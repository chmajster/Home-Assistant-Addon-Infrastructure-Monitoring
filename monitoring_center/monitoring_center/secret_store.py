from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .database import Database, dumps_json, loads_json
from .security import is_secret_key, register_secret

PREFIX = "mc:v1:"


class SecretStoreError(RuntimeError):
    pass


class SecretStore:
    """Versioned AES-256-GCM storage, bound to monitor and field names with AAD."""

    def __init__(self, db: Database, key_path: Path) -> None:
        self.db = db
        self.key_path = key_path
        self._key = self._load_or_create_key()

    def _load_or_create_key(self) -> bytes:
        encrypted = self.db.fetchone(
            """SELECT 1 AS present FROM monitor_secrets
               UNION ALL SELECT 1 AS present FROM credential_secrets LIMIT 1"""
        )
        if self.key_path.exists():
            try:
                key = self.key_path.read_bytes()
            except OSError as exc:
                raise SecretStoreError("Nie można odczytać klucza głównego") from exc
            if len(key) != 32:
                raise SecretStoreError("Klucz główny jest uszkodzony")
            return key
        if encrypted:
            raise SecretStoreError("Brak klucza głównego dla istniejących zaszyfrowanych danych")
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        key = AESGCM.generate_key(bit_length=256)
        try:
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(key)
            os.chmod(self.key_path, 0o600)
        except FileExistsError:
            return self._load_or_create_key()
        return key

    def encrypt(self, value: Any, monitor_id: int, field: str) -> str:
        return self._encrypt(value, f"monitor:{monitor_id}:{field}:v1")

    def decrypt(self, value: str, monitor_id: int, field: str) -> Any:
        return self._decrypt(value, f"monitor:{monitor_id}:{field}:v1")

    def encrypt_credential(self, value: Any, credential_id: int, field: str) -> str:
        return self._encrypt(value, f"credential:{credential_id}:{field}:v1")

    def decrypt_credential(self, value: str, credential_id: int, field: str) -> Any:
        return self._decrypt(value, f"credential:{credential_id}:{field}:v1")

    def _encrypt(self, value: Any, aad: str) -> str:
        register_secret(value)
        nonce = os.urandom(12)
        plaintext = json.dumps(value, ensure_ascii=False).encode()
        encrypted = AESGCM(self._key).encrypt(nonce, plaintext, aad.encode())
        import base64

        return PREFIX + base64.urlsafe_b64encode(nonce + encrypted).decode()

    def _decrypt(self, value: str, aad: str) -> Any:
        if not value.startswith(PREFIX):
            raise SecretStoreError("Nieobsługiwany format zaszyfrowanej wartości")
        import base64

        try:
            raw = base64.urlsafe_b64decode(value.removeprefix(PREFIX))
            plaintext = AESGCM(self._key).decrypt(raw[:12], raw[12:], aad.encode())
            result = json.loads(plaintext)
            register_secret(result)
            return result
        except Exception as exc:
            raise SecretStoreError("Nie można odszyfrować sekretu; sprawdź klucz główny") from exc

    def update_credential_secrets(
        self,
        credential_id: int,
        values: dict[str, Any],
        clear_fields: set[str] | None = None,
    ) -> None:
        with self.db.transaction():
            for field in clear_fields or set():
                self.db.execute(
                    "DELETE FROM credential_secrets WHERE credential_id=? AND field=?",
                    (credential_id, field),
                )
            for field, value in values.items():
                if value in (None, "", "********"):
                    continue
                self.db.execute(
                    """INSERT INTO credential_secrets(credential_id, field, encrypted_value, updated_at)
                       VALUES (?, ?, ?, datetime('now'))
                       ON CONFLICT(credential_id, field) DO UPDATE SET
                         encrypted_value=excluded.encrypted_value, updated_at=datetime('now')""",
                    (credential_id, field, self.encrypt_credential(value, credential_id, field)),
                )

    def credential_secrets(self, credential_id: int) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for row in self.db.fetchall(
            "SELECT field, encrypted_value FROM credential_secrets WHERE credential_id=?",
            (credential_id,),
        ):
            values[row["field"]] = self.decrypt_credential(row["encrypted_value"], credential_id, row["field"])
        return values

    def split_config(self, monitor_id: int, config: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        with self.db.transaction():
            for key, value in config.items():
                if is_secret_key(key):
                    if value not in (None, ""):
                        self.db.execute(
                            """INSERT INTO monitor_secrets(monitor_id, field, encrypted_value, updated_at)
                               VALUES (?, ?, ?, datetime('now'))
                               ON CONFLICT(monitor_id, field) DO UPDATE SET
                                 encrypted_value=excluded.encrypted_value, updated_at=datetime('now')""",
                            (monitor_id, key, self.encrypt(value, monitor_id, key)),
                        )
                elif isinstance(value, dict):
                    clean[key] = self._split_nested(monitor_id, key, value)
                else:
                    clean[key] = value
        return clean

    def _split_nested(self, monitor_id: int, prefix: str, value: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, item in value.items():
            field = f"{prefix}.{key}"
            if is_secret_key(key):
                if item not in (None, ""):
                    self.db.execute(
                        """INSERT INTO monitor_secrets(monitor_id, field, encrypted_value, updated_at)
                           VALUES (?, ?, ?, datetime('now')) ON CONFLICT(monitor_id, field) DO UPDATE SET
                           encrypted_value=excluded.encrypted_value, updated_at=datetime('now')""",
                        (monitor_id, field, self.encrypt(item, monitor_id, field)),
                    )
            elif isinstance(item, dict):
                clean[key] = self._split_nested(monitor_id, field, item)
            else:
                clean[key] = item
        return clean

    def hydrate(self, monitor_id: int, config: dict[str, Any]) -> dict[str, Any]:
        hydrated = json.loads(dumps_json(config))
        for row in self.db.fetchall(
            "SELECT field, encrypted_value FROM monitor_secrets WHERE monitor_id = ?", (monitor_id,)
        ):
            path = row["field"].split(".")
            target = hydrated
            for part in path[:-1]:
                target = target.setdefault(part, {})
            target[path[-1]] = self.decrypt(row["encrypted_value"], monitor_id, row["field"])
            register_secret(target[path[-1]])
        return hydrated

    def migrate_plaintext(self) -> int:
        migrated = 0
        with self.db.transaction():
            for row in self.db.fetchall("SELECT id, config_json FROM monitors"):
                config = loads_json(row["config_json"], {})
                clean = self.split_config(int(row["id"]), config)
                if clean != config:
                    self.db.execute("UPDATE monitors SET config_json=? WHERE id=?", (dumps_json(clean), row["id"]))
                    migrated += 1
        if migrated:
            # A pre-schema backup may contain legacy plaintext. Replace only backups
            # generated by our migration with a consistent post-encryption copy.
            for backup in self.db.path.parent.glob(f"{self.db.path.name}.schema-*.bak"):
                backup.unlink(missing_ok=True)
            version = self.db.fetchone("SELECT MAX(version) AS version FROM schema_migrations") or {"version": 0}
            self.db.backup(self.db.path.with_suffix(f"{self.db.path.suffix}.schema-{version['version']}.encrypted.bak"))
        return migrated

    def rotate(self, new_key: bytes) -> None:
        if len(new_key) != 32:
            raise ValueError("Klucz rotacji musi mieć 32 bajty")
        values = [
            (row["monitor_id"], row["field"], self.decrypt(row["encrypted_value"], row["monitor_id"], row["field"]))
            for row in self.db.fetchall("SELECT * FROM monitor_secrets")
        ]
        credential_values = [
            (
                row["credential_id"],
                row["field"],
                self.decrypt_credential(row["encrypted_value"], row["credential_id"], row["field"]),
            )
            for row in self.db.fetchall("SELECT * FROM credential_secrets")
        ]
        old_key = self._key
        self._key = new_key
        try:
            with self.db.transaction():
                for monitor_id, field, value in values:
                    self.db.execute(
                        """UPDATE monitor_secrets SET encrypted_value=?, updated_at=datetime('now')
                           WHERE monitor_id=? AND field=?""",
                        (self.encrypt(value, monitor_id, field), monitor_id, field),
                    )
                for credential_id, field, value in credential_values:
                    self.db.execute(
                        """UPDATE credential_secrets SET encrypted_value=?, updated_at=datetime('now')
                           WHERE credential_id=? AND field=?""",
                        (self.encrypt_credential(value, credential_id, field), credential_id, field),
                    )
            temporary = self.key_path.with_suffix(".new")
            temporary.write_bytes(new_key)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.key_path)
        except Exception:
            self._key = old_key
            raise
