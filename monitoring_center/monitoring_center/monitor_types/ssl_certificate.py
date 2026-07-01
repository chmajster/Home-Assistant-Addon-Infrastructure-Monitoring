from __future__ import annotations

import asyncio
import socket
import ssl
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from ..config import AppConfig
from .base import CheckResult, MonitorContext, normalize_timeout_config, positive_int, timeout_seconds_from_config


class SslCertificateMonitor:
    type = "ssl_certificate"
    label = "Certyfikat SSL"
    category = "website"
    default_interval = 21600

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        host, port = _host_port(target, config)
        config["host"] = host
        config["port"] = port
        config["warning_days"] = positive_int(config.get("warning_days"), 30, 1, 3650)
        config["error_days"] = positive_int(config.get("error_days"), 7, 0, 3650)
        normalize_timeout_config(config, app_config.default_timeout_minutes * 60)
        return f"{host}:{port}", config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        try:
            host, port = _host_port(monitor["target"], monitor["config"])
            timeout = timeout_seconds_from_config(monitor["config"], context.config.default_timeout_minutes * 60)
            warning_days = positive_int(monitor["config"].get("warning_days"), 30, 1, 3650)
            error_days = positive_int(monitor["config"].get("error_days"), 7, 0, 3650)
            started = time.perf_counter()
            cert = await asyncio.wait_for(asyncio.to_thread(_fetch_cert, host, port, timeout), timeout=timeout + 1)
            elapsed_ms = (time.perf_counter() - started) * 1000
            expires_at = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
            days_left = (expires_at - datetime.now(UTC)).days
            status = "ok"
            events: list[str] = []
            if days_left <= error_days:
                status = "error"
                events.append("ssl_certificate_expiring")
            elif days_left <= warning_days:
                status = "warning"
                events.append("ssl_certificate_expiring")
            return CheckResult(
                status,
                response_ms=elapsed_ms,
                details={
                    "host": host,
                    "port": port,
                    "expires_at": expires_at.isoformat(),
                    "days_left": days_left,
                    "warning_days": warning_days,
                    "error_days": error_days,
                    "subject": cert.get("subject"),
                    "issuer": cert.get("issuer"),
                },
                events=events,
            )
        except Exception as exc:
            return CheckResult("error", error=str(exc))


def _fetch_cert(host: str, port: int, timeout: float) -> dict[str, Any]:
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            return tls.getpeercert()


def _host_port(target: str, config: dict[str, Any]) -> tuple[str, int]:
    value = target.strip()
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = str(config.get("host") or parsed.hostname or value).strip()
    port = positive_int(config.get("port") or parsed.port, 443, 1, 65535)
    return host, port
