from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

from ..config import AppConfig
from ..validators import ensure_public_url_if_required, validate_url
from .base import CheckResult, MonitorContext, csv_ints, normalize_timeout_config, timeout_seconds_from_config


class RestApiMonitor:
    type = "rest_api"
    label = "REST API"
    category = "website"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        config["expected_status_codes"] = csv_ints(config.get("expected_status_codes"), [200])
        normalize_timeout_config(config, app_config.default_timeout_minutes * 60)
        return validate_url(target), config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        try:
            url = validate_url(monitor["target"])
            ensure_public_url_if_required(url, bool(context.settings["block_private_networks"]))
            timeout = timeout_seconds_from_config(
                monitor["config"],
                float(context.settings["default_timeout_minutes"]) * 60,
            )
            expected_codes = csv_ints(monitor["config"].get("expected_status_codes"), [200])
            started = time.perf_counter()
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=False) as client:
                response = await client.get(url, headers={"User-Agent": "MonitoringCenter/0.2"})
            elapsed_ms = (time.perf_counter() - started) * 1000
            details: dict[str, Any] = {
                "expected_status_codes": expected_codes,
                "response_hash": hashlib.sha256(response.content).hexdigest(),
                "response_excerpt": response.text[:1000],
            }
            status = "ok" if response.status_code in expected_codes else "error"
            json_path = str(monitor["config"].get("json_path") or "").strip()
            if json_path:
                value = _json_path(response.json(), json_path)
                expected_value = monitor["config"].get("expected_value")
                details["json_path"] = json_path
                details["actual_value"] = value
                details["expected_value"] = expected_value
                if expected_value is not None and str(value) != str(expected_value):
                    status = "error"
            return CheckResult(
                status,
                response_ms=elapsed_ms,
                http_status=response.status_code,
                error=None if status == "ok" else "REST API check failed",
                details=details,
                events=["rest_api_check_failed"] if status == "error" else [],
            )
        except Exception as exc:
            return CheckResult("error", error=str(exc), events=["rest_api_check_failed"])


def _json_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current
