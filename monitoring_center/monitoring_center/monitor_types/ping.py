from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from ..config import AppConfig
from ..validators import validate_device_target
from .base import CheckResult, MonitorContext, positive_int


class PingHostMonitor:
    type = "ping_host"
    label = "Ping hosta"
    category = "network"
    default_interval = 60

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        normalized = validate_device_target(target)
        config["timeout_seconds"] = positive_int(
            config.get("timeout_seconds"),
            app_config.ping_timeout_seconds,
            minimum=1,
            maximum=30,
        )
        return normalized, config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        try:
            target = validate_device_target(monitor["target"])
            timeout = positive_int(
                monitor["config"].get("timeout_seconds"),
                context.config.ping_timeout_seconds,
                minimum=1,
                maximum=30,
            )
            started = time.perf_counter()
            process = await asyncio.create_subprocess_exec(
                "ping",
                "-c",
                "1",
                "-W",
                str(timeout),
                target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            elapsed_ms = (time.perf_counter() - started) * 1000
            output = (stdout + stderr).decode(errors="replace")
            response_ms = _parse_ping_time(output) or elapsed_ms
            packet_loss = _parse_packet_loss(output, process.returncode)
            if process.returncode == 0:
                return CheckResult(
                    "online",
                    response_ms=response_ms,
                    packet_loss=packet_loss,
                    details={"host": target, "timeout_seconds": timeout},
                )
            return CheckResult(
                "offline",
                packet_loss=packet_loss,
                error=_short_error(output) or "Ping failed",
                details={"host": target, "timeout_seconds": timeout},
            )
        except Exception as exc:
            return CheckResult("offline", error=str(exc), packet_loss=100.0)


def _parse_ping_time(output: str) -> float | None:
    match = re.search(r"time[=<]([\d.]+)\s*ms", output)
    return float(match.group(1)) if match else None


def _parse_packet_loss(output: str, return_code: int) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", output)
    if match:
        return float(match.group(1))
    return 0.0 if return_code == 0 else 100.0


def _short_error(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""
