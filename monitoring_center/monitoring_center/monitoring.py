from __future__ import annotations

import asyncio
import difflib
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from . import __version__
from .config import AppConfig
from .database import Database, dumps_json, loads_json
from .ha import HomeAssistantClient
from .monitor_types import PRESETS, get_plugin, list_types, resolve_type
from .monitor_types.base import CheckResult, MonitorContext, is_success_status
from .validators import normalize_url_key

LOGGER = logging.getLogger(__name__)
URL_MONITOR_TYPES = {"http_status", "http_hash", "rest_api"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class MonitorService:
    def __init__(self, db: Database, config: AppConfig, ha: HomeAssistantClient) -> None:
        self.db = db
        self.config = config
        self.ha = ha
        self._apply_persisted_settings()
        self.running: set[int] = set()
        self.active_checks: set[int] = set()
        self.queued_checks: set[int] = set()
        self._check_semaphore = asyncio.Semaphore(max(int(self.config.max_concurrent_checks), 1))
        self._stop = asyncio.Event()
        self._last_started: dict[int, float] = {}
        self._last_tick_at: str | None = None
        self._scheduler_error_count = 0
        self._last_scheduler_error: str | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self.started_at = utc_now()

    async def scheduler(self) -> None:
        LOGGER.info("Monitoring scheduler started")
        while not self._stop.is_set():
            try:
                await self._tick()
                await self.cleanup_history()
            except Exception as exc:
                self._scheduler_error_count += 1
                self._last_scheduler_error = str(exc)
                LOGGER.exception("Scheduler tick failed")
            await asyncio.sleep(5)

    def stop(self) -> None:
        self._stop.set()
        for task in list(self._tasks):
            task.cancel()

    async def _tick(self) -> None:
        self._last_tick_at = utc_now()
        now = time.monotonic()
        monitors = self.list_monitors(enabled_only=True)
        for monitor in monitors:
            monitor_id = int(monitor["id"])
            interval = int(monitor["interval_seconds"])
            last_started = self._last_started.get(monitor_id, 0)
            if monitor_id in self.running or now - last_started < interval:
                continue
            self._last_started[monitor_id] = now
            self._schedule_check_task(monitor_id)

    def _schedule_check_task(self, monitor_id: int) -> None:
        task = asyncio.create_task(self.run_check(monitor_id), name=f"monitor-check-{monitor_id}")
        self._tasks.add(task)
        task.add_done_callback(self._on_check_task_done)

    def _on_check_task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            LOGGER.debug("Scheduled monitor check task cancelled")
        except Exception as exc:
            self._scheduler_error_count += 1
            self._last_scheduler_error = str(exc)
            LOGGER.exception("Scheduled monitor check task failed")

    def list_monitors(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE m.enabled = 1" if enabled_only else ""
        rows = self.db.fetchall(
            f"""
            SELECT m.*, g.name AS group_name, g.maintenance_until AS group_maintenance_until,
                   g.maintenance_reason AS group_maintenance_reason
            FROM monitors m
            LEFT JOIN monitor_groups g ON g.id = m.group_id
            {where}
            ORDER BY m.name COLLATE NOCASE
            """
        )
        return [self._hydrate_monitor(row) for row in rows]

    def get_monitor(self, monitor_id: int) -> dict[str, Any]:
        row = self.db.fetchone(
            """
            SELECT m.*, g.name AS group_name, g.maintenance_until AS group_maintenance_until,
                   g.maintenance_reason AS group_maintenance_reason
            FROM monitors m
            LEFT JOIN monitor_groups g ON g.id = m.group_id
            WHERE m.id = ?
            """,
            (monitor_id,),
        )
        if not row:
            raise KeyError(monitor_id)
        return self._hydrate_monitor(row)

    def list_groups(self) -> list[dict[str, Any]]:
        groups = self.db.fetchall("SELECT * FROM monitor_groups ORDER BY name COLLATE NOCASE")
        monitors = self.list_monitors()
        return [self._hydrate_group(group, monitors) for group in groups]

    def create_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.db.fetchone(
            "SELECT * FROM monitor_groups WHERE name = ?",
            (payload["name"].strip(),),
        )
        if existing:
            return self._hydrate_group(existing, self.list_monitors())
        cursor = self.db.execute(
            "INSERT INTO monitor_groups(name, description, color) VALUES (?, ?, ?)",
            (payload["name"].strip(), payload.get("description"), payload.get("color") or "#0f766e"),
        )
        return self.get_group(int(cursor.lastrowid))

    def get_group(self, group_id: int) -> dict[str, Any]:
        row = self.db.fetchone("SELECT * FROM monitor_groups WHERE id = ?", (group_id,))
        if not row:
            raise KeyError(group_id)
        return self._hydrate_group(row, self.list_monitors())

    def update_group(self, group_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_group(group_id)
        self.db.execute(
            """
            UPDATE monitor_groups
            SET name = ?, description = ?, color = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                payload.get("name", current["name"]).strip(),
                payload.get("description", current.get("description")),
                payload.get("color", current.get("color") or "#0f766e"),
                group_id,
            ),
        )
        return self.get_group(group_id)

    def delete_group(self, group_id: int) -> None:
        self.db.execute("UPDATE monitors SET group_id = NULL WHERE group_id = ?", (group_id,))
        self.db.execute("DELETE FROM monitor_groups WHERE id = ?", (group_id,))

    def get_monitor_types(self) -> list[dict[str, Any]]:
        return list_types()

    def get_presets(self) -> list[dict[str, Any]]:
        return PRESETS

    async def create_monitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        monitor = self._normalize_payload(payload)
        self._ensure_unique_url_monitor(monitor)
        monitor_id = self._insert_monitor(monitor)
        created = self.get_monitor(monitor_id)
        self._record_local_event("monitor_created", created, None, created["status"], {"config": created["config"]})
        if payload.get("test_on_save", True):
            await self.run_check(int(created["id"]))
            created = self.get_monitor(int(created["id"]))
        return created

    async def create_monitors_bulk(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        created_ids: list[int] = []
        with self.db.transaction():
            for payload in payloads:
                monitor = self._normalize_payload({**payload, "test_on_save": False})
                self._ensure_unique_url_monitor(monitor)
                created_ids.append(self._insert_monitor(monitor))
        return [self.get_monitor(monitor_id) for monitor_id in created_ids]

    async def update_monitor(self, monitor_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_monitor(monitor_id)
        merged = {
            "type": payload.get("type", current["type"]),
            "name": payload.get("name", current["name"]),
            "target": payload.get("target", current["target"]),
            "interval_seconds": payload.get("interval_seconds", current["interval_seconds"]),
            "group_id": payload.get("group_id", current.get("group_id")),
            "enabled": payload.get("enabled", current["enabled"]),
            "config": payload.get("config", current["config"]),
        }
        monitor = self._normalize_payload(merged)
        self._ensure_unique_url_monitor(monitor, exclude_id=monitor_id)
        self.db.execute(
            """
            UPDATE monitors
            SET type = ?, name = ?, target = ?, interval_seconds = ?, group_id = ?, enabled = ?,
                config_json = ?, failure_count = 0, recovery_count = 0, last_raw_status = NULL,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                monitor["type"],
                monitor["name"],
                monitor["target"],
                monitor["interval_seconds"],
                monitor["group_id"],
                int(monitor["enabled"]),
                dumps_json(monitor["config"]),
                monitor_id,
            ),
        )
        self._last_started.pop(monitor_id, None)
        if payload.get("test_on_save", False):
            await self.run_check(monitor_id)
        updated = self.get_monitor(monitor_id)
        self._record_local_event(
            "monitor_updated",
            updated,
            current["status"],
            updated["status"],
            {"previous_config": current["config"], "config": updated["config"]},
        )
        if bool(current["enabled"]) != bool(updated["enabled"]):
            self._record_local_event(
                "monitor_enabled" if updated["enabled"] else "monitor_disabled",
                updated,
                "enabled" if current["enabled"] else "disabled",
                "enabled" if updated["enabled"] else "disabled",
            )
        return updated

    async def test_monitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        monitor = self._normalize_payload(payload)
        test_monitor = {
            "id": None,
            "status": "unknown",
            "last_content_hash": None,
            "last_changed_at": None,
            **monitor,
        }
        result = await self._check(test_monitor)
        return {
            "status": result.status,
            "success": is_success_status(result.status),
            "checked_at": utc_now(),
            "response_ms": result.response_ms,
            "http_status": result.http_status,
            "content_hash": result.content_hash,
            "error": result.error,
            "details": result.details or {},
        }

    def delete_monitor(self, monitor_id: int) -> None:
        self.get_monitor(monitor_id)
        self.db.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
        self._last_started.pop(monitor_id, None)

    def set_monitor_enabled(self, monitor_id: int, enabled: bool) -> dict[str, Any]:
        current = self.get_monitor(monitor_id)
        self.db.execute(
            "UPDATE monitors SET enabled = ?, updated_at = datetime('now') WHERE id = ?",
            (int(enabled), monitor_id),
        )
        if not enabled:
            self._last_started.pop(monitor_id, None)
        updated = self.get_monitor(monitor_id)
        if bool(current["enabled"]) != bool(updated["enabled"]):
            self._record_local_event(
                "monitor_enabled" if updated["enabled"] else "monitor_disabled",
                updated,
                "enabled" if current["enabled"] else "disabled",
                "enabled" if updated["enabled"] else "disabled",
            )
        return updated

    async def run_check(self, monitor_id: int) -> dict[str, Any]:
        if monitor_id in self.running:
            return self.get_monitor(monitor_id)
        self.running.add(monitor_id)
        self.queued_checks.add(monitor_id)
        try:
            async with self._check_semaphore:
                self.queued_checks.discard(monitor_id)
                self.active_checks.add(monitor_id)
                try:
                    return await self._run_check_now(monitor_id)
                finally:
                    self.active_checks.discard(monitor_id)
        finally:
            self.queued_checks.discard(monitor_id)
            self.running.discard(monitor_id)

    async def _run_check_now(self, monitor_id: int) -> dict[str, Any]:
        monitor = self.get_monitor(monitor_id)
        previous_status = monitor["status"]
        result = await self._check(monitor)
        final_status, failure_count, recovery_count, threshold_pending = self._status_after_thresholds(
            monitor,
            result.status,
        )
        now = utc_now()
        changed = previous_status != final_status
        content_changed = result.content_changed
        last_changed_at = now if changed or content_changed else monitor.get("last_changed_at")
        details = {
            **(result.details or {}),
            "raw_status": result.status,
            "effective_status": final_status,
            "failure_count": failure_count,
            "recovery_count": recovery_count,
            "failure_threshold": self._monitor_int_setting(
                monitor,
                "failure_threshold",
                self.config.failure_threshold,
                1,
            ),
            "recovery_threshold": self._monitor_int_setting(
                monitor,
                "recovery_threshold",
                self.config.recovery_threshold,
                1,
            ),
        }

        self.db.execute(
            """
            UPDATE monitors
            SET status = ?, last_response_ms = ?, last_http_status = ?, last_error = ?,
                last_content_hash = COALESCE(?, last_content_hash),
                last_checked_at = ?, last_changed_at = ?, failure_count = ?, recovery_count = ?,
                last_raw_status = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                final_status,
                result.response_ms,
                result.http_status,
                result.error,
                result.content_hash,
                now,
                last_changed_at,
                failure_count,
                recovery_count,
                result.status,
                monitor_id,
            ),
        )
        self._persist_runtime_details(monitor, details)
        if details.get("stop_checks"):
            self.db.execute(
                "UPDATE monitors SET enabled = 0, updated_at = datetime('now') WHERE id = ?",
                (monitor_id,),
            )
            self._last_started.pop(monitor_id, None)
        elif threshold_pending:
            self._schedule_retry(monitor, details)
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
                final_status,
                result.response_ms,
                result.http_status,
                result.packet_loss,
                result.error,
                previous_status,
                final_status,
                int(result.content_changed),
                result.content_hash,
                dumps_json(
                    {
                        "monitor_id": monitor_id,
                        "monitor_type": monitor["type"],
                        "status": final_status,
                        "response_time_ms": result.response_ms,
                        "checked_at": now,
                        "error_message": result.error,
                        **details,
                    }
                ),
            ),
        )
        self._sync_incident(monitor_id, previous_status, final_status, result.status, result.error, now)

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
        if not self._is_maintenance_active(updated):
            if changed:
                await self._record_event("monitor_status_changed", updated, previous_status, final_status, details)
                await self._record_event(
                    "monitor_online" if is_success_status(final_status) else "monitor_offline",
                    updated,
                    previous_status,
                    final_status,
                    details,
                )
            for event_type in result.events:
                await self._record_event(event_type, updated, previous_status, final_status, details)
            if monitor["type"] == "http_hash" and content_changed:
                await self._record_event("website_changed", updated, previous_status, final_status, details)
            if monitor["type"] in {"http_status", "http_hash"} and result.error:
                await self._record_event("website_error", updated, previous_status, final_status, details)
        return updated

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

    def _status_after_thresholds(self, monitor: dict[str, Any], raw_status: str) -> tuple[str, int, int, bool]:
        previous_status = str(monitor.get("status") or "unknown")
        previous_success = is_success_status(previous_status)
        raw_success = is_success_status(raw_status)
        failure_threshold = self._monitor_int_setting(monitor, "failure_threshold", self.config.failure_threshold, 1)
        recovery_threshold = self._monitor_int_setting(monitor, "recovery_threshold", self.config.recovery_threshold, 1)
        failure_count = int(monitor.get("failure_count") or 0)
        recovery_count = int(monitor.get("recovery_count") or 0)

        if raw_success:
            failure_count = 0
            if previous_success or previous_status == "unknown":
                return raw_status, failure_count, 0, False
            recovery_count += 1
            if recovery_count >= recovery_threshold:
                return raw_status, failure_count, 0, False
            return previous_status, failure_count, recovery_count, True

        recovery_count = 0
        if previous_success or previous_status == "unknown":
            failure_count += 1
            if failure_count >= failure_threshold:
                return raw_status, 0, recovery_count, False
            return previous_status, failure_count, recovery_count, True
        return raw_status, 0, recovery_count, False

    def _schedule_retry(self, monitor: dict[str, Any], details: dict[str, Any]) -> None:
        retry_delay = self._monitor_int_setting(monitor, "retry_delay_seconds", self.config.retry_delay_seconds, 0)
        if retry_delay <= 0:
            return
        interval = max(int(monitor.get("interval_seconds") or retry_delay), 1)
        self._last_started[int(monitor["id"])] = time.monotonic() - max(interval - retry_delay, 0)
        details["retry_delay_seconds"] = retry_delay

    def _monitor_int_setting(self, monitor: dict[str, Any], key: str, default: int, minimum: int) -> int:
        config = monitor.get("config") or {}
        return _safe_int(config.get(key), default, minimum)

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

    def _record_local_event(
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
        self.db.execute(
            """
            INSERT INTO events(monitor_id, event_type, previous_state, new_state, payload_json, delivered_to_ha)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (monitor["id"], event_type, previous_state, new_state, dumps_json(payload)),
        )

    def _sync_incident(
        self,
        monitor_id: int,
        previous_status: str | None,
        current_status: str,
        root_status: str,
        last_error: str | None,
        checked_at: str,
    ) -> None:
        previous_failed = self._is_incident_status(previous_status)
        current_failed = self._is_incident_status(current_status)
        if current_failed:
            open_incident = self.db.fetchone(
                """
                SELECT * FROM incidents
                WHERE monitor_id = ? AND status = 'open' AND ended_at IS NULL
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """,
                (monitor_id,),
            )
            if open_incident:
                duration = self._incident_duration_seconds(open_incident["started_at"], checked_at)
                self.db.execute(
                    """
                    UPDATE incidents
                    SET root_status = ?, last_error = ?, check_count = check_count + 1,
                        duration_seconds = ?
                    WHERE id = ?
                    """,
                    (root_status, last_error, duration, open_incident["id"]),
                )
                return
            self.db.execute(
                """
                INSERT INTO incidents(
                    monitor_id, started_at, status, root_status, last_error, check_count, duration_seconds
                )
                VALUES (?, ?, 'open', ?, ?, 1, 0)
                """,
                (monitor_id, checked_at, root_status, last_error),
            )
            return

        if previous_failed:
            open_incident = self.db.fetchone(
                """
                SELECT * FROM incidents
                WHERE monitor_id = ? AND status = 'open' AND ended_at IS NULL
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """,
                (monitor_id,),
            )
            if not open_incident:
                return
            duration = self._incident_duration_seconds(open_incident["started_at"], checked_at)
            self.db.execute(
                """
                UPDATE incidents
                SET ended_at = ?, status = 'closed', last_error = ?,
                    check_count = check_count + 1, duration_seconds = ?
                WHERE id = ?
                """,
                (checked_at, last_error, duration, open_incident["id"]),
            )

    @staticmethod
    def _is_incident_status(status: str | None) -> bool:
        return bool(status) and status != "unknown" and not is_success_status(str(status))

    @staticmethod
    def _incident_duration_seconds(started_at: str | None, ended_at: str | None = None) -> int:
        started = parse_time(started_at)
        ended = parse_time(ended_at) or datetime.now(timezone.utc)
        if not started:
            return 0
        return max(0, int((ended - started).total_seconds()))

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
            LIMIT 200
            """
        )
        avg = self.db.fetchone(
            "SELECT AVG(response_ms) AS avg_response_ms FROM monitor_checks WHERE response_ms IS NOT NULL"
        )
        recent_failures = [row for row in checks if not is_success_status(row["status"])][:12]
        recent_changes = [row for row in checks if row["content_changed"]][:40]
        return {
            "total": len(monitors),
            "online": len([m for m in monitors if is_success_status(m["status"])]),
            "offline": len([m for m in monitors if not is_success_status(m["status"])]),
            "changed_websites": len(recent_changes),
            "avg_response_ms": round(float(avg["avg_response_ms"]), 2) if avg and avg["avg_response_ms"] else None,
            "recent_failures": recent_failures,
            "recent_changes": recent_changes,
            "monitors": monitors,
            "groups": self.list_groups(),
            "slo": self.get_slo_stats(),
        }

    def get_slo_stats(self, group_id: int | None = None, monitor_id: int | None = None) -> dict[str, Any]:
        windows = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}
        return {
            label: self._slo_for_window(days, group_id=group_id, monitor_id=monitor_id)
            for label, days in windows.items()
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

    def list_incidents(
        self,
        limit: int = 100,
        active_only: bool = False,
        monitor_id: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if active_only:
            clauses.append("i.status = 'open' AND i.ended_at IS NULL")
        if monitor_id is not None:
            clauses.append("i.monitor_id = ?")
            params.append(monitor_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.fetchall(
            f"""
            SELECT i.*, m.name AS monitor_name, m.type AS monitor_type, m.target
            FROM incidents i
            JOIN monitors m ON m.id = i.monitor_id
            {where}
            ORDER BY COALESCE(i.ended_at, i.started_at) DESC, i.id DESC
            LIMIT ?
            """,
            (*params, min(max(int(limit), 1), 500)),
        )
        for row in rows:
            if row["status"] == "open" and not row.get("ended_at"):
                row["duration_seconds"] = self._incident_duration_seconds(row["started_at"])
        return rows

    def get_monitor_timeline(self, monitor_id: int, limit: int = 120) -> list[dict[str, Any]]:
        monitor = self.get_monitor(monitor_id)
        items: list[dict[str, Any]] = [
            {
                "timestamp": monitor.get("created_at"),
                "type": "monitor_created",
                "title": "Utworzono monitor",
                "description": monitor["target"],
                "status": monitor["status"],
                "payload": {"monitor_type": monitor["type"]},
            }
        ]
        events = self.db.fetchall(
            """
            SELECT *
            FROM events
            WHERE monitor_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (monitor_id, min(max(int(limit), 1), 500)),
        )
        for event in events:
            payload = loads_json(event.pop("payload_json", None), {})
            items.append(
                {
                    "timestamp": event["created_at"],
                    "type": event["event_type"],
                    "title": self._timeline_title(event["event_type"]),
                    "description": self._timeline_description(event, payload),
                    "previous_state": event.get("previous_state"),
                    "new_state": event.get("new_state"),
                    "payload": payload,
                }
            )

        checks = self.db.fetchall(
            """
            SELECT *
            FROM monitor_checks
            WHERE monitor_id = ?
              AND (
                COALESCE(previous_status, '') != COALESCE(new_status, '')
                OR content_changed = 1
                OR error IS NOT NULL
              )
            ORDER BY checked_at DESC, id DESC
            LIMIT ?
            """,
            (monitor_id, min(max(int(limit), 1), 500)),
        )
        for check in checks:
            details = loads_json(check.get("details_json"), {})
            if check.get("content_changed"):
                items.append(
                    {
                        "timestamp": check["checked_at"],
                        "type": "website_hash_changed",
                        "title": "Zmiana hasha WWW",
                        "description": check.get("content_hash"),
                        "status": check["status"],
                        "payload": details,
                    }
                )
            if check.get("previous_status") != check.get("new_status"):
                items.append(
                    {
                        "timestamp": check["checked_at"],
                        "type": "status_transition",
                        "title": "Zmiana statusu",
                        "description": f"{check.get('previous_status') or '-'} -> {check.get('new_status') or '-'}",
                        "previous_state": check.get("previous_status"),
                        "new_state": check.get("new_status"),
                        "status": check["status"],
                        "payload": details,
                    }
                )
            error_text = str(check.get("error") or "")
            if details.get("stop_checks") or "page size" in error_text.lower() or "limit" in error_text.lower():
                items.append(
                    {
                        "timestamp": check["checked_at"],
                        "type": "page_limit_exceeded",
                        "title": "Przekroczono limit strony",
                        "description": error_text or details.get("error_message") or "",
                        "status": check["status"],
                        "payload": details,
                    }
                )

        for incident in self.list_incidents(limit=limit, monitor_id=monitor_id):
            items.append(
                {
                    "timestamp": incident["started_at"],
                    "type": "incident_started",
                    "title": "Start incydentu",
                    "description": incident.get("last_error") or incident.get("root_status"),
                    "status": incident["root_status"],
                    "payload": incident,
                }
            )
            if incident.get("ended_at"):
                items.append(
                    {
                        "timestamp": incident["ended_at"],
                        "type": "incident_ended",
                        "title": "Koniec incydentu",
                        "description": f"Czas trwania: {incident.get('duration_seconds', 0)} s",
                        "status": "ok",
                        "payload": incident,
                    }
                )

        items = [item for item in items if item.get("timestamp")]
        return sorted(items, key=lambda item: str(item["timestamp"]), reverse=True)[: min(max(int(limit), 1), 500)]

    @staticmethod
    def _timeline_title(event_type: str) -> str:
        return {
            "monitor_created": "Utworzono monitor",
            "monitor_updated": "Zmieniono konfiguracje",
            "monitor_enabled": "Wlaczono monitor",
            "monitor_disabled": "Wylaczono monitor",
            "maintenance_started": "Start maintenance",
            "maintenance_ended": "Koniec maintenance",
            "monitor_status_changed": "Zmiana statusu",
            "monitor_online": "Powrot do OK",
            "monitor_offline": "Awaria monitora",
            "website_changed": "Zmiana WWW",
            "website_error": "Blad WWW",
            "website_hash_changed": "Zmiana hasha WWW",
        }.get(event_type, event_type)

    @staticmethod
    def _timeline_description(event: dict[str, Any], payload: dict[str, Any]) -> str:
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        return (
            details.get("error_message")
            or details.get("change_summary")
            or event.get("new_state")
            or payload.get("target")
            or ""
        )

    def get_settings(self) -> dict[str, Any]:
        settings = {
            "retention_days": self.config.retention_days,
            "default_interval_seconds": self.config.default_interval_seconds,
            "default_timeout_minutes": self.config.default_timeout_minutes,
            "max_concurrent_checks": self.config.max_concurrent_checks,
            "failure_threshold": self.config.failure_threshold,
            "recovery_threshold": self.config.recovery_threshold,
            "retry_delay_seconds": self.config.retry_delay_seconds,
            "max_page_size_mb": self.config.max_page_size_mb,
            "block_private_networks": self.config.block_private_networks,
            "publish_home_assistant_entities": self.config.publish_home_assistant_entities,
            "publish_home_assistant_events": self.config.publish_home_assistant_events,
            "entity_prefix": self.config.entity_prefix,
        }
        persisted_keys: set[str] = set()
        for row in self.db.fetchall("SELECT key, value FROM settings"):
            persisted_keys.add(row["key"])
            settings[row["key"]] = loads_json(row["value"], row["value"])
        if "default_timeout_minutes" not in persisted_keys:
            timeout_seconds = settings.get("request_timeout_seconds", settings.get("ping_timeout_seconds", 300))
            settings["default_timeout_minutes"] = max(_safe_float(timeout_seconds, 300) / 60, 1 / 60)
        if "default_interval_seconds" not in persisted_keys:
            legacy_interval = settings.get("default_website_interval", settings.get("default_device_interval", 300))
            settings["default_interval_seconds"] = int(max(_safe_float(legacy_interval, 300), 5))
        if "max_page_size_mb" not in persisted_keys:
            settings["max_page_size_mb"] = max(_safe_float(settings.get("max_page_size_kb", 512), 512) / 1024, 1 / 1024)
        settings.pop("request_timeout_seconds", None)
        settings.pop("ping_timeout_seconds", None)
        settings.pop("default_device_interval", None)
        settings.pop("default_website_interval", None)
        settings.pop("max_page_size_kb", None)
        return settings

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_settings_payload(payload)
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
        self._check_semaphore = asyncio.Semaphore(max(int(self.config.max_concurrent_checks), 1))
        return self.get_settings()

    def set_monitor_maintenance(self, monitor_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_monitor(monitor_id)
        until = self._maintenance_until(payload)
        self.db.execute(
            """
            UPDATE monitors
            SET maintenance_until = ?, maintenance_reason = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (until, payload.get("reason"), monitor_id),
        )
        updated = self.get_monitor(monitor_id)
        self._record_local_event(
            "maintenance_started",
            updated,
            current.get("maintenance_until"),
            until,
            {"reason": payload.get("reason")},
        )
        return updated

    def clear_monitor_maintenance(self, monitor_id: int) -> dict[str, Any]:
        current = self.get_monitor(monitor_id)
        self.db.execute(
            """
            UPDATE monitors
            SET maintenance_until = NULL, maintenance_reason = NULL, updated_at = datetime('now')
            WHERE id = ?
            """,
            (monitor_id,),
        )
        updated = self.get_monitor(monitor_id)
        self._record_local_event(
            "maintenance_ended",
            updated,
            current.get("maintenance_until"),
            None,
            {"reason": current.get("maintenance_reason")},
        )
        return updated

    def set_group_maintenance(self, group_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        until = self._maintenance_until(payload)
        self.db.execute(
            """
            UPDATE monitor_groups
            SET maintenance_until = ?, maintenance_reason = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (until, payload.get("reason"), group_id),
        )
        return self.get_group(group_id)

    def clear_group_maintenance(self, group_id: int) -> dict[str, Any]:
        self.db.execute(
            """
            UPDATE monitor_groups
            SET maintenance_until = NULL, maintenance_reason = NULL, updated_at = datetime('now')
            WHERE id = ?
            """,
            (group_id,),
        )
        return self.get_group(group_id)

    def _apply_persisted_settings(self) -> None:
        for key, value in self.get_settings().items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    @staticmethod
    def _normalize_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        if "default_timeout_minutes" not in normalized:
            timeout_seconds = normalized.pop("request_timeout_seconds", normalized.pop("ping_timeout_seconds", None))
            if timeout_seconds is not None:
                normalized["default_timeout_minutes"] = max(_safe_float(timeout_seconds, 300) / 60, 1 / 60)
        normalized.pop("request_timeout_seconds", None)
        normalized.pop("ping_timeout_seconds", None)
        if "default_interval_seconds" not in normalized:
            legacy_interval = normalized.pop("default_website_interval", normalized.pop("default_device_interval", 300))
            normalized["default_interval_seconds"] = int(max(_safe_float(legacy_interval, 300), 5))
        normalized.pop("default_device_interval", None)
        normalized.pop("default_website_interval", None)

        if "max_page_size_mb" not in normalized:
            max_page_size_kb = normalized.pop("max_page_size_kb", None)
            if max_page_size_kb is not None:
                normalized["max_page_size_mb"] = max(_safe_float(max_page_size_kb, 512) / 1024, 1 / 1024)
        normalized.pop("max_page_size_kb", None)
        return normalized

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
        schema = self.db.fetchone("SELECT MAX(version) AS version FROM schema_migrations")
        db_stats = self.db.diagnostics()
        started = parse_time(self.started_at)
        last_tick = parse_time(self._last_tick_at)
        now = datetime.now(timezone.utc)
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
            "version": __version__,
            "python_version": sys.version.split()[0],
            "started_at": self.started_at,
            "database_path": str(self.config.database_path),
            "database_exists": self.config.database_path.exists(),
            "schema_version": int(schema["version"] or 0) if schema else 0,
            **db_stats,
            "last_check": last_check["checked_at"] if last_check else None,
            "scheduler_running": not self._stop.is_set(),
            "scheduler_uptime_seconds": max(0, int((now - started).total_seconds())) if started else 0,
            "scheduler_last_tick": self._last_tick_at,
            "scheduler_last_tick_age_seconds": max(0, int((now - last_tick).total_seconds())) if last_tick else None,
            "scheduler_error_count": self._scheduler_error_count,
            "scheduler_last_error": self._last_scheduler_error,
            "max_concurrent_checks": self.config.max_concurrent_checks,
            "active_jobs": sorted(self.active_checks),
            "active_job_count": len(self.active_checks),
            "queued_jobs": sorted(self.queued_checks),
            "queued_job_count": len(self.queued_checks),
            "running_jobs": sorted(self.running),
            "scheduled_task_count": len(self._tasks),
            "scheduled_tasks": [task.get_name() for task in self._tasks if not task.done()],
            "intervals": {m["id"]: m["interval_seconds"] for m in self.list_monitors()},
            "errors": errors,
            "log_file": str(self.config.log_file),
            "settings": self.get_settings(),
            "slo": self.get_slo_stats(),
        }

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        monitor_type = resolve_type(payload["type"])
        config = self._normalize_monitor_config(payload.get("config") or {})
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
            "interval_seconds": int(payload.get("interval_seconds") or self.get_settings()["default_interval_seconds"]),
            "group_id": payload.get("group_id"),
            "enabled": bool(payload.get("enabled", True)),
            "config": config,
        }

    def _insert_monitor(self, monitor: dict[str, Any]) -> int:
        cursor = self.db.execute(
            """
            INSERT INTO monitors(type, name, target, interval_seconds, group_id, enabled, config_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                monitor["type"],
                monitor["name"],
                monitor["target"],
                monitor["interval_seconds"],
                monitor["group_id"],
                int(monitor["enabled"]),
                dumps_json(monitor["config"]),
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _normalize_monitor_config(config: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(config)
        if "timeout_minutes" not in normalized and "timeout_seconds" in normalized:
            try:
                normalized["timeout_minutes"] = _safe_float(normalized.pop("timeout_seconds"), 300) / 60
            except (TypeError, ValueError):
                normalized.pop("timeout_seconds", None)
        if "max_page_size_mb" not in normalized and "max_page_size_kb" in normalized:
            try:
                normalized["max_page_size_mb"] = _safe_float(normalized.pop("max_page_size_kb"), 512) / 1024
            except (TypeError, ValueError):
                normalized.pop("max_page_size_kb", None)
        return normalized

    def _ensure_unique_url_monitor(self, monitor: dict[str, Any], exclude_id: int | None = None) -> None:
        if monitor["type"] not in URL_MONITOR_TYPES:
            return
        target_key = normalize_url_key(monitor["target"])
        for existing in self.list_monitors():
            if exclude_id is not None and existing["id"] == exclude_id:
                continue
            if existing["type"] not in URL_MONITOR_TYPES:
                continue
            try:
                existing_key = normalize_url_key(existing["target"])
            except HTTPException:
                continue
            if existing_key == target_key:
                raise HTTPException(
                    status_code=409,
                    detail=f"Monitor URL already exists: {existing['name']}",
                )

    @staticmethod
    def _hydrate_monitor(row: dict[str, Any]) -> dict[str, Any]:
        row["enabled"] = bool(row["enabled"])
        row["failure_count"] = int(row.get("failure_count") or 0)
        row["recovery_count"] = int(row.get("recovery_count") or 0)
        row["type"] = resolve_type(row["type"])
        row["config"] = loads_json(row.pop("config_json", None), {})
        row["maintenance_active"] = _is_future(row.get("maintenance_until")) or _is_future(
            row.get("group_maintenance_until")
        )
        return row

    def _hydrate_group(self, row: dict[str, Any], monitors: list[dict[str, Any]]) -> dict[str, Any]:
        group_monitors = [monitor for monitor in monitors if monitor.get("group_id") == row["id"]]
        active = _is_future(row.get("maintenance_until"))
        statuses = [monitor["status"] for monitor in group_monitors]
        if not group_monitors:
            status = "empty"
        elif all(is_success_status(status) for status in statuses):
            status = "ok"
        elif any(is_success_status(status) for status in statuses):
            status = "warning"
        else:
            status = "error"
        row["maintenance_active"] = active
        row["monitor_count"] = len(group_monitors)
        row["online"] = len([monitor for monitor in group_monitors if is_success_status(monitor["status"])])
        row["offline"] = len(group_monitors) - row["online"]
        row["status"] = status
        row["slo"] = self.get_slo_stats(group_id=row["id"])
        return row

    def _slo_for_window(self, days: int, group_id: int | None = None, monitor_id: int | None = None) -> dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
        clauses = ["c.checked_at >= ?"]
        params: list[Any] = [cutoff]
        if group_id is not None:
            clauses.append("m.group_id = ?")
            params.append(group_id)
        if monitor_id is not None:
            clauses.append("m.id = ?")
            params.append(monitor_id)
        where = " AND ".join(clauses)
        rows = self.db.fetchall(
            f"""
            SELECT c.status, c.response_ms, c.previous_status, c.new_status
            FROM monitor_checks c
            JOIN monitors m ON m.id = c.monitor_id
            WHERE {where}
            ORDER BY c.monitor_id, c.checked_at ASC, c.id ASC
            """,
            params,
        )
        total = len(rows)
        good = len([row for row in rows if is_success_status(row["status"])])
        avg = [row["response_ms"] for row in rows if row["response_ms"] is not None]
        incidents = 0
        for row in rows:
            previous_status = row["previous_status"]
            previous_ok = previous_status not in {"offline", "error", "closed", "timeout"}
            current_ok = is_success_status(row["new_status"] or row["status"])
            if previous_ok and not current_ok:
                incidents += 1
        return {
            "checks": total,
            "uptime_percent": round((good / total) * 100, 2) if total else None,
            "avg_response_ms": round(sum(avg) / len(avg), 2) if avg else None,
            "incidents": incidents,
        }

    def _maintenance_until(self, payload: dict[str, Any]) -> str | None:
        if payload.get("until"):
            parsed = parse_time(payload["until"])
            return parsed.replace(microsecond=0).isoformat() if parsed else None
        minutes = payload.get("duration_minutes")
        if minutes is None:
            return "9999-12-31T23:59:59+00:00"
        return (datetime.now(timezone.utc) + timedelta(minutes=int(minutes))).replace(microsecond=0).isoformat()

    def _is_maintenance_active(self, monitor: dict[str, Any]) -> bool:
        return _is_future(monitor.get("maintenance_until")) or _is_future(monitor.get("group_maintenance_until"))


def _is_future(value: str | None) -> bool:
    parsed = parse_time(value)
    return bool(parsed and parsed > datetime.now(timezone.utc))


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int, minimum: int = 1) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(number, minimum)
