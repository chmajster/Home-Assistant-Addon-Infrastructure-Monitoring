from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import AppConfig
from ..ha import get_supervisor_token
from .base import CheckResult, MonitorContext, normalize_timeout_config, timeout_seconds_from_config


class HomeAssistantEntityMonitor:
    type = "ha_entity"
    label = "Encja Home Assistant"
    category = "home_assistant"
    default_interval = 60

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        entity_id = target.strip()
        if "." not in entity_id:
            raise ValueError("Home Assistant entity_id is required")
        normalize_timeout_config(config, app_config.default_timeout_minutes * 60)
        alert_states = config.get("alert_states") or ["unavailable", "unknown"]
        config["alert_states"] = alert_states if isinstance(alert_states, list) else str(alert_states).split(",")
        return entity_id, config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        token = get_supervisor_token()
        if not token:
            return CheckResult("error", error="SUPERVISOR_TOKEN is not available")
        timeout = timeout_seconds_from_config(monitor["config"], context.config.default_timeout_minutes * 60)
        alert_states = [str(item).strip() for item in monitor["config"].get("alert_states", []) if str(item).strip()]
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    f"http://supervisor/core/api/states/{monitor['target']}",
                    headers={"Authorization": f"Bearer {token}"},
                )
            elapsed_ms = (time.perf_counter() - started) * 1000
            if response.status_code == 404:
                return CheckResult("error", response_ms=elapsed_ms, error="Entity does not exist")
            response.raise_for_status()
            payload = response.json()
            state = payload.get("state")
            previous_state = monitor["config"].get("last_ha_state")
            changed = bool(previous_state is not None and previous_state != state)
            status = "error" if state in alert_states else "ok"
            return CheckResult(
                status,
                response_ms=elapsed_ms,
                content_changed=changed,
                error=f"Entity state is {state}" if status == "error" else None,
                details={
                    "entity_id": monitor["target"],
                    "state": state,
                    "previous_state": previous_state,
                    "state_changed": changed,
                    "attributes": payload.get("attributes", {}),
                    "alert_states": alert_states,
                },
                events=["ha_entity_state_changed"] if changed or status == "error" else [],
            )
        except Exception as exc:
            return CheckResult("error", error=str(exc))
