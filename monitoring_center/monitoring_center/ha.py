from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

import httpx

from .config import AppConfig
from .validators import ensure_public_url_if_required

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
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False)
        self.publish_error_count = 0
        self.last_publish_success_at: str | None = None

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def available(self) -> bool:
        return bool(self.token)

    async def list_states(self, timeout: float = 10.0) -> list[dict[str, Any]]:
        if not self.available:
            return []
        response = await self._client.get(f"{self.base_url}/states", headers=self._headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    async def get_api_status(self, timeout: float = 5.0) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "available": False, "error": "SUPERVISOR_TOKEN is not available"}
        try:
            response = await self._client.get(f"{self.base_url}/", headers=self._headers, timeout=timeout)
            response.raise_for_status()
            return {"ok": True, "available": True, "status_code": response.status_code}
        except Exception as exc:  # pragma: no cover - depends on HA runtime
            return {"ok": False, "available": True, "error": str(exc)}

    async def publish_test_state(self, entity_id: str, state: Any, attributes: dict[str, Any]) -> bool:
        if not self.available:
            return False
        try:
            response = await self._client.post(
                f"{self.base_url}/states/{entity_id}",
                headers=self._headers,
                json={"state": str(state), "attributes": attributes},
                timeout=5.0,
            )
            response.raise_for_status()
            return True
        except Exception as exc:  # pragma: no cover - network integration
            LOGGER.warning("Failed to publish self-check entity %s: %s", entity_id, exc)
            return False

    async def publish_monitor_state(self, monitor: dict[str, Any]) -> None:
        if not self.config.publish_home_assistant_entities or not self.available:
            return

        prefix = slugify(self.config.entity_prefix)
        monitor_slug = str(int(monitor["id"]))
        status = monitor.get("status", "unknown")
        is_online = status in {"online", "ok", "open", "warning"}
        attrs = {
            "friendly_name": monitor["name"],
            "monitor_type": monitor["type"],
            "target": monitor["target"],
            "group_id": monitor.get("group_id"),
            "group_name": monitor.get("group_name"),
            "maintenance_active": monitor.get("maintenance_active", False),
            "maintenance_until": monitor.get("maintenance_until") or monitor.get("group_maintenance_until"),
            "last_checked_at": monitor.get("last_checked_at"),
            "last_error": monitor.get("last_error"),
            "response_ms": monitor.get("last_response_ms"),
        }
        details = monitor.get("last_details") or {}

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

        if monitor["type"] in {"http_status", "http_hash", "rest_api"}:
            await self._set_state(
                f"sensor.{prefix}_{monitor_slug}_http_status",
                monitor.get("last_http_status") or "unknown",
                attrs,
            )
        if monitor["type"] == "http_hash":
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
            await self._set_state(
                f"sensor.{prefix}_{monitor_slug}_last_hash",
                monitor.get("last_content_hash") or "unknown",
                attrs,
            )
        if monitor["type"] == "tcp_port":
            await self._set_state(
                f"sensor.{prefix}_{monitor_slug}_tcp_port",
                details.get("port") or monitor.get("config", {}).get("port") or "unknown",
                attrs,
            )
        if monitor["type"] == "ssl_certificate":
            await self._set_state(
                f"sensor.{prefix}_{monitor_slug}_ssl_days_left",
                details.get("days_left", "unknown"),
                attrs,
            )
        if monitor["type"] == "dns_lookup":
            await self._set_state(
                f"sensor.{prefix}_{monitor_slug}_dns_result",
                ", ".join(details.get("records", [])) if details.get("records") else "unknown",
                attrs,
            )

    async def fire_event(self, event_type: str, payload: dict[str, Any]) -> bool:
        if not self.config.publish_home_assistant_events or not self.available:
            return False
        try:
            response = await self._client.post(
                f"{self.base_url}/events/{event_type}", headers=self._headers, json=payload, timeout=5.0
            )
            response.raise_for_status()
            return True
        except Exception as exc:  # pragma: no cover - network integration
            LOGGER.warning("Failed to fire Home Assistant event %s: %s", event_type, exc)
            return False

    async def create_persistent_notification(self, title: str, message: str) -> bool:
        if not self.available:
            return False
        try:
            response = await self._client.post(
                f"{self.base_url}/services/persistent_notification/create",
                headers=self._headers,
                json={"title": title, "message": message},
                timeout=5.0,
            )
            response.raise_for_status()
            return True
        except Exception as exc:  # pragma: no cover - network integration
            LOGGER.warning("Failed to create Home Assistant persistent notification: %s", exc)
            return False

    async def post_webhook(self, url: str, payload: dict[str, Any]) -> bool:
        if not url:
            return False
        try:
            ensure_public_url_if_required(url, not self.config.allow_private_webhooks)
            response = await self._client.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
            return True
        except Exception as exc:  # pragma: no cover - network integration
            LOGGER.warning("Failed to deliver monitoring webhook: %s", exc)
            return False

    async def _set_state(self, entity_id: str, state: Any, attributes: dict[str, Any]) -> None:
        for attempt in range(3):
            try:
                response = await self._client.post(
                    f"{self.base_url}/states/{entity_id}",
                    headers=self._headers,
                    json={"state": str(state), "attributes": attributes},
                    timeout=5.0,
                )
                response.raise_for_status()
                from datetime import UTC, datetime

                self.last_publish_success_at = datetime.now(UTC).isoformat()
                return
            except Exception as exc:  # pragma: no cover - network integration
                self.publish_error_count += 1
                if attempt == 2:
                    LOGGER.warning("Failed to publish %s to Home Assistant: %s", entity_id, exc)
                else:
                    await asyncio.sleep(0.25 * (2**attempt))

    async def delete_monitor_states(self, monitor: dict[str, Any]) -> None:
        if not self.available:
            return
        prefix = slugify(self.config.entity_prefix)
        identifiers = {str(int(monitor["id"])), slugify(f"{monitor['id']}_{monitor['name']}")}
        suffixes = (
            "status",
            "response_time",
            "last_error",
            "http_status",
            "last_change",
            "change_count",
            "last_hash",
            "tcp_port",
            "ssl_days_left",
            "dns_result",
        )
        await asyncio.gather(
            *(
                self._delete_state(f"{domain}.{prefix}_{identifier}_{suffix}")
                for identifier in identifiers
                for suffix in suffixes
                for domain in (("binary_sensor",) if suffix == "status" else ("sensor",))
            )
        )

    async def _delete_state(self, entity_id: str) -> None:
        try:
            response = await self._client.delete(
                f"{self.base_url}/states/{entity_id}", headers=self._headers, timeout=5.0
            )
            if response.status_code not in {200, 404}:
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Failed to remove Home Assistant entity %s: %s", entity_id, exc)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }


def _number_or_unknown(value: Any) -> Any:
    return round(float(value), 2) if value is not None else "unknown"
