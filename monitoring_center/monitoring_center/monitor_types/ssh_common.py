from __future__ import annotations

import asyncio
import re
import shlex
import time
from dataclasses import dataclass
from typing import Any

from ..config import AppConfig
from .base import positive_int


@dataclass(slots=True)
class SshCommandResult:
    exit_code: int | None
    stdout: str
    stderr: str
    elapsed_ms: float


def normalize_ssh_config(
    target: str,
    config: dict[str, Any],
    app_config: AppConfig,
    *,
    require_username: bool = True,
) -> tuple[str, dict[str, Any]]:
    host = str(config.get("host") or "").strip()
    port_value = config.get("port")
    if not host:
        if target.count(":") == 1:
            host, port_text = target.rsplit(":", 1)
            port_value = port_value or port_text
        else:
            host = target.strip()
    if not host:
        raise ValueError("SSH host is required")
    config["host"] = host
    config["port"] = positive_int(port_value, 22, 1, 65535)
    username = str(config.get("username") or "").strip()
    if require_username and not username:
        raise ValueError("SSH username is required")
    config["username"] = username
    auth_method = str(config.get("auth_method") or "password").strip()
    if auth_method not in {"password", "private_key"}:
        raise ValueError("auth_method must be password or private_key")
    config["auth_method"] = auth_method
    config["known_hosts_policy"] = str(config.get("known_hosts_policy") or "auto_add").strip()
    config["connect_timeout_seconds"] = positive_int(
        config.get("connect_timeout_seconds"),
        int(app_config.default_timeout_minutes * 60),
        1,
        300,
    )
    return f"{host}:{config['port']}", config


async def run_ssh_command(config: dict[str, Any], command: str | None = None) -> SshCommandResult:
    try:
        import asyncssh
    except ImportError as exc:  # pragma: no cover - depends on add-on image
        raise RuntimeError("asyncssh is required for SSH based monitors") from exc

    connect_timeout = float(config.get("connect_timeout_seconds") or 10)
    command_timeout = float(config.get("command_timeout_seconds") or 30)
    max_output_chars = positive_int(config.get("max_output_chars"), 4000, 1, 200000)
    connect_kwargs: dict[str, Any] = {
        "host": config["host"],
        "port": int(config.get("port") or 22),
        "username": config.get("username") or None,
    }
    if config.get("known_hosts_policy") == "auto_add":
        connect_kwargs["known_hosts"] = None
    if config.get("auth_method") == "password":
        connect_kwargs["password"] = config.get("password") or None
    elif config.get("private_key"):
        key = asyncssh.import_private_key(
            str(config.get("private_key")),
            passphrase=str(config.get("private_key_passphrase") or "") or None,
        )
        connect_kwargs["client_keys"] = [key]

    started = time.perf_counter()
    conn = await asyncio.wait_for(asyncssh.connect(**connect_kwargs), timeout=connect_timeout)
    try:
        if not command:
            return SshCommandResult(None, "", "", (time.perf_counter() - started) * 1000)
        result = await conn.run(_shell_command(command, config), timeout=command_timeout, check=False)
        return SshCommandResult(
            int(result.exit_status or 0),
            _limit_output(result.stdout, max_output_chars),
            _limit_output(result.stderr, max_output_chars),
            (time.perf_counter() - started) * 1000,
        )
    finally:
        conn.close()
        await conn.wait_closed()


def regex_matches(pattern: str | None, value: str) -> bool:
    if not pattern:
        return False
    try:
        return re.search(str(pattern), value, re.MULTILINE) is not None
    except re.error:
        return False


def quote(value: Any) -> str:
    return shlex.quote(str(value))


def _shell_command(command: str, config: dict[str, Any]) -> str:
    shell = str(config.get("shell") or "bash").strip()
    if shell in {"bash", "sh", "zsh"}:
        return f"{shell} -lc {shlex.quote(command)}"
    return command


def _limit_output(value: str | bytes | None, max_chars: int) -> str:
    if value is None:
        return ""
    text = value.decode(errors="replace") if isinstance(value, bytes) else str(value)
    return text[:max_chars]
