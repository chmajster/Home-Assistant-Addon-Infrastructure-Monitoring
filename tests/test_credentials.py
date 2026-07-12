from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from monitoring_center.config import AppConfig
from monitoring_center.database import Database
from monitoring_center.monitor_types.base import CheckResult
from monitoring_center.monitoring import MonitorService
from monitoring_center.secret_store import SecretStore, SecretStoreError
from monitoring_center.security import sanitize_secrets


def _password_profile(service: MonitorService, name: str = "Wspólny login") -> dict:
    return service.create_credential(
        {
            "name": name,
            "kind": "username_password",
            "username": "operator",
            "password": "characteristic-password-123",
            "description": "Profil testowy",
        }
    )


def _key_profile(service: MonitorService, name: str = "Klucz NAS") -> dict:
    return service.create_credential(
        {
            "name": name,
            "kind": "ssh_private_key",
            "username": "root",
            "private_key": "-----BEGIN PRIVATE KEY-----\nkey-material\n-----END PRIVATE KEY-----",
            "private_key_passphrase": "key-passphrase-123",
        }
    )


def test_credentials_encrypt_secrets_and_return_only_metadata(
    db: Database, app_config: AppConfig, ha_client: object
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _password_profile(service)
    row = db.fetchone("SELECT * FROM credential_profiles WHERE id=?", (profile["id"],))
    secret = db.fetchone("SELECT * FROM credential_secrets WHERE credential_id=?", (profile["id"],))

    assert row and "password" not in row
    assert secret and "characteristic-password-123" not in secret["encrypted_value"]
    assert profile["has_password"] is True
    assert "password" not in profile
    assert service.secrets.credential_secrets(profile["id"])["password"] == "characteristic-password-123"


def test_ssh_profile_uses_profile_specific_aad(db: Database, app_config: AppConfig, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _key_profile(service)
    encrypted = db.fetchone(
        "SELECT encrypted_value FROM credential_secrets WHERE credential_id=? AND field='private_key'",
        (profile["id"],),
    )

    assert encrypted
    with pytest.raises(SecretStoreError):
        service.secrets.decrypt(encrypted["encrypted_value"], profile["id"], "private_key")
    assert service.secrets.decrypt_credential(encrypted["encrypted_value"], profile["id"], "private_key").startswith(
        "-----BEGIN"
    )


def test_credential_update_preserves_blank_and_can_clear_secret(
    db: Database, app_config: AppConfig, ha_client: object
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _password_profile(service)

    service.update_credential(profile["id"], {"password": "", "description": "Zmieniony opis"})
    assert service.secrets.credential_secrets(profile["id"])["password"] == "characteristic-password-123"
    service.update_credential(profile["id"], {"password": "********"})
    assert service.secrets.credential_secrets(profile["id"])["password"] == "characteristic-password-123"
    updated = service.update_credential(profile["id"], {"clear_secret_fields": ["password"]})
    assert updated["has_password"] is False


def test_credential_name_conflict_and_delete_guard(db: Database, app_config: AppConfig, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _password_profile(service, "NAS root")
    with pytest.raises(HTTPException) as conflict:
        _password_profile(service, "nas ROOT")
    assert conflict.value.status_code == 409

    monitor_id = service._insert_monitor(
        {
            "type": "mqtt_monitor",
            "name": "MQTT",
            "target": "broker:1883",
            "interval_seconds": 60,
            "group_id": None,
            "credential_id": profile["id"],
            "enabled": True,
            "config": {"host": "broker", "port": 1883},
        }
    )
    with pytest.raises(HTTPException) as in_use:
        service.delete_credential(profile["id"])
    assert in_use.value.status_code == 409
    assert "1 monitor" in str(in_use.value.detail)
    service.delete_monitor(monitor_id)
    service.delete_credential(profile["id"])
    assert service.list_credentials() == []


def test_monitor_exposes_safe_credential_reference_and_rejects_incompatible_profile(
    db: Database, app_config: AppConfig, ha_client: object
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _key_profile(service)
    monitor_id = service._insert_monitor(
        {
            "type": "ssh_command",
            "name": "SSH",
            "target": "server:22",
            "interval_seconds": 60,
            "group_id": None,
            "credential_id": profile["id"],
            "enabled": True,
            "config": {"host": "server", "port": 22},
        }
    )
    monitor = service.get_monitor(monitor_id)

    assert monitor["credential"] == {
        "id": profile["id"],
        "name": "Klucz NAS",
        "kind": "ssh_private_key",
        "username": "root",
    }
    assert "key-material" not in json.dumps(monitor)
    with pytest.raises(HTTPException) as incompatible:
        service._normalize_payload(
            {
                "type": "mqtt_monitor",
                "name": "MQTT",
                "target": "broker:1883",
                "credential_id": profile["id"],
                "config": {},
            }
        )
    assert incompatible.value.status_code == 422


def test_effective_credentials_override_direct_values_and_update_immediately(
    db: Database, app_config: AppConfig, ha_client: object
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _password_profile(service)
    monitor = {
        "id": 1,
        "type": "ssh_command",
        "credential_id": profile["id"],
        "config": {"username": "legacy", "password": "legacy-password", "host": "server"},
    }

    effective = service._monitor_with_effective_credentials(monitor)
    assert effective["config"]["username"] == "operator"
    assert effective["config"]["password"] == "characteristic-password-123"
    assert monitor["config"]["password"] == "legacy-password"
    service.update_credential(profile["id"], {"password": "new-shared-password"})
    assert service._monitor_with_effective_credentials(monitor)["config"]["password"] == "new-shared-password"


def test_private_key_and_passphrase_are_injected_only_in_memory(
    db: Database, app_config: AppConfig, ha_client: object
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _key_profile(service)
    monitor = {"id": 1, "type": "ssh_command", "credential_id": profile["id"], "config": {"host": "nas"}}

    effective = service._monitor_with_effective_credentials(monitor)
    assert effective["config"]["auth_method"] == "private_key"
    assert effective["config"]["private_key"].startswith("-----BEGIN")
    assert effective["config"]["private_key_passphrase"] == "key-passphrase-123"
    assert "private_key" not in monitor["config"]


def test_legacy_direct_credentials_still_work(db: Database, app_config: AppConfig, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monitor = {
        "id": 1,
        "type": "ssh_command",
        "credential_id": None,
        "config": {"username": "legacy", "password": "legacy-password"},
    }
    assert service._monitor_with_effective_credentials(monitor) is monitor


def test_master_key_rotation_covers_credential_secrets(db: Database, app_config: AppConfig, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _password_profile(service)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    service.secrets.rotate(AESGCM.generate_key(bit_length=256))
    assert service.secrets.credential_secrets(profile["id"])["password"] == "characteristic-password-123"


def test_missing_master_key_is_not_regenerated_when_credential_secrets_exist(
    db: Database, app_config: AppConfig, ha_client: object
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    _password_profile(service)
    service.secrets.key_path.unlink()

    with pytest.raises(SecretStoreError, match="Brak klucza głównego"):
        SecretStore(db, service.secrets.key_path)


def test_credential_values_are_registered_for_log_redaction(
    db: Database, app_config: AppConfig, ha_client: object
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    _password_profile(service)

    assert sanitize_secrets("failure characteristic-password-123") == "failure ********"


def test_credentials_api_never_returns_secrets(
    db: Database, app_config: AppConfig, ha_client: object, monkeypatch
) -> None:
    from monitoring_center import main as app_main

    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monkeypatch.setattr(app_main, "service", service)
    client = TestClient(app_main.app)
    created = client.post(
        "/api/credentials",
        json={
            "name": "API profile",
            "kind": "username_password",
            "username": "api-user",
            "password": "api-characteristic-password",
        },
    )
    listed = client.get("/api/credentials")

    assert created.status_code == 200
    assert listed.status_code == 200
    assert "api-characteristic-password" not in created.text
    assert "api-characteristic-password" not in listed.text
    assert listed.json()[0]["has_password"] is True


def test_monitor_import_clears_missing_credential_and_returns_warning(
    db: Database, app_config: AppConfig, ha_client: object, monkeypatch
) -> None:
    from monitoring_center import main as app_main

    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monkeypatch.setattr(app_main, "service", service)
    response = TestClient(app_main.app).post(
        "/api/monitors/import",
        json={
            "monitors": [
                {
                    "type": "ping_host",
                    "name": "Import",
                    "target": "192.0.2.1",
                    "credential_id": 9999,
                    "test_on_save": False,
                    "config": {},
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["warnings"]
    assert response.json()["monitors"][0]["credential_id"] is None


@pytest.mark.parametrize("monitor_type", ["mqtt_monitor", "ssh_command"])
def test_unsaved_monitor_test_injects_password_profile(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
    monitor_type: str,
) -> None:
    from monitoring_center import monitoring as monitoring_module

    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _password_profile(service)
    captured: dict = {}

    class CapturingPlugin:
        def validate(self, target: str, config: dict, app_config: AppConfig) -> tuple[str, dict]:
            return target, config

        async def check(self, monitor: dict, context: object) -> CheckResult:
            captured.update(monitor["config"])
            return CheckResult("ok")

    monkeypatch.setattr(monitoring_module, "get_plugin", lambda kind: CapturingPlugin())
    result = asyncio.run(
        service.test_monitor(
            {
                "type": monitor_type,
                "name": "Test",
                "target": "server:22",
                "credential_id": profile["id"],
                "config": {"username": "legacy", "password": "legacy-password"},
            }
        )
    )

    assert result["success"] is True
    assert captured["username"] == "operator"
    assert captured["password"] == "characteristic-password-123"
    assert captured["auth_method"] == "password"


def test_unsaved_ssh_test_injects_private_key_profile(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    from monitoring_center import monitoring as monitoring_module

    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _key_profile(service)
    captured: dict = {}

    class CapturingPlugin:
        def validate(self, target: str, config: dict, app_config: AppConfig) -> tuple[str, dict]:
            return target, config

        async def check(self, monitor: dict, context: object) -> CheckResult:
            captured.update(monitor["config"])
            return CheckResult("ok")

    monkeypatch.setattr(monitoring_module, "get_plugin", lambda kind: CapturingPlugin())
    result = asyncio.run(
        service.test_monitor(
            {
                "type": "ssh_command",
                "name": "Test SSH",
                "target": "server:22",
                "credential_id": profile["id"],
                "config": {},
            }
        )
    )

    assert result["success"] is True
    assert captured["private_key"].startswith("-----BEGIN")
    assert captured["private_key_passphrase"] == "key-passphrase-123"
    assert captured["auth_method"] == "private_key"


def test_missing_profile_secret_returns_safe_test_error(db: Database, app_config: AppConfig, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _password_profile(service)
    service.update_credential(profile["id"], {"clear_secret_fields": ["password"]})

    result = asyncio.run(
        service.test_monitor(
            {
                "type": "mqtt_monitor",
                "name": "MQTT",
                "target": "broker:1883",
                "credential_id": profile["id"],
                "config": {},
            }
        )
    )

    assert result["success"] is False
    assert "nie zawiera hasła" in result["error"]
    assert "characteristic-password" not in json.dumps(result)


def test_credential_decryption_failure_returns_safe_test_error(
    db: Database, app_config: AppConfig, ha_client: object
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    profile = _password_profile(service)
    db.execute(
        "UPDATE credential_secrets SET encrypted_value='mc:v1:invalid' WHERE credential_id=?",
        (profile["id"],),
    )

    result = asyncio.run(
        service.test_monitor(
            {
                "type": "mqtt_monitor",
                "name": "MQTT",
                "target": "broker:1883",
                "credential_id": profile["id"],
                "config": {},
            }
        )
    )

    assert result["success"] is False
    assert "Nie można odszyfrować profilu" in result["error"]
    assert "invalid" not in result["error"]
