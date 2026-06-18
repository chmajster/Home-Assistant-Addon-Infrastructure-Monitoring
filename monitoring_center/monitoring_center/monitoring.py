from __future__ import annotations

import asyncio
import difflib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from .config import AppConfig
from .database import Database, dumps_json, loads_json
from .ha import HomeAssistantClient
from .monitor_types import PRESETS, get_plugin, list_types, resolve_type
from .monitor_types.base import CheckResult, MonitorContext, is_success_status

LOGGER = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class MonitorService:
    def __init__(self, db: Database, config: AppConfig, ha: HomeAssistantClient) -> None:
        self.db = db
        self.config = config
        self.ha = ha
        self.running: set[int] = set()
        self._stop = asyncio.Event()
        self._last_started: dict[int, float] = {}
        self._apply_persisted_settings()

    async def scheduler(self) -> None:
        LOGGER.info("Monitoring scheduler started")
        while not self._stop.is_set():
            try:
                await self._tick()
                await self.cleanup_history()
            except Exception:
                LOGGER.exception("Scheduler tick failed")
            await asyncio.sleep(5)

    def stop(self) -> None:
        self._stop.set()

    async def _tick(self) -> None:
        now = time.monotonic()
        monitors = self.list_monitors(enabled_only=True)
        for monitor in monitors:
            monitor_id = int(monitor["id"])
            interval = int(monitor["interval_seconds"])
            last_started = self._last_started.get(monitor_id, 0)
            if monitor_id in self.running or now - last_started < interval:
                continue
            self._last_started[monitor_id] = now
            asyncio.create_task(self.run_check(monitor_id))

    def list_monitors(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE enabled = 1" if enabled_only else ""
        rows = self.db.fetchall(f"SELECT * FROM monitors {where} ORDER BY name COLLATE NOCASE")
        return [self._hydrate_monitor(row) for row in rows]

    def get_monitor(self, monitor_id: int) -> dict[str, Any]:
        row = self.db.fetchone("SELECT * FROM monitors WHERE id = ?", (monitor_id,))
        if not row:
            raise KeyError(monitor_id)
        return self._hydrate_monitor(row)

    def get_monitor_types(self) -> list[dict[str, Any]]:
        return list_types()

    def get_presets(self) -> list[dict[str, Any]]:
        return PRESETS

    async def create_monitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        monitor = self._normalize_payload(payload)
        cursor = self.db.execute(
            """
            INSERT INTO monitors(type, name, target, interval_seconds, enabled, config_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                monitor["type"],
                monitor["name"],
                monitor["target"],
                monitor["interval_seconds"],
                int(monitor["enabled"]),
                dumps_json(monitor["config"]),
            ),
        )
        created = self.get_monitor(int(cursor.lastrowid))
        if payload.get("test_on_save", True):
            await self.run_check(int(created["id"]))
            created = self.get_monitor(int(created["id"]))
        return created

    async def update_monitor(self, monitor_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_monitor(monitor_id)
        merged = {
            "type": payload.get("type", current["type"]),
            "name": payload.get("name", current["name"]),
            "target": payload.get("target", current["target"]),
            "interval_seconds": payload.get("interval_seconds", current["interval_seconds"]),
            "enabled": payload.get("enabled", current["enabled"]),
            "config": payload.get("config", current["config"]),
        }
        monitor = self._normalize_payload(merged)
        self.db.execute(
            """
            UPDATE monitors
            SET type = ?, name = ?, target = ?, interval_seconds = ?, enabled = ?,
                config_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                monitor["type"],
                monitor["name"],
                monitor["target"],
                monitor["interval_seconds"],
                int(monitor["enabled"]),
                dumps_json(monitor["config"]),
                monitor_id,
            ),
        )
        self._last_started.pop(monitor_id, None)
        if payload.get("test_on_save", False):
            await self.run_check(monitor_id)
        return self.get_monitor(monitor_id)

    def delete_monitor(self, monitor_id: int) -> None:
        self.db.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
        self._last_started.pop(monitor_id, None)

    async def run_check(self, monitor_id: int) -> dict[str, Any]:
        if monitor_id in self.running:
            return self.get_monitor(monitor_id)
        self.running.add(monitor_id)
        try:
            monitor = self.get_monitor(monitor_id)
            previous_status = monitor["status"]
            result = await self._check(monitor)
            now = utc_now()
            changed = previous_status != result.status
            content_changed = result.content_changed
            last_changed_at = now if changed or content_changed else monitor.get("last_changed_at")
            details = result.details or {}

            self.db.execute(
                """
                UPDATE monitors
                SET status = ?, last_response_ms = ?, last_http_status = ?, last_error = ?,
                    last_content_hash = COALESCE(?, last_content_hash),
                    last_checked_at = ?, last_changed_at = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    result.status,
                    result.response_ms,
                    result.http_status,
                    result.error,
                    result.content_hash,
                    now,
                    last_changed_at,
                    monitor_id,
                ),
            )
            self._persist_runtime_details(monitor, details)
            self.db.execute(
                """
                INSERT INTO monitor_checks(
                    monitor_id, checked_at, status, response_ms, http_status, packet_loss,
                    error, previous_status, new_status, content_changed, content_hash, details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    monitor_id,
                    now,
                    result.status,
                    result.response_ms,
                    result.http_status,
                    result.packet_loss,
                    result.error,
                    previous_status,
                    result.status,
                    int(result.content_changed),
                    result.content_hash,
                    dumps_json(
                        {
                            "monitor_id": monitor_id,
                            "monitor_type": monitor["type"],
                            "status": result.status,
                            "response_time_ms": result.response_ms,
                            "checked_at": now,
                            "error_message": result.error,
                            **details,
                        }
                    ),
                ),
            )

            should_store_snapshot = (
                monitor["type"] == "http_hash"
                and bool(result.normalized_content)
                and bool(result.content_hash)
                and (content_changed or not monitor.get("last_content_hash"))
            )
            if should_store_snapshot:
                self._store_snapshot(monitor, result)

            updated = self.get_monitor(monitor_id)
            updated["change_count"] = self._change_count(monitor_id)
            updated["last_details"] = details
            await self.ha.publish_monitor_state(updated)
            if changed:
                await self._record_event("monitor_status_changed", updated, previous_status, result.status, details)
                await self._record_event(
                    "monitor_online" if is_success_status(result.status) else "monitor_offline",
                    updated,
                    previous_status,
                    result.status,
                    details,
                )
            for event_type in result.events:
                await self._record_event(event_type, updated, previous_status, result.status, details)
            if monitor["type"] == "http_hash" and content_changed:
                await self._record_event("website_changed", updated, previous_status, result.status, details)
            if monitor["type"] in {"http_status", "http_hash"} and result.error:
                await self._record_event("website_error", updated, previous_status, result.status, details)
            return updated
        finally:
            self.running.discard(monitor_id)

    async def _check(self, monitor: dict[str, Any]) -> CheckResult:
        try:
            plugin = get_plugin(monitor["type"])
            return await plugin.check(
                monitor,
                MonitorContext(config=self.config, settings=self.get_settings(), ha=self.ha),
            )
        except KeyError:
            return CheckResult("error", error=f"Unsupported monitor type: {monitor['type']}")
        except Exception as exc:
            return CheckResult("error", error=str(exc))

    def _store_snapshot(self, monitor: dict[str, Any], result: CheckResult) -> None:
        previous = self.db.fetchone(
            """
            SELECT normalized_content FROM website_snapshots
            WHERE monitor_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (monitor["id"],),
        )
        previous_text = previous["normalized_content"] if previous else ""
        diff = "\n".join(
            difflib.unified_diff(
                previous_text.splitlines(),
                (result.normalized_content or "").splitlines(),
                fromfile="previous",
                tofile="current",
                lineterm="",
            )
        )
        self.db.execute(
            """
            INSERT INTO website_snapshots(monitor_id, content_hash, normalized_content, raw_excerpt, diff)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                monitor["id"],
                result.content_hash,
                result.normalized_content,
                result.raw_excerpt,
                diff[:20000],
            ),
        )

    async def _record_event(
        self,
        event_type: str,
        monitor: dict[str, Any],
        previous_state: str | None,
        new_state: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "monitor_id": monitor["id"],
            "monitor_name": monitor["name"],
            "monitor_type": monitor["type"],
            "target": monitor["target"],
            "previous_state": previous_state,
            "new_state": new_state,
            "created_at": utc_now(),
            "details": details or {},
        }
        delivered = await self.ha.fire_event(event_type, payload)
        self.db.execute(
            """
            INSERT INTO events(monitor_id, event_type, previous_state, new_state, payload_json, delivered_to_ha)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (monitor["id"], event_type, previous_state, new_state, dumps_json(payload), int(delivered)),
        )

    async def cleanup_history(self) -> None:
        retention = int(self.get_settings().get("retention_days", self.config.retention_days))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention)).replace(microsecond=0).isoformat()
        self.db.execute("DELETE FROM monitor_checks WHERE checked_at < ?", (cutoff,))
        self.db.execute("DELETE FROM events WHERE created_at < ?", (cutoff,))
        self.db.execute("DELETE FROM website_snapshots WHERE created_at < ?", (cutoff,))

    def get_history(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if filters.get("monitor_id"):
            clauses.append("c.monitor_id = ?")
            params.append(filters["monitor_id"])
        if filters.get("type"):
            clauses.append("m.type = ?")
            params.append(filters["type"])
        if filters.get("status"):
            clauses.append("c.status = ?")
            params.append(filters["status"])
        if filters.get("from_date"):
            clauses.append("c.checked_at >= ?")
            params.append(filters["from_date"])
        if filters.get("to_date"):
            clauses.append("c.checked_at <= ?")
            params.append(filters["to_date"])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = min(int(filters.get("limit", 250)), 1000)
        return self.db.fetchall(
            f"""
            SELECT c.*, m.name AS monitor_name, m.type AS monitor_type, m.target
            FROM monitor_checks c
            JOIN monitors m ON m.id = c.monitor_id
            {where}
            ORDER BY c.checked_at DESC, c.id DESC
            LIMIT ?
            """,
            (*params, limit),
        )

    def get_summary(self) -> dict[str, Any]:
        monitors = self.list_monitors()
        checks = self.db.fetchall(
            """
            SELECT c.*, m.name AS monitor_name, m.type AS monitor_type, m.target
            FROM monitor_checks c
            JOIN monitors m ON m.id = c.monitor_id
            ORDER BY c.checked_at DESC, c.id DESC
            LIMIT 30
            """
        )
        avg = self.db.fetchone(
            "SELECT AVG(response_ms) AS avg_response_ms FROM monitor_checks WHERE response_ms IS NOT NULL"
        )
        recent_failures = [row for row in checks if not is_success_status(row["status"])][:8]
        recent_changes = [row for row in checks if row["content_changed"]][:8]
        return {
            "total": len(monitors),
            "online": len([m for m in monitors if is_success_status(m["status"])]),
            "offline": len([m for m in monitors if not is_success_status(m["status"])]),
            "changed_websites": len(recent_changes),
            "avg_response_ms": round(float(avg["avg_response_ms"]), 2) if avg and avg["avg_response_ms"] else None,
            "recent_failures": recent_failures,
            "recent_changes": recent_changes,
            "monitors": monitors,
        }

    def get_snapshots(self, monitor_id: int) -> list[dict[str, Any]]:
        return self.db.fetchall(
            """
            SELECT id, monitor_id, created_at, content_hash, raw_excerpt, diff
            FROM website_snapshots
            WHERE monitor_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 20
            """,
            (monitor_id,),
        )

    def get_events(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall("SELECT * FROM events ORDER BY created_at DESC, id DESC LIMIT 100")
        for row in rows:
            row["payload"] = loads_json(row.pop("payload_json", None), {})
        return rows

    def get_settings(self) -> dict[str, Any]:
        settings = {
            "retention_days": self.config.retention_days,
            "request_timeout_seconds": self.config.request_timeout_seconds,
            "ping_timeout_seconds": self.config.ping_timeout_seconds,
            "max_page_size_kb": self.config.max_page_size_kb,
            "block_private_networks": self.config.block_private_networks,
            "publish_home_assistant_entities": self.config.publish_home_assistant_entities,
            "publish_home_assistant_events": self.config.publish_home_assistant_events,
            "entity_prefix": self.config.entity_prefix,
        }
        for row in self.db.fetchall("SELECT key, value FROM settings"):
            settings[row["key"]] = loads_json(row["value"], row["value"])
        return settings

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        for key, value in payload.items():
            self.db.execute(
                """
                INSERT INTO settings(key, value, updated_at) VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
                """,
                (key, dumps_json(value)),
            )
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        return self.get_settings()

    def _apply_persisted_settings(self) -> None:
        for key, value in self.get_settings().items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    def _persist_runtime_details(self, monitor: dict[str, Any], details: dict[str, Any]) -> None:
        config = dict(monitor.get("config") or {})
        changed = False
        if "records" in details:
            config["last_dns_result"] = details["records"]
            changed = True
        if "state" in details:
            config["last_ha_state"] = details["state"]
            changed = True
        if changed:
            self.db.execute(
                "UPDATE monitors SET config_json = ?, updated_at = datetime('now') WHERE id = ?",
                (dumps_json(config), monitor["id"]),
            )

    def _change_count(self, monitor_id: int) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) AS count FROM monitor_checks WHERE monitor_id = ? AND content_changed = 1",
            (monitor_id,),
        )
        return int(row["count"] if row else 0)

    def diagnostics(self) -> dict[str, Any]:
        last_check = self.db.fetchone("SELECT MAX(checked_at) AS checked_at FROM monitor_checks")
        errors = self.db.fetchall(
            """
            SELECT checked_at, monitor_id, error
            FROM monitor_checks
            WHERE error IS NOT NULL AND error != ''
            ORDER BY checked_at DESC
            LIMIT 20
            """
        )
        return {
            "version": "0.2.0",
            "database_path": str(self.config.database_path),
            "database_exists": self.config.database_path.exists(),
            "database_size_bytes": self.config.database_path.stat().st_size if self.config.database_path.exists() else 0,
            "monitor_count": self.db.fetchone("SELECT COUNT(*) AS count FROM monitors")["count"],
            "last_check": last_check["checked_at"] if last_check else None,
            "running_jobs": sorted(self.running),
            "intervals": {m["id"]: m["interval_seconds"] for m in self.list_monitors()},
            "errors": errors,
            "log_file": str(self.config.log_file),
            "settings": self.get_settings(),
        }

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        monitor_type = resolve_type(payload["type"])
        config = payload.get("config") or {}
        try:
            plugin = get_plugin(monitor_type)
            target, config = plugin.validate(payload["target"], config, self.config)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "type": monitor_type,
            "name": payload["name"].strip(),
            "target": target,
            "interval_seconds": int(payload.get("interval_seconds") or plugin.default_interval),
            "enabled": bool(payload.get("enabled", True)),
            "config": config,
        }

    @staticmethod
    def _hydrate_monitor(row: dict[str, Any]) -> dict[str, Any]:
        row["enabled"] = bool(row["enabled"])
        row["type"] = resolve_type(row["type"])
        row["config"] = loads_json(row.pop("config_json", None), {})
        return row
