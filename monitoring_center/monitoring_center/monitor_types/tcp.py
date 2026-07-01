from __future__ import annotations

import asyncio
import time
from typing import Any

from ..config import AppConfig
from ..validators import validate_device_target
from .base import CheckResult, MonitorContext, normalize_timeout_config, positive_int, timeout_seconds_from_config


class TcpPortMonitor:
    type = "tcp_port"
    label = "Port TCP"
    category = "network"
    default_interval = 60

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        host, port = _host_port(target, config)
        validate_device_target(host)
        config["host"] = host
        config["port"] = port
        normalize_timeout_config(config, app_config.default_timeout_minutes * 60, minimum=0.1)
        return f"{host}:{port}", config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        host, port = _host_port(monitor["target"], monitor["config"])
        timeout = timeout_seconds_from_config(
            monitor["config"],
            context.config.default_timeout_minutes * 60,
            minimum=0.1,
        )
        started = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
            writer.close()
            await writer.wait_closed()
            elapsed_ms = (time.perf_counter() - started) * 1000
            return CheckResult(
                "open",
                response_ms=elapsed_ms,
                details={"host": host, "port": port, "timeout_seconds": timeout},
                events=["tcp_port_open"],
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return CheckResult(
                "timeout",
                response_ms=elapsed_ms,
                error=f"TCP connection to {host}:{port} timed out",
                details={"host": host, "port": port, "timeout_seconds": timeout},
                events=["tcp_port_closed"],
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return CheckResult(
                "closed",
                response_ms=elapsed_ms,
                error=str(exc),
                details={"host": host, "port": port, "timeout_seconds": timeout},
                events=["tcp_port_closed"],
            )


def _host_port(target: str, config: dict[str, Any]) -> tuple[str, int]:
    host = str(config.get("host") or "").strip()
    port_value = config.get("port")
    if not host:
        if target.count(":") == 1:
            host, port_text = target.rsplit(":", 1)
            port_value = port_value or port_text
        else:
            host = target.strip()
    port = positive_int(port_value, 80, 1, 65535)
    return host.strip(), port
