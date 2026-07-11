from __future__ import annotations

import asyncio
import difflib
import logging
import math
import os
import platform
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from . import __version__
from .config import AppConfig
from .database import Database, dumps_json, loads_json
from .discovery import DiscoveryService
from .ha import HomeAssistantClient
from .monitor_types import PRESETS, get_plugin, list_types, resolve_type
from .monitor_types.base import CheckResult, MonitorContext, is_success_status
from .secret_store import SecretStore
from .security import preserve_existing_secrets, sanitize_secrets
from .validators import normalize_url_key

LOGGER = logging.getLogger(__name__)
URL_MONITOR_TYPES = {"http_status", "http_hash", "rest_api"}
ANOMALY_METRICS = (
    "response_ms",
    "disk_usage_percent",
    "directory_size_bytes",
    "file_count",
    "packet_loss",
    "dns_lookup_ms",
)
TOPOLOGY_TYPE_ORDER = {
    "internet": 0,
    "router": 1,
    "switch": 2,
    "ap": 3,
    "server": 4,
    "service": 4,
    "iot": 5,
    "other": 5,
}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _has_cycle(graph: dict[int, set[int]]) -> bool:
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node: int) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph.get(node, set())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


class MonitorService:
    def __init__(
        self, db: Database, config: AppConfig, ha: HomeAssistantClient, secret_store: SecretStore | None = None
    ) -> None:
        self.db = db
        self.config = config
        self.ha = ha
        self.discovery = DiscoveryService(ha)
        self.secrets = secret_store or SecretStore(db, db.path.parent / "monitoring_center.key")
        self.secrets.migrate_plaintext()
        self._apply_persisted_settings()
        self.running: set[int] = set()
        self.active_checks: set[int] = set()
        self.queued_checks: set[int] = set()
        self._limit_condition = asyncio.Condition()
        self._limit_active = 0
        self._stop = asyncio.Event()
        self._last_tick_at: str | None = None
        self._scheduler_error_count = 0
        self._last_scheduler_error: str | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._baseline_cache: dict[tuple[int, str, float, int], tuple[float, dict[str, Any] | None]] = {}
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
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=2)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
        for task in list(self._tasks):
            task.cancel()

    async def _tick(self) -> None:
        self._last_tick_at = utc_now()
        await self._process_alert_retries()
        queue_limit = max(int(self.config.max_concurrent_checks) * 4, 20)
        due = self.db.fetchall(
            """SELECT s.monitor_id FROM scheduler_state s JOIN monitors m ON m.id=s.monitor_id
               WHERE m.enabled=1 AND s.next_check_at <= datetime('now')
               ORDER BY s.next_check_at, s.monitor_id LIMIT ?""",
            (queue_limit + 1,),
        )
        for position, row in enumerate(due):
            monitor_id = int(row["monitor_id"])
            if position >= queue_limit:
                self.db.execute(
                    "UPDATE scheduler_state SET last_skip_reason='queue_full' WHERE monitor_id=?", (monitor_id,)
                )
            elif monitor_id in self.running:
                self.db.execute(
                    "UPDATE scheduler_state SET last_skip_reason='already_running' WHERE monitor_id=?", (monitor_id,)
                )
            else:
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

    async def wait_for_tasks(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def list_monitors(self, enabled_only: bool = False, include_secrets: bool = False) -> list[dict[str, Any]]:
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
        return [self._hydrate_monitor(row, mask_secrets=not include_secrets) for row in rows]

    def get_monitor(self, monitor_id: int, include_secrets: bool = False) -> dict[str, Any]:
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
        return self._hydrate_monitor(row, mask_secrets=not include_secrets)

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
        return self.get_group(int(cursor.lastrowid or 0))

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

    def get_topology(self) -> dict[str, Any]:
        monitors = {int(monitor["id"]): monitor for monitor in self.list_monitors()}
        nodes = [
            self._hydrate_topology_node(row, monitors)
            for row in self.db.fetchall("SELECT * FROM topology_nodes ORDER BY id")
        ]
        edges = [
            {
                "id": row["id"],
                "source_node_id": row["source_node_id"],
                "target_node_id": row["target_node_id"],
                "label": row.get("label"),
                "metadata": loads_json(row.get("metadata_json"), {}),
            }
            for row in self.db.fetchall("SELECT * FROM topology_edges ORDER BY id")
        ]
        meta = self.db.fetchone("SELECT version FROM topology_meta WHERE singleton=1") or {"version": 1}
        return {"nodes": nodes, "edges": edges, "version": int(meta["version"])}

    def save_topology(self, payload: dict[str, Any]) -> dict[str, Any]:
        nodes = payload.get("nodes") or []
        edges = payload.get("edges") or []
        old_to_new: dict[int, int] = {}
        with self.db.transaction():
            meta = self.db.fetchone("SELECT version FROM topology_meta WHERE singleton=1") or {"version": 1}
            expected_version = payload.get("version")
            if expected_version is not None and int(expected_version) != int(meta["version"]):
                raise HTTPException(status_code=409, detail="Topologia została zmieniona w innej sesji")
            retained_nodes: set[int] = set()
            for node in nodes:
                old_id = int(node["id"]) if node.get("id") else None
                values = (
                    str(node["name"]).strip(),
                    node.get("type") or "other",
                    node.get("monitor_id"),
                    node.get("icon"),
                    float(node.get("x") or 0),
                    float(node.get("y") or 0),
                    dumps_json(node.get("metadata") or {}),
                )
                existing = self.db.fetchone("SELECT id FROM topology_nodes WHERE id=?", (old_id,)) if old_id else None
                if existing:
                    self.db.execute(
                        """UPDATE topology_nodes SET name=?,type=?,monitor_id=?,icon=?,x=?,y=?,metadata_json=?,
                           updated_at=datetime('now') WHERE id=?""",
                        (*values, old_id),
                    )
                    new_id = int(old_id or 0)
                else:
                    cursor = self.db.execute(
                        """INSERT INTO topology_nodes(name,type,monitor_id,icon,x,y,metadata_json)
                           VALUES (?,?,?,?,?,?,?)""",
                        values,
                    )
                    new_id = int(cursor.lastrowid or 0)
                retained_nodes.add(new_id)
                if old_id is not None:
                    old_to_new[old_id] = new_id
            if retained_nodes:
                placeholders = ",".join("?" for _ in retained_nodes)
                self.db.execute(f"DELETE FROM topology_nodes WHERE id NOT IN ({placeholders})", tuple(retained_nodes))
            else:
                self.db.execute("DELETE FROM topology_nodes")
            retained_edges: set[int] = set()
            graph: dict[int, set[int]] = {node_id: set() for node_id in retained_nodes}
            for edge in edges:
                source = old_to_new.get(int(edge["source_node_id"]), int(edge["source_node_id"]))
                target = old_to_new.get(int(edge["target_node_id"]), int(edge["target_node_id"]))
                if source not in retained_nodes or target not in retained_nodes or source == target:
                    raise HTTPException(status_code=422, detail="Krawędź wskazuje nieistniejący węzeł")
                graph[source].add(target)
                existing_edge = self.db.fetchone("SELECT id FROM topology_edges WHERE id=?", (edge.get("id"),))
                if existing_edge:
                    edge_id = int(existing_edge["id"])
                    self.db.execute(
                        """UPDATE topology_edges SET source_node_id=?,target_node_id=?,label=?,metadata_json=?,
                           updated_at=datetime('now') WHERE id=?""",
                        (source, target, edge.get("label"), dumps_json(edge.get("metadata") or {}), edge_id),
                    )
                else:
                    cursor = self.db.execute(
                        """INSERT INTO topology_edges(source_node_id,target_node_id,label,metadata_json)
                           VALUES (?,?,?,?)""",
                        (source, target, edge.get("label"), dumps_json(edge.get("metadata") or {})),
                    )
                    edge_id = int(cursor.lastrowid or 0)
                retained_edges.add(edge_id)
            if _has_cycle(graph):
                raise HTTPException(status_code=422, detail="Topologia nie może zawierać cyklu zależności")
            if retained_edges:
                placeholders = ",".join("?" for _ in retained_edges)
                self.db.execute(f"DELETE FROM topology_edges WHERE id NOT IN ({placeholders})", tuple(retained_edges))
            else:
                self.db.execute("DELETE FROM topology_edges")
            self.db.execute("UPDATE topology_meta SET version=version+1, updated_at=datetime('now') WHERE singleton=1")
        return self.get_topology()

    def auto_layout_topology(self) -> dict[str, Any]:
        topology = self.get_topology()
        if not topology["nodes"]:
            topology = self._seed_topology_from_monitors()
        nodes = topology["nodes"]
        if not nodes:
            return topology
        layers: dict[int, list[dict[str, Any]]] = {}
        for node in nodes:
            layer_id = TOPOLOGY_TYPE_ORDER.get(node.get("type") or "other", TOPOLOGY_TYPE_ORDER["other"])
            layers.setdefault(layer_id, []).append(node)
        for layer_index, layer_nodes in sorted(layers.items()):
            count = len(layer_nodes)
            for index, node in enumerate(layer_nodes):
                node["x"] = 90 + layer_index * 170
                node["y"] = 80 + index * 110 + max(0, 3 - count) * 35
        return self.save_topology({"nodes": nodes, "edges": topology["edges"]})

    def _seed_topology_from_monitors(self) -> dict[str, Any]:
        monitors = self.list_monitors()
        nodes: list[dict[str, Any]] = [
            {
                "id": -1,
                "name": "Internet",
                "type": "internet",
                "monitor_id": None,
                "icon": "cloud",
                "x": 0,
                "y": 0,
                "metadata": {},
            },
            {
                "id": -2,
                "name": "Router",
                "type": "router",
                "monitor_id": None,
                "icon": "router",
                "x": 0,
                "y": 0,
                "metadata": {},
            },
        ]
        edges = [{"source_node_id": -1, "target_node_id": -2, "label": "WAN", "metadata": {}}]
        for index, monitor in enumerate(monitors, start=3):
            node_id = -index
            node_type = _infer_topology_type(monitor)
            nodes.append(
                {
                    "id": node_id,
                    "name": monitor["name"],
                    "type": node_type,
                    "monitor_id": monitor["id"],
                    "icon": _topology_icon(node_type),
                    "x": 0,
                    "y": 0,
                    "metadata": {"target": monitor.get("target")},
                }
            )
            edges.append({"source_node_id": -2, "target_node_id": node_id, "label": "", "metadata": {}})
        return {"nodes": nodes, "edges": edges}

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

    async def scan_discovery(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return await asyncio.wait_for(
            self.discovery.scan(payload, self.list_monitors(include_secrets=True)),
            timeout=float(payload.get("total_timeout_seconds") or 60),
        )

    async def import_discovery(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sanitized = []
        for payload in payloads:
            sanitized.append(
                {
                    "type": payload["type"],
                    "name": payload["name"],
                    "target": payload["target"],
                    "interval_seconds": payload.get("interval_seconds"),
                    "group_id": payload.get("group_id"),
                    "enabled": payload.get("enabled", True),
                    "test_on_save": False,
                    "config": payload.get("config") or {},
                }
            )
        return await self.create_monitors_bulk(sanitized)

    async def update_monitor(self, monitor_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_monitor(monitor_id, include_secrets=True)
        if payload.get("name") and payload["name"] != current["name"] and hasattr(self.ha, "delete_monitor_states"):
            await self.ha.delete_monitor_states(current)
        merged = {
            "type": payload.get("type", current["type"]),
            "name": payload.get("name", current["name"]),
            "target": payload.get("target", current["target"]),
            "interval_seconds": payload.get("interval_seconds", current["interval_seconds"]),
            "group_id": payload.get("group_id", current.get("group_id")),
            "enabled": payload.get("enabled", current["enabled"]),
            "config": preserve_existing_secrets(payload.get("config", current["config"]), current["config"]),
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
                dumps_json(self.secrets.split_config(monitor_id, monitor["config"])),
                monitor_id,
            ),
        )
        self.db.execute(
            """INSERT INTO scheduler_state(monitor_id,next_check_at) VALUES (?,datetime('now'))
               ON CONFLICT(monitor_id) DO UPDATE SET next_check_at=datetime('now'),
               last_skip_reason='configuration_changed'""",
            (monitor_id,),
        )
        if payload.get("test_on_save", False):
            await self.run_check(monitor_id)
        updated = self.get_monitor(monitor_id)
        self._record_local_event(
            "monitor_updated",
            updated,
            current["status"],
            updated["status"],
            {"previous_config": sanitize_secrets(current["config"]), "config": updated["config"]},
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
            "details": sanitize_secrets(result.details or {}),
        }

    def delete_monitor(self, monitor_id: int) -> None:
        monitor = self.get_monitor(monitor_id)
        if hasattr(self.ha, "delete_monitor_states"):
            try:
                asyncio.get_running_loop().create_task(self.ha.delete_monitor_states(monitor))
            except RuntimeError:
                pass
        task = next((task for task in self._tasks if task.get_name() == f"monitor-check-{monitor_id}"), None)
        if task:
            task.cancel()
        self.db.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))

    def set_monitor_enabled(self, monitor_id: int, enabled: bool) -> dict[str, Any]:
        current = self.get_monitor(monitor_id)
        self.db.execute(
            "UPDATE monitors SET enabled = ?, updated_at = datetime('now') WHERE id = ?",
            (int(enabled), monitor_id),
        )
        if not enabled:
            self.db.execute("UPDATE scheduler_state SET last_skip_reason='disabled' WHERE monitor_id=?", (monitor_id,))
        else:
            self.db.execute(
                "UPDATE scheduler_state SET next_check_at=datetime('now') WHERE monitor_id=?", (monitor_id,)
            )
        updated = self.get_monitor(monitor_id)
        if bool(current["enabled"]) != bool(updated["enabled"]):
            self._record_local_event(
                "monitor_enabled" if updated["enabled"] else "monitor_disabled",
                updated,
                "enabled" if current["enabled"] else "disabled",
                "enabled" if updated["enabled"] else "disabled",
            )
        return updated

    async def run_check(self, monitor_id: int, force: bool = False) -> dict[str, Any]:
        if monitor_id in self.running:
            if not force:
                return {**self.get_monitor(monitor_id), "check_status": "already_running"}
            while monitor_id in self.running and not self._stop.is_set():
                await asyncio.sleep(0.05)
            return await self.run_check(monitor_id, force=False)
        self.running.add(monitor_id)
        self.queued_checks.add(monitor_id)
        started = time.monotonic()
        try:
            async with self._limit_condition:
                await self._limit_condition.wait_for(
                    lambda: self._limit_active < max(int(self.config.max_concurrent_checks), 1)
                )
                self._limit_active += 1
            try:
                self.queued_checks.discard(monitor_id)
                self.active_checks.add(monitor_id)
                try:
                    monitor = self.get_monitor(monitor_id, include_secrets=True)
                    if not monitor["enabled"]:
                        self.db.execute(
                            "UPDATE scheduler_state SET last_skip_reason='disabled_while_queued' WHERE monitor_id=?",
                            (monitor_id,),
                        )
                        return {**sanitize_secrets(monitor), "check_status": "completed"}
                    self.db.execute(
                        "UPDATE scheduler_state SET last_started_at=?, last_skip_reason=NULL WHERE monitor_id=?",
                        (utc_now(), monitor_id),
                    )
                    result = await self._run_check_now(monitor_id)
                    interval = int(result["interval_seconds"])
                    jitter = monitor_id % max(min(interval // 10, 30), 1)
                    self.db.execute(
                        """UPDATE scheduler_state SET last_finished_at=?, last_duration_ms=?,
                           next_check_at=datetime('now', ?),
                           last_scheduler_error=NULL, consecutive_scheduler_errors=0 WHERE monitor_id=?""",
                        (
                            utc_now(),
                            round((time.monotonic() - started) * 1000, 2),
                            f"+{interval + jitter} seconds",
                            monitor_id,
                        ),
                    )
                    return {**result, "check_status": "completed"}
                except asyncio.CancelledError:
                    self.db.execute(
                        """UPDATE scheduler_state SET last_scheduler_error='cancelled',
                           last_skip_reason='cancelled' WHERE monitor_id=?""",
                        (monitor_id,),
                    )
                    raise
                except Exception as exc:
                    self.db.execute(
                        """UPDATE scheduler_state SET last_finished_at=?, last_duration_ms=?, last_scheduler_error=?,
                           consecutive_scheduler_errors=consecutive_scheduler_errors+1,
                           next_check_at=datetime('now', '+15 seconds') WHERE monitor_id=?""",
                        (utc_now(), round((time.monotonic() - started) * 1000, 2), str(exc)[:500], monitor_id),
                    )
                    raise
                finally:
                    self.active_checks.discard(monitor_id)
            finally:
                async with self._limit_condition:
                    self._limit_active -= 1
                    self._limit_condition.notify_all()
        finally:
            self.queued_checks.discard(monitor_id)
            self.running.discard(monitor_id)

    async def _run_check_now(self, monitor_id: int) -> dict[str, Any]:
        monitor = self.get_monitor(monitor_id, include_secrets=True)
        previous_status = monitor["status"]
        result = await self._check(monitor)
        result = self._apply_anomaly_detection(monitor, result)
        if result.error:
            result.error = str(sanitize_secrets(result.error))
        final_status, failure_count, recovery_count, threshold_pending = self._status_after_thresholds(
            monitor,
            result.status,
        )
        now = utc_now()
        changed = previous_status != final_status
        content_changed = result.content_changed
        last_changed_at = now if changed or content_changed else monitor.get("last_changed_at")
        details = sanitize_secrets(
            {
                **(result.details or {}),
                "raw_status": result.status,
                "effective_status": final_status,
                "severity": self._monitor_severity(monitor, result.details),
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
        )

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
            self.db.execute(
                "UPDATE scheduler_state SET last_skip_reason='stopped_by_check' WHERE monitor_id=?", (monitor_id,)
            )
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
                    sanitize_secrets(
                        {
                            "monitor_id": monitor_id,
                            "monitor_type": monitor["type"],
                            "status": final_status,
                            "response_time_ms": result.response_ms,
                            "checked_at": now,
                            "error_message": result.error,
                            **details,
                        }
                    )
                ),
            ),
        )
        self.invalidate_baseline(monitor_id)
        self._sync_incident(monitor_id, previous_status, final_status, result.status, result.error, now)

        should_store_snapshot = (
            monitor["type"] == "http_hash"
            and bool(result.normalized_content)
            and bool(result.content_hash)
            and (content_changed or not monitor.get("last_content_hash"))
        )
        if should_store_snapshot:
            self._store_snapshot(monitor, result)

        updated = self.get_monitor(monitor_id, include_secrets=True)
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
        await self._handle_alert_routing(updated, previous_status, final_status, result.error, details)
        return sanitize_secrets(updated)

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

    def _apply_anomaly_detection(self, monitor: dict[str, Any], result: CheckResult) -> CheckResult:
        config = monitor.get("config") or {}
        if not config.get("anomaly_detection_enabled") or not monitor.get("id"):
            return result
        details = dict(result.details or {})
        min_samples = _safe_int(config.get("anomaly_min_samples"), 12, 2)
        anomalies: list[dict[str, Any]] = []
        strongest_status: str | None = None
        for metric, current in self._anomaly_candidate_values(result, details).items():
            if current is None or not math.isfinite(current):
                continue
            baseline = self.metric_baseline(
                int(monitor["id"]),
                metric,
                window_hours=max(_safe_float(config.get("anomaly_window_hours"), 24), 1),
                min_samples=min_samples,
            )
            if not baseline:
                continue
            anomaly = self._score_anomaly(metric, current, baseline, config)
            if not anomaly:
                continue
            anomalies.append(anomaly)
            if anomaly["status"] == "error":
                strongest_status = "error"
            elif strongest_status != "error":
                strongest_status = "warning"
        if not anomalies:
            return result

        primary = anomalies[0]
        details.update(
            {
                "baseline": primary["baseline"],
                "current_value": primary["current_value"],
                "anomaly_score": primary["anomaly_score"],
                "anomaly_reason": primary["anomaly_reason"],
                "anomaly_metric": primary["metric"],
                "anomalies": anomalies,
            }
        )
        result.details = details
        if "monitor_anomaly_detected" not in result.events:
            result.events.append("monitor_anomaly_detected")
        if strongest_status == "error":
            result.status = "error"
            result.error = result.error or primary["anomaly_reason"]
        elif strongest_status == "warning" and is_success_status(result.status):
            result.status = "warning"
            result.error = result.error or primary["anomaly_reason"]
        return result

    @staticmethod
    def _anomaly_candidate_values(result: CheckResult, details: dict[str, Any]) -> dict[str, float | None]:
        return {
            "response_ms": _optional_float(result.response_ms),
            "disk_usage_percent": _first_float(details, "disk_usage_percent", "used_percent"),
            "directory_size_bytes": _directory_size_bytes(details),
            "file_count": _first_float(details, "file_count"),
            "packet_loss": _optional_float(result.packet_loss)
            if result.packet_loss is not None
            else _first_float(details, "packet_loss", "packet_loss_percent"),
            "dns_lookup_ms": _first_float(details, "dns_lookup_ms"),
        }

    def _score_anomaly(
        self,
        metric: str,
        current: float,
        baseline: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        strategy = str(config.get("anomaly_baseline_method") or "median")
        if strategy not in {"mean", "median", "p95", "mad"}:
            strategy = "median"
        mean = float(baseline["median"] if strategy == "mad" else baseline[strategy])
        stddev = float(baseline["stddev"])
        multiplier = max(_safe_float(config.get("anomaly_stddev_multiplier"), 3), 0)
        warn_percent = max(_safe_float(config.get("anomaly_warn_percent_over_baseline"), 50), 0)
        error_percent = max(_safe_float(config.get("anomaly_error_percent_over_baseline"), 100), warn_percent)
        warn_threshold = max(mean * (1 + warn_percent / 100), mean + stddev * multiplier)
        error_threshold = max(mean * (1 + error_percent / 100), mean + stddev * multiplier * 1.5)
        if current <= warn_threshold:
            return None
        percent_over = ((current - mean) / mean * 100) if mean > 0 else 0
        z_score = ((current - mean) / stddev) if stddev > 0 else (math.inf if current > mean else 0)
        status = "error" if current >= error_threshold else "warning"
        reason = f"{metric} {current:.2f} przekracza baseline {mean:.2f} o {percent_over:.1f}% ({status})"
        return {
            "metric": metric,
            "status": status,
            "baseline": baseline,
            "current_value": round(current, 4),
            "anomaly_score": round(float(z_score if math.isfinite(z_score) else 999), 4),
            "anomaly_reason": reason,
            "thresholds": {"warning": round(warn_threshold, 4), "error": round(error_threshold, 4)},
        }

    def metric_baseline(
        self,
        monitor_id: int,
        metric: str,
        *,
        window_hours: float,
        min_samples: int,
    ) -> dict[str, Any] | None:
        key = (monitor_id, metric, float(window_hours), int(min_samples))
        cached = self._baseline_cache.get(key)
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
        values = self._metric_history_values(monitor_id, metric, window_hours)
        if len(values) < min_samples:
            self._baseline_cache[key] = (time.monotonic(), None)
            return None
        sorted_values = sorted(values)
        median = statistics.median(sorted_values)
        baseline = {
            "metric": metric,
            "sample_count": len(values),
            "mean": round(statistics.fmean(values), 4),
            "median": round(statistics.median(sorted_values), 4),
            "p95": round(_percentile(sorted_values, 0.95), 4),
            "stddev": round(statistics.pstdev(values), 4),
            "mad": round(statistics.median(abs(value - median) for value in values), 4),
            "window_hours": window_hours,
        }
        self._baseline_cache[key] = (time.monotonic(), baseline)
        return baseline

    def invalidate_baseline(self, monitor_id: int) -> None:
        self._baseline_cache = {key: value for key, value in self._baseline_cache.items() if key[0] != monitor_id}

    def _metric_history_values(self, monitor_id: int, metric: str, window_hours: float) -> list[float]:
        cutoff = (datetime.now(UTC) - timedelta(hours=window_hours)).replace(microsecond=0).isoformat()
        rows = self.db.fetchall(
            """
            SELECT response_ms, packet_loss, details_json
            FROM monitor_checks
            WHERE monitor_id = ? AND checked_at >= ? AND status NOT IN ('error', 'offline', 'unknown')
            ORDER BY checked_at DESC, id DESC
            LIMIT 500
            """,
            (monitor_id, cutoff),
        )
        values: list[float] = []
        for row in rows:
            details = loads_json(row.get("details_json"), {})
            value = self._metric_value_from_check(metric, row, details)
            if value is not None and math.isfinite(value):
                values.append(value)
        return values

    @staticmethod
    def _metric_value_from_check(metric: str, row: dict[str, Any], details: dict[str, Any]) -> float | None:
        if metric == "response_ms":
            return _optional_float(row.get("response_ms"))
        if metric == "packet_loss":
            packet_loss = _optional_float(row.get("packet_loss"))
            if packet_loss is not None:
                return packet_loss
            return _first_float(details, "packet_loss", "packet_loss_percent")
        if metric == "disk_usage_percent":
            return _first_float(details, "disk_usage_percent", "used_percent")
        if metric == "directory_size_bytes":
            return _directory_size_bytes(details)
        if metric == "file_count":
            return _first_float(details, "file_count")
        if metric == "dns_lookup_ms":
            return _first_float(details, "dns_lookup_ms")
        return None

    def _schedule_retry(self, monitor: dict[str, Any], details: dict[str, Any]) -> None:
        retry_delay = self._monitor_int_setting(monitor, "retry_delay_seconds", self.config.retry_delay_seconds, 0)
        if retry_delay <= 0:
            return
        self.db.execute(
            "UPDATE scheduler_state SET next_check_at=datetime('now', ?) WHERE monitor_id=?",
            (f"+{retry_delay} seconds", int(monitor["id"])),
        )
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
            "severity": self._monitor_severity(monitor, details),
            "details": sanitize_secrets(details or {}),
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
            "severity": self._monitor_severity(monitor, details),
            "details": sanitize_secrets(details or {}),
        }
        self.db.execute(
            """
            INSERT INTO events(monitor_id, event_type, previous_state, new_state, payload_json, delivered_to_ha)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (monitor["id"], event_type, previous_state, new_state, dumps_json(payload)),
        )

    @staticmethod
    def _monitor_severity(monitor: dict[str, Any], details: dict[str, Any] | None = None) -> str:
        if details and details.get("severity"):
            return str(details["severity"])
        raw_config = monitor.get("config")
        config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
        return str(config.get("severity") or "warning")

    async def _handle_alert_routing(
        self,
        monitor: dict[str, Any],
        previous_status: str | None,
        final_status: str,
        error: str | None,
        details: dict[str, Any],
    ) -> None:
        config = dict(monitor.get("config") or {})
        state = dict(config.get("_alert_state") or {})
        severity = self._monitor_severity(monitor, details)
        active = final_status == "warning" or self._is_incident_status(final_status)
        now = utc_now()
        event_details = {
            **details,
            "severity": severity,
            "alert_channels": config.get("alert_channels", ["home_assistant_event"]),
        }
        if active:
            key = f"{final_status}:{error or details.get('error_message') or ''}"[:500]
            last_at = parse_time(state.get("last_at"))
            minutes_since = (datetime.now(UTC) - last_at).total_seconds() / 60 if last_at else None
            cooldown = int(config.get("cooldown_minutes") or 0)
            repeat_every = int(config.get("repeat_every_minutes") or 0)
            repeats = int(state.get("repeats") or 0)
            max_repeats = int(config.get("max_repeats") or 0)
            duplicate = bool(config.get("deduplicate_alerts", True)) and state.get("last_key") == key
            suppressed_reason: str | None = None
            repeated = False
            root_cause = self._root_cause_for_monitor(int(monitor["id"]))
            if root_cause:
                suppressed_reason = "parent_failure"
                event_details["root_cause"] = root_cause
            elif self._is_maintenance_active(monitor):
                suppressed_reason = "maintenance"
            elif duplicate and cooldown and minutes_since is not None and minutes_since < cooldown:
                suppressed_reason = "cooldown"
            elif duplicate and repeat_every and minutes_since is not None and minutes_since >= repeat_every:
                repeated = True
                if max_repeats and repeats >= max_repeats:
                    suppressed_reason = "max_repeats"
            elif duplicate and not cooldown and not repeat_every:
                suppressed_reason = "deduplicated"

            if suppressed_reason:
                self._record_local_event(
                    "monitor_alert_suppressed",
                    monitor,
                    previous_status,
                    final_status,
                    {**event_details, "alert_sent": False, "suppressed_reason": suppressed_reason},
                )
            else:
                event_type = "monitor_alert_repeated" if repeated else "monitor_alert"
                if "home_assistant_event" in config.get("alert_channels", ["home_assistant_event"]):
                    await self._record_event(
                        event_type,
                        monitor,
                        previous_status,
                        final_status,
                        {**event_details, "alert_sent": True},
                    )
                else:
                    self._record_local_event(
                        event_type,
                        monitor,
                        previous_status,
                        final_status,
                        {**event_details, "alert_sent": True},
                    )
                await self._deliver_alert_channels(config, monitor, final_status, event_details)
                state["last_at"] = now
                state["last_key"] = key
                state["repeats"] = repeats + 1 if repeated else 0
            state["active"] = True
        else:
            if state.get("active") and config.get("notify_on_recovery", True):
                await self._record_event(
                    "monitor_alert_recovered",
                    monitor,
                    previous_status,
                    final_status,
                    {**event_details, "alert_sent": True},
                )
            state = {"active": False, "last_recovered_at": now}

        self.db.execute(
            """UPDATE monitor_runtime SET alert_state_json=?, last_alert_at=?, alert_repeat_count=?,
               updated_at=datetime('now') WHERE monitor_id=?""",
            (dumps_json(state), state.get("last_at"), int(state.get("repeats") or 0), monitor["id"]),
        )

    def _root_cause_for_monitor(self, monitor_id: int) -> dict[str, Any] | None:
        rows = self.db.fetchall(
            """WITH RECURSIVE ancestors(id) AS (
                 SELECT e.source_node_id FROM topology_edges e
                 JOIN topology_nodes child ON child.id=e.target_node_id WHERE child.monitor_id=?
                 UNION
                 SELECT e.source_node_id FROM topology_edges e JOIN ancestors a ON e.target_node_id=a.id
               )
               SELECT m.id,m.name,m.status FROM ancestors a JOIN topology_nodes n ON n.id=a.id
               JOIN monitors m ON m.id=n.monitor_id""",
            (monitor_id,),
        )
        failed = next((row for row in rows if self._is_incident_status(str(row["status"]))), None)
        if not failed:
            return None
        affected = self.db.fetchone(
            """WITH RECURSIVE descendants(id) AS (
                 SELECT id FROM topology_nodes WHERE monitor_id=?
                 UNION SELECT e.target_node_id FROM topology_edges e JOIN descendants d ON e.source_node_id=d.id
               ) SELECT COUNT(DISTINCT monitor_id) AS count FROM topology_nodes
                 WHERE id IN (SELECT id FROM descendants) AND monitor_id IS NOT NULL""",
            (failed["id"],),
        )
        return {
            "monitor_id": failed["id"],
            "monitor_name": failed["name"],
            "affected_count": affected["count"] if affected else 1,
        }

    async def _deliver_alert_channels(
        self,
        config: dict[str, Any],
        monitor: dict[str, Any],
        final_status: str,
        details: dict[str, Any],
    ) -> None:
        channels = config.get("alert_channels", ["home_assistant_event"])
        title = f"Monitoring Center: {monitor['name']}"
        message = f"{monitor['name']} changed to {final_status} ({details.get('severity', 'warning')})"
        if "persistent_notification" in channels or "home_assistant_persistent_notification" in channels:
            await self._deliver_channel(
                monitor,
                "persistent_notification",
                {"title": title, "message": message},
                lambda: self.ha.create_persistent_notification(title, message),
            )
        if "webhook" in channels and config.get("webhook_url"):
            payload = sanitize_secrets(
                {
                    "monitor_id": monitor["id"],
                    "monitor_name": monitor["name"],
                    "monitor_type": monitor["type"],
                    "target": monitor["target"],
                    "new_state": final_status,
                    "details": details,
                }
            )
            await self._deliver_channel(
                monitor, "webhook", payload, lambda: self.ha.post_webhook(str(config["webhook_url"]), payload)
            )

    async def _deliver_channel(
        self, monitor: dict[str, Any], channel: str, payload: dict[str, Any], sender: Any
    ) -> None:
        cursor = self.db.execute(
            """INSERT INTO alert_deliveries(monitor_id,channel,payload_json,result,next_attempt_at)
               VALUES (?,?,?,'pending',datetime('now'))""",
            (monitor["id"], channel, dumps_json(sanitize_secrets(payload))),
        )
        delivery_id = int(cursor.lastrowid or 0)
        try:
            delivered = bool(await sender())
            error = None if delivered else "Kanał odrzucił dostawę"
        except Exception as exc:
            delivered = False
            error = str(exc)[:500]
        self.db.execute(
            """UPDATE alert_deliveries SET attempted_at=datetime('now'), result=?, error=?, attempt_count=1,
               next_attempt_at=datetime('now','+30 seconds') WHERE id=?""",
            ("delivered" if delivered else "retry", error, delivery_id),
        )

    async def _process_alert_retries(self) -> None:
        rows = self.db.fetchall(
            """SELECT * FROM alert_deliveries WHERE result='retry' AND attempt_count < 5
               AND next_attempt_at <= datetime('now') ORDER BY next_attempt_at,id LIMIT 20"""
        )
        for row in rows:
            payload = loads_json(row["payload_json"], {})
            monitor = self.get_monitor(int(row["monitor_id"]), include_secrets=True)
            config = monitor.get("config") or {}
            if row["channel"] == "webhook" and config.get("webhook_url"):
                delivered = await self.ha.post_webhook(str(config["webhook_url"]), payload)
            elif row["channel"] == "persistent_notification":
                delivered = await self.ha.create_persistent_notification(
                    str(payload.get("title") or "Monitoring Center"), str(payload.get("message") or "Alert")
                )
            else:
                delivered = False
            attempts = int(row["attempt_count"]) + 1
            delay = min(3600, 30 * (2 ** (attempts - 1)))
            self.db.execute(
                """UPDATE alert_deliveries SET attempted_at=datetime('now'),result=?,attempt_count=?,
                   next_attempt_at=datetime('now',?),error=? WHERE id=?""",
                (
                    "delivered" if delivered else "retry",
                    attempts,
                    f"+{delay} seconds",
                    None if delivered else "Kanał odrzucił dostawę",
                    row["id"],
                ),
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
        ended = parse_time(ended_at) or datetime.now(UTC)
        if not started:
            return 0
        return max(0, int((ended - started).total_seconds()))

    async def cleanup_history(self) -> None:
        settings = self.get_settings()
        default = int(settings.get("retention_days", self.config.retention_days))
        policies = (
            ("monitor_checks", "checked_at", "retention_checks_days"),
            ("events", "created_at", "retention_events_days"),
            ("incidents", "ended_at", "retention_incidents_days"),
            ("website_snapshots", "created_at", "retention_snapshots_days"),
        )
        for table, column, key in policies:
            retention = int(settings.get(key) or default)
            cutoff = (datetime.now(UTC) - timedelta(days=retention)).replace(microsecond=0).isoformat()
            self.db.execute(f"DELETE FROM {table} WHERE {column} IS NOT NULL AND {column} < ?", (cutoff,))
        self.db.checkpoint()
        self.db.optimize()
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
        anomaly_filter = str(filters.get("status") or "").lower() == "anomaly"
        if filters.get("status") and not anomaly_filter:
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
        rows = self.db.fetchall(
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
        for row in rows:
            details = loads_json(row.get("details_json"), {})
            row["severity"] = details.get("severity") or details.get("alert_severity")
            row["anomaly"] = bool(details.get("anomaly_reason"))
        if anomaly_filter:
            rows = [row for row in rows if row.get("anomaly")]
        if filters.get("severity"):
            rows = [row for row in rows if str(row.get("severity") or "") == str(filters["severity"])]
        return rows

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
            "active_anomalies": self._active_anomaly_count(),
            "monitors": monitors,
            "groups": self.list_groups(),
            "slo": self.get_slo_stats(),
        }

    def _active_anomaly_count(self) -> int:
        rows = self.db.fetchall(
            """
            SELECT c.monitor_id, c.details_json
            FROM monitor_checks c
            JOIN (
                SELECT monitor_id, MAX(id) AS latest_id
                FROM monitor_checks
                GROUP BY monitor_id
            ) latest ON latest.latest_id = c.id
            """
        )
        count = 0
        for row in rows:
            details = loads_json(row.get("details_json"), {})
            if details.get("anomaly_reason"):
                count += 1
        return count

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

    def get_cursor_page(self, resource: str, limit: int, cursor: str | None = None, **filters: Any) -> dict[str, Any]:
        definitions = {
            "history": ("monitor_checks", "monitor_id"),
            "events": ("events", "monitor_id"),
            "incidents": ("incidents", "monitor_id"),
            "monitors": ("monitors", None),
            "snapshots": ("website_snapshots", "monitor_id"),
        }
        if resource not in definitions:
            raise ValueError(resource)
        table, monitor_column = definitions[resource]
        clauses: list[str] = []
        params: list[Any] = []
        if cursor:
            try:
                clauses.append("id < ?")
                params.append(int(cursor))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Nieprawidłowy kursor") from exc
        monitor_id = filters.get("monitor_id")
        if monitor_id is not None and monitor_column:
            clauses.append(f"{monitor_column} = ?")
            params.append(int(monitor_id))
        if resource == "history" and filters.get("status"):
            clauses.append("status = ?")
            params.append(str(filters["status"]))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total_clauses = [clause for clause in clauses if clause != "id < ?"]
        total_params = params[1:] if cursor else params
        total_where = f"WHERE {' AND '.join(total_clauses)}" if total_clauses else ""
        bounded = min(max(int(limit), 1), 500)
        rows = self.db.fetchall(f"SELECT * FROM {table} {where} ORDER BY id DESC LIMIT ?", (*params, bounded + 1))
        has_more = len(rows) > bounded
        rows = rows[:bounded]
        if resource == "monitors":
            rows = [self._hydrate_monitor(row) for row in rows]
        elif resource == "events":
            for row in rows:
                row["payload"] = loads_json(row.pop("payload_json", None), {})
        elif resource == "history":
            for row in rows:
                row["details"] = loads_json(row.pop("details_json", None), {})
        total_row = self.db.fetchone(f"SELECT COUNT(*) AS count FROM {table} {total_where}", total_params)
        return {
            "items": rows,
            "pagination": {
                "limit": bounded,
                "next_cursor": str(rows[-1]["id"]) if has_more and rows else None,
                "has_more": has_more,
                "total": int(total_row["count"] if total_row else 0),
            },
        }

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

    def update_incident(self, incident_id: int, action: str, comment: str | None = None) -> dict[str, Any]:
        incident = self.db.fetchone("SELECT * FROM incidents WHERE id=?", (incident_id,))
        if not incident:
            raise HTTPException(status_code=404, detail="Incydent nie istnieje")
        if action == "acknowledged":
            self.db.execute(
                "UPDATE incidents SET acknowledged_at=datetime('now'),operator_comment=? WHERE id=?",
                (comment, incident_id),
            )
        elif action == "closed":
            self.db.execute(
                """UPDATE incidents SET status='closed',ended_at=COALESCE(ended_at,datetime('now')),
                   operator_comment=? WHERE id=?""",
                (comment, incident_id),
            )
        else:
            raise ValueError(action)
        self.db.execute(
            "INSERT INTO incident_history(incident_id,action,comment) VALUES (?,?,?)",
            (incident_id, action, comment),
        )
        updated = self.db.fetchone("SELECT * FROM incidents WHERE id=?", (incident_id,))
        assert updated is not None
        updated["history"] = self.db.fetchall(
            "SELECT action,comment,created_at FROM incident_history WHERE incident_id=? ORDER BY id DESC",
            (incident_id,),
        )
        return updated

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
        raw_details = payload.get("details")
        details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
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
            "allow_private_monitor_targets": self.config.allow_private_monitor_targets,
            "allow_private_webhooks": self.config.allow_private_webhooks,
            "publish_home_assistant_entities": self.config.publish_home_assistant_entities,
            "publish_home_assistant_events": self.config.publish_home_assistant_events,
            "entity_prefix": self.config.entity_prefix,
            "retention_checks_days": self.config.retention_days,
            "retention_events_days": self.config.retention_days,
            "retention_incidents_days": self.config.retention_days,
            "retention_snapshots_days": self.config.retention_days,
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
        runtime: dict[str, Any] = {}
        if "records" in details:
            runtime["last_dns_result_json"] = dumps_json(details["records"])
        if "state" in details:
            runtime["last_ha_state"] = details["state"]
        if "last_hash" in details or "last_output_hash" in details:
            runtime["last_output_hash"] = details.get("last_output_hash") or details.get("last_hash")
        if "anomaly_reason" in details:
            runtime["last_anomaly_json"] = dumps_json(
                {
                    "metric": details.get("anomaly_metric"),
                    "baseline": details.get("baseline"),
                    "current_value": details.get("current_value"),
                    "anomaly_score": details.get("anomaly_score"),
                    "anomaly_reason": details.get("anomaly_reason"),
                }
            )
        if "_alert_state" in details:
            runtime["alert_state_json"] = dumps_json(details["_alert_state"])
        if runtime:
            columns = ", ".join(f"{key}=?" for key in runtime)
            self.db.execute(
                f"UPDATE monitor_runtime SET {columns}, updated_at=datetime('now') WHERE monitor_id=?",
                (*runtime.values(), monitor["id"]),
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
        now = datetime.now(UTC)
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

    def get_bootstrap(self) -> dict[str, Any]:
        monitors = self.list_monitors()
        summary = self.get_summary()
        summary["monitors"] = monitors
        return {
            "summary": summary,
            "monitors": monitors,
            "groups": self.list_groups(),
            "settings": self.get_settings(),
            "monitor_types": self.get_monitor_types(),
            "presets": self.get_presets(),
            "incidents": self.list_incidents(limit=100),
            "topology": self.get_topology(),
            "generated_at": utc_now(),
        }

    async def full_diagnostics(self) -> dict[str, Any]:
        data = self.diagnostics()
        data.update(
            {
                "addon_version": __version__,
                "process": self._process_usage(),
                "wal_status": self._wal_status(),
                "checks_last_24h": self._checks_last_24h(),
                "avg_check_response_ms": self._avg_check_response_ms(),
                "home_assistant_api": await self.ha.get_api_status(),
                "data_writable": self._data_writable_status(),
                "log_file_status": self._log_file_status(),
            }
        )
        return data

    async def run_self_check(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        started = loop.time()
        await asyncio.sleep(0)
        lag_ms = (loop.time() - started) * 1000
        pending_alerts = self.db.fetchone(
            "SELECT COUNT(*) AS count FROM alert_deliveries WHERE result IN ('pending','retry')"
        )
        checks = [
            self._self_check_sqlite(),
            self._self_check_data_path(),
            {
                "name": "scheduler",
                "ok": not self._stop.is_set(),
                "queued": len(self.queued_checks),
                "active": len(self.active_checks),
            },
            {
                "name": "secret_storage",
                "ok": self.secrets.key_path.exists() and (self.secrets.key_path.stat().st_mode & 0o077) == 0,
            },
            {
                "name": "alert_deliveries",
                "ok": True,
                "pending": int(pending_alerts["count"] if pending_alerts else 0),
            },
            {"name": "event_loop_lag", "ok": lag_ms < 1000, "lag_ms": round(lag_ms, 3)},
            await self._self_check_ha_api(),
        ]
        if self.config.publish_home_assistant_events:
            checks.append(await self._self_check_ha_event())
        if self.config.publish_home_assistant_entities:
            checks.append(await self._self_check_ha_entity())
        ok = all(item["ok"] for item in checks)
        payload = sanitize_secrets(
            {
                "status": "ok" if ok else "error",
                "checked_at": utc_now(),
                "checks": checks,
            }
        )
        self.db.execute(
            """
            INSERT INTO events(monitor_id, event_type, previous_state, new_state, payload_json, delivered_to_ha)
            VALUES (NULL, 'diagnostics_self_check', NULL, ?, ?, 0)
            """,
            (payload["status"], dumps_json(payload)),
        )
        return payload

    def _self_check_sqlite(self) -> dict[str, Any]:
        try:
            value = f"self-check-{time.time_ns()}"
            self.db.execute("CREATE TEMP TABLE IF NOT EXISTS diagnostics_self_check(value TEXT)")
            self.db.execute("DELETE FROM diagnostics_self_check")
            self.db.execute("INSERT INTO diagnostics_self_check(value) VALUES (?)", (value,))
            row = self.db.fetchone("SELECT value FROM diagnostics_self_check LIMIT 1")
            integrity = self.db.fetchone("PRAGMA integrity_check")
            return {
                "name": "sqlite_read_write",
                "ok": bool(row and row["value"] == value and integrity and next(iter(integrity.values())) == "ok"),
                "integrity": next(iter(integrity.values())) if integrity else "unknown",
            }
        except Exception as exc:
            return {"name": "sqlite_read_write", "ok": False, "error": str(exc)}

    def _self_check_data_path(self) -> dict[str, Any]:
        path = self.config.database_path.parent / ".monitoring_center_self_check"
        try:
            value = f"self-check-{time.time_ns()}"
            path.write_text(value, encoding="utf-8")
            ok = path.read_text(encoding="utf-8") == value
            path.unlink(missing_ok=True)
            return {"name": "data_read_write", "ok": ok, "path": str(self.config.database_path.parent)}
        except Exception as exc:
            return {
                "name": "data_read_write",
                "ok": False,
                "path": str(self.config.database_path.parent),
                "error": str(exc),
            }

    async def _self_check_ha_api(self) -> dict[str, Any]:
        status = await self.ha.get_api_status()
        return {"name": "home_assistant_api", **status}

    async def _self_check_ha_event(self) -> dict[str, Any]:
        payload = {"source": "monitoring_center", "test": True, "created_at": utc_now()}
        delivered = await self.ha.fire_event("monitoring_center_self_check", payload)
        return {"name": "home_assistant_event_publish", "ok": bool(delivered), "enabled": True}

    async def _self_check_ha_entity(self) -> dict[str, Any]:
        entity_id = f"sensor.{self.config.entity_prefix}_self_check"
        delivered = await self.ha.publish_test_state(
            entity_id,
            "ok",
            {"friendly_name": "Monitoring Center Self Check", "checked_at": utc_now()},
        )
        return {"name": "home_assistant_entity_publish", "ok": bool(delivered), "enabled": True, "entity_id": entity_id}

    def _process_usage(self) -> dict[str, Any]:
        started = parse_time(self.started_at)
        usage: dict[str, Any] = {
            "pid": os.getpid(),
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "uptime_seconds": max(0, int((datetime.now(UTC) - started).total_seconds())) if started else None,
        }
        try:
            import resource

            usage["max_rss_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # type: ignore[attr-defined]
        except Exception:
            usage["max_rss_kb"] = None
        try:
            times = os.times()
            usage["cpu_seconds"] = round(float(times.user + times.system), 4)
        except Exception:
            usage["cpu_seconds"] = None
        return usage

    def _wal_status(self) -> dict[str, Any]:
        wal_path = self.config.database_path.with_name(f"{self.config.database_path.name}-wal")
        return {"exists": wal_path.exists(), "size_bytes": wal_path.stat().st_size if wal_path.exists() else 0}

    def _checks_last_24h(self) -> int:
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).replace(microsecond=0).isoformat()
        row = self.db.fetchone("SELECT COUNT(*) AS count FROM monitor_checks WHERE checked_at >= ?", (cutoff,))
        return int(row["count"] if row else 0)

    def _avg_check_response_ms(self) -> float | None:
        row = self.db.fetchone("SELECT AVG(response_ms) AS value FROM monitor_checks WHERE response_ms IS NOT NULL")
        return round(float(row["value"]), 2) if row and row["value"] is not None else None

    def _data_writable_status(self) -> dict[str, Any]:
        path = self.config.database_path.parent
        return {"path": str(path), "ok": os.access(path, os.W_OK)}

    def _log_file_status(self) -> dict[str, Any]:
        return {
            "path": str(self.config.log_file),
            "exists": self.config.log_file.exists(),
            "writable": os.access(self.config.log_file.parent, os.W_OK),
            "size_bytes": self.config.log_file.stat().st_size if self.config.log_file.exists() else 0,
        }

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        monitor_type = resolve_type(payload["type"])
        config = self._normalize_monitor_config(payload.get("config") or {})
        try:
            plugin = get_plugin(monitor_type)
            target, config = plugin.validate(payload["target"], config, self.config)
            config = self._normalize_common_monitor_config(config)
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

    @staticmethod
    def _hydrate_topology_node(row: dict[str, Any], monitors: dict[int, dict[str, Any]]) -> dict[str, Any]:
        monitor_id = row.get("monitor_id")
        monitor = monitors.get(int(monitor_id)) if monitor_id is not None else None
        status = monitor.get("status") if monitor else "neutral"
        return {
            "id": row["id"],
            "name": row["name"],
            "type": row.get("type") or "other",
            "monitor_id": monitor_id,
            "icon": row.get("icon") or _topology_icon(row.get("type") or "other"),
            "x": float(row.get("x") or 0),
            "y": float(row.get("y") or 0),
            "metadata": loads_json(row.get("metadata_json"), {}),
            "status": status or "neutral",
            "monitor": {
                "id": monitor["id"],
                "name": monitor["name"],
                "type": monitor["type"],
                "target": monitor["target"],
                "enabled": monitor["enabled"],
            }
            if monitor
            else None,
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
                "{}",
            ),
        )
        monitor_id = int(cursor.lastrowid or 0)
        clean = self.secrets.split_config(monitor_id, monitor["config"])
        self.db.execute("UPDATE monitors SET config_json=? WHERE id=?", (dumps_json(clean), monitor_id))
        self.db.execute(
            "INSERT INTO monitor_runtime(monitor_id) VALUES (?) ON CONFLICT(monitor_id) DO NOTHING", (monitor_id,)
        )
        jitter = monitor_id % 30
        self.db.execute(
            "INSERT INTO scheduler_state(monitor_id,next_check_at) VALUES (?,datetime('now', ?))",
            (monitor_id, f"+{jitter} seconds"),
        )
        return monitor_id

    @staticmethod
    def _normalize_monitor_config(config: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(config)
        for runtime_key in (
            "_alert_state",
            "last_dns_result",
            "last_ha_state",
            "last_hash",
            "last_output_hash",
            "last_anomaly",
        ):
            normalized.pop(runtime_key, None)
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

    @staticmethod
    def _normalize_common_monitor_config(config: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(config)
        severity = str(normalized.get("severity") or "warning").strip().lower()
        normalized["severity"] = severity if severity in {"info", "warning", "critical"} else "warning"
        normalized["cooldown_minutes"] = _safe_int(normalized.get("cooldown_minutes"), 30, 0)
        normalized["notify_on_recovery"] = bool(normalized.get("notify_on_recovery", True))
        normalized["repeat_every_minutes"] = _safe_int(normalized.get("repeat_every_minutes"), 0, 0)
        normalized["max_repeats"] = _safe_int(normalized.get("max_repeats"), 0, 0)
        normalized["deduplicate_alerts"] = bool(normalized.get("deduplicate_alerts", True))
        channels = normalized.get("alert_channels")
        if isinstance(channels, list):
            normalized["alert_channels"] = [str(channel) for channel in channels if str(channel).strip()]
        elif channels:
            normalized["alert_channels"] = [item.strip() for item in str(channels).split(",") if item.strip()]
        else:
            normalized["alert_channels"] = ["home_assistant_event"]
        normalized["anomaly_detection_enabled"] = bool(normalized.get("anomaly_detection_enabled", False))
        normalized["anomaly_window_hours"] = _safe_int(normalized.get("anomaly_window_hours"), 24, 1)
        normalized["anomaly_min_samples"] = _safe_int(normalized.get("anomaly_min_samples"), 12, 2)
        normalized["anomaly_stddev_multiplier"] = max(_safe_float(normalized.get("anomaly_stddev_multiplier"), 3), 0)
        normalized["anomaly_warn_percent_over_baseline"] = max(
            _safe_float(normalized.get("anomaly_warn_percent_over_baseline"), 50),
            0,
        )
        normalized["anomaly_error_percent_over_baseline"] = max(
            _safe_float(normalized.get("anomaly_error_percent_over_baseline"), 100),
            normalized["anomaly_warn_percent_over_baseline"],
        )
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

    def _hydrate_monitor(self, row: dict[str, Any], mask_secrets: bool = True) -> dict[str, Any]:
        row["enabled"] = bool(row["enabled"])
        row["failure_count"] = int(row.get("failure_count") or 0)
        row["recovery_count"] = int(row.get("recovery_count") or 0)
        row["type"] = resolve_type(row["type"])
        row["config"] = self.secrets.hydrate(int(row["id"]), loads_json(row.pop("config_json", None), {}))
        if mask_secrets:
            row["config"] = sanitize_secrets(row["config"])
        else:
            runtime = self.db.fetchone("SELECT * FROM monitor_runtime WHERE monitor_id=?", (row["id"],)) or {}
            if runtime.get("last_dns_result_json"):
                row["config"]["last_dns_result"] = loads_json(runtime["last_dns_result_json"], [])
            if runtime.get("last_ha_state") is not None:
                row["config"]["last_ha_state"] = runtime["last_ha_state"]
            if runtime.get("last_output_hash"):
                row["config"]["last_output_hash"] = runtime["last_output_hash"]
                row["config"]["last_hash"] = runtime["last_output_hash"]
            if runtime.get("alert_state_json"):
                row["config"]["_alert_state"] = loads_json(runtime["alert_state_json"], {})
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
        cutoff = (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0).isoformat()
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
        return (datetime.now(UTC) + timedelta(minutes=int(minutes))).replace(microsecond=0).isoformat()

    def _is_maintenance_active(self, monitor: dict[str, Any]) -> bool:
        return _is_future(monitor.get("maintenance_until")) or _is_future(monitor.get("group_maintenance_until"))


def _is_future(value: str | None) -> bool:
    parsed = parse_time(value)
    return bool(parsed and parsed > datetime.now(UTC))


def _safe_float(value: object, default: float) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int, minimum: int = 1) -> int:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        number = default
    return max(number, minimum)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _first_float(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _optional_float(source.get(key))
        if value is not None:
            return value
    return None


def _directory_size_bytes(details: dict[str, Any]) -> float | None:
    direct = _first_float(details, "directory_size_bytes")
    if direct is not None:
        return direct
    size_mb = _first_float(details, "size_mb")
    return size_mb * 1024 * 1024 if size_mb is not None else None


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = (len(sorted_values) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return sorted_values[int(index)]
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _topology_icon(node_type: str) -> str:
    return {
        "internet": "cloud",
        "router": "router",
        "switch": "network",
        "ap": "wifi",
        "server": "server",
        "iot": "cpu",
        "service": "box",
        "other": "circle",
    }.get(node_type, "circle")


def _infer_topology_type(monitor: dict[str, Any]) -> str:
    text = f"{monitor.get('name', '')} {monitor.get('target', '')} {monitor.get('type', '')}".lower()
    if "router" in text or "gateway" in text:
        return "router"
    if "switch" in text:
        return "switch"
    if " ap" in f" {text}" or "wifi" in text or "unifi" in text:
        return "ap"
    if any(token in text for token in ["nas", "server", "docker", "linux", "ssh"]):
        return "server"
    if any(token in text for token in ["mqtt", "pihole", "ha_", "home assistant", "http", "rest"]):
        return "service"
    if any(token in text for token in ["sensor", "light", "switch.", "device_tracker"]):
        return "iot"
    return "other"
