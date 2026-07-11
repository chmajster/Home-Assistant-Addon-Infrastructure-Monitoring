from __future__ import annotations

from typing import Any

MASKED_SECRET = "********"

SECRET_KEYS = {
    "api_key",
    "api_token",
    "authorization",
    "bearer_token",
    "community",
    "passphrase",
    "password",
    "private_key",
    "private_key_passphrase",
    "secret",
    "snmp_community",
    "token",
    "webhook_url",
}
_SECRET_VALUES: set[str] = set()


def register_secret(value: Any) -> None:
    if isinstance(value, str) and len(value) >= 4 and value != MASKED_SECRET:
        _SECRET_VALUES.add(value)


def redact_text(value: str) -> str:
    redacted = value
    for secret in sorted(_SECRET_VALUES, key=len, reverse=True):
        redacted = redacted.replace(secret, MASKED_SECRET)
    return redacted


def is_secret_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in SECRET_KEYS or normalized.endswith("_token") or normalized.endswith("_password")


def is_blank_secret(value: Any) -> bool:
    return value is None or value == "" or value == MASKED_SECRET


def sanitize_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            sanitized[key] = (
                MASKED_SECRET if is_secret_key(str(key)) and item not in (None, "") else sanitize_secrets(item)
            )
        return sanitized
    if isinstance(value, list):
        return [sanitize_secrets(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def preserve_existing_secrets(new_config: dict[str, Any], current_config: dict[str, Any]) -> dict[str, Any]:
    merged = dict(new_config)
    for key, previous in current_config.items():
        if is_secret_key(str(key)):
            if key not in merged or is_blank_secret(merged.get(key)):
                if previous not in (None, "", MASKED_SECRET):
                    merged[key] = previous
        elif isinstance(previous, dict) and isinstance(merged.get(key), dict):
            merged[key] = preserve_existing_secrets(merged[key], previous)
    return merged
