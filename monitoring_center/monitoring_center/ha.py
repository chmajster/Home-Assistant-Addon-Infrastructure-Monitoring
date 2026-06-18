from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from .config import AppConfig

LOGGER = logging.getLogger(__name__)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", value.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "monitor"


class HomeAssistantClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.base_url = "http://supervisor/core/api"
        self.token = os.environ.get("SUPERVISOR_TOKEN")

    @property
    def available(self) -> bool:
        return bool(self.token)

    async def publish_monitor_state(self, monitor: dict[str, Any]) -> None:
        if not self.config.publish_home_assistant_entities or not self.available:
            return

        prefix = slugify(self.config.entity_prefix)
        monitor_slug = slugify(f"{monitor['id']}_{monitor['name']}")
        status = monitor.get("status", "unknown")
        is_online = status in {"online", "ok"}
        attrs = {
            "friendly_name": monitor["name"],
            "monitor_type": monitor["type"],
            "target": monitor["target"],
            "last_checked_at": monitor.get("last_checked_at"),
            "last_error": monitor.get("last_error"),
            "response_ms": monitor.get("last_response_ms"),
        }

        await self._set_state(
            f"binary_sensor.{prefix}_{monitor_slug}_status",
            "on" if is_online else "off",
            {**attrs, "device_class": "connectivity"},
        )
        await self._set_state(
            f"sensor.{prefix}_{monitor_slug}_response_time",
            _number_or_unknown(monitor.get("last_response_ms")),
            {**attrs, "unit_of_measurement": "ms", "state_class": "measurement"},
        )
        await self._set_state(
            f"sensor.{prefix}_{monitor_slug}_last_error",
            monitor.get("last_error") or "none",
            attrs,
        )

        if monitor["type"] == "website":
            await self._set_state(
                f"sensor.{prefix}_{monitor_slug}_http_status",
                monitor.get("last_http_status") or "unknown",
                attrs,
            )
            await self._set_state(
                f"sensor.{prefix}_{monitor_slug}_last_change",
                monitor.get("last_changed_at") or "unknown",
                attrs,
            )
            await self._set_state(
                f"sensor.{prefix}_{monitor_slug}_change_count",
                monitor.get("change_count", 0),
                {**attrs, "state_class": "total_increasing"},
            )

    async def fire_event(self, event_type: str, payload: dict[str, Any]) -> bool:
        if not self.config.publish_home_assistant_events or not self.available:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.base_url}/events/{event_type}",
                    headers=self._headers,
                    json=payload,
                )
                response.raise_for_status()
            return True
        except Exception as exc:  # pragma: no cover - network integration
            LOGGER.warning("Failed to fire Home Assistant event %s: %s", event_type, exc)
            return False

    async def _set_state(self, entity_id: str, state: Any, attributes: dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.base_url}/states/{entity_id}",
                    headers=self._headers,
                    json={"state": str(state), "attributes": attributes},
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network integration
            LOGGER.warning("Failed to publish %s to Home Assistant: %s", entity_id, exc)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }


def _number_or_unknown(value: Any) -> Any:
    return round(float(value), 2) if value is not None else "unknown"
