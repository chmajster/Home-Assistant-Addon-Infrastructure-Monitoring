from __future__ import annotations

import os
from typing import Any

import httpx

from ..config import AppConfig
from .base import CheckResult, MonitorContext, normalize_timeout_config, timeout_seconds_from_config


class MonitoringCenterHealthMonitor:
    type = "monitoring_center_health"
    label = "Monitoring Center Health"
    category = "system"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        normalize_timeout_config(config, app_config.default_timeout_minutes * 60)
        return target.strip() or "self", config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        timeout = timeout_seconds_from_config(monitor["config"], context.config.default_timeout_minutes * 60)
        port = int(os.environ.get("MONITORING_CENTER_PORT", "8099"))
        url = f"http://127.0.0.1:{port}/api/diagnostics/full"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            return CheckResult("error", error=str(exc), events=["diagnostics_self_check"])

        checks = {
            "scheduler": bool(data.get("scheduler_running")),
            "database": bool(data.get("database_exists")),
            "data_writable": bool(data.get("data_writable", {}).get("ok")),
            "ha_api": bool(data.get("home_assistant_api", {}).get("ok"))
            or not bool(data.get("home_assistant_api", {}).get("available")),
            "log_file": bool(data.get("log_file_status", {}).get("writable")),
        }
        ok = all(checks.values()) and int(data.get("scheduler_error_count") or 0) == 0
        return CheckResult(
            "online" if ok else "warning",
            details={"checks": checks, "diagnostics": data},
            error=None if ok else "Monitoring Center self-check warning",
            events=[] if ok else ["diagnostics_self_check"],
        )
