from __future__ import annotations

import asyncio
import difflib
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .config import AppConfig
from .database import Database, dumps_json, loads_json
from .ha import HomeAssistantClient
from .validators import ensure_public_url_if_required, validate_device_target, validate_url

LOGGER = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class CheckResult:
    status: str
    response_ms: float | None = None
    http_status: int | None = None
    packet_loss: float | None = None
    error: str | None = None
    content_changed: bool = False
    content_hash: str | None = None
    normalized_content: str | None = None
    raw_excerpt: str | None = None
    details: dict[str, Any] | None = None


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
            "type": current["type"],
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
            SET name = ?, target = ?, interval_seconds = ?, enabled = ?,
                config_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
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
            website_changed = monitor["type"] == "website" and result.content_changed
            last_changed_at = now if changed or website_changed else monitor.get("last_changed_at")

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
                    dumps_json(result.details or {}),
                ),
            )

            should_store_snapshot = (
                monitor["type"] == "website"
                and bool(result.normalized_content)
                and bool(result.content_hash)
                and (website_changed or not monitor.get("last_content_hash"))
            )
            if should_store_snapshot:
                self._store_snapshot(monitor, result)

            updated = self.get_monitor(monitor_id)
            updated["change_count"] = self._change_count(monitor_id)
            await self.ha.publish_monitor_state(updated)
            if changed:
                await self._record_event(
                    "monitor_online" if result.status in {"online", "ok"} else "monitor_offline",
                    updated,
                    previous_status,
                    result.status,
                )
            if website_changed:
                await self._record_event("website_changed", updated, previous_status, result.status)
            if result.error and monitor["type"] == "website":
                await self._record_event("website_error", updated, previous_status, result.status)
            return updated
        finally:
            self.running.discard(monitor_id)

    async def _check(self, monitor: dict[str, Any]) -> CheckResult:
        if monitor["type"] == "device":
            return await self._check_device(monitor)
        return await self._check_website(monitor)

    async def _check_device(self, monitor: dict[str, Any]) -> CheckResult:
        try:
            target = validate_device_target(monitor["target"])
            timeout = int(monitor["config"].get("timeout_seconds", self.config.ping_timeout_seconds))
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
                return CheckResult("online", response_ms=response_ms, packet_loss=packet_loss)
            return CheckResult(
                "offline",
                response_ms=None,
                packet_loss=packet_loss,
                error=_short_error(output) or "Ping failed",
            )
        except Exception as exc:
            return CheckResult("offline", error=str(exc), packet_loss=100.0)

    async def _check_website(self, monitor: dict[str, Any]) -> CheckResult:
        try:
            url = validate_url(monitor["target"])
            settings = self.get_settings()
            ensure_public_url_if_required(url, bool(settings["block_private_networks"]))
            timeout = float(monitor["config"].get("timeout_seconds", settings["request_timeout_seconds"]))
            max_bytes = int(monitor["config"].get("max_page_size_kb", settings["max_page_size_kb"])) * 1024
            started = time.perf_counter()
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=timeout,
                trust_env=False,
                headers={"User-Agent": "MonitoringCenter/0.1"},
            ) as client:
                async with client.stream("GET", url) as response:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise ValueError("Configured page size limit exceeded")
            elapsed_ms = (time.perf_counter() - started) * 1000
            text = bytes(body).decode(response.encoding or "utf-8", errors="replace")
            normalized = _normalize_content(text, monitor["config"])
            content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            content_changed = bool(monitor.get("last_content_hash") and monitor["last_content_hash"] != content_hash)
            status = "ok" if response.status_code < 400 else "error"
            return CheckResult(
                status=status,
                response_ms=elapsed_ms,
                http_status=response.status_code,
                content_changed=content_changed,
                content_hash=content_hash,
                normalized_content=normalized,
                raw_excerpt=text[:4000],
                error=None if status == "ok" else f"HTTP {response.status_code}",
                details={"final_url": str(response.url), "bytes": len(body)},
            )
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
    ) -> None:
        payload = {
            "monitor_id": monitor["id"],
            "monitor_name": monitor["name"],
            "monitor_type": monitor["type"],
            "target": monitor["target"],
            "previous_state": previous_state,
            "new_state": new_state,
            "created_at": utc_now(),
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
        recent_failures = [row for row in checks if row["status"] in {"offline", "error"}][:8]
        recent_changes = [row for row in checks if row["content_changed"]][:8]
        return {
            "total": len(monitors),
            "online": len([m for m in monitors if m["status"] in {"online", "ok"}]),
            "offline": len([m for m in monitors if m["status"] in {"offline", "error"}]),
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
            "version": "0.1.0",
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
        monitor_type = payload["type"]
        config = payload.get("config") or {}
        if monitor_type == "device":
            target = validate_device_target(payload["target"])
            default_interval = self.config.default_device_interval
        elif monitor_type == "website":
            target = validate_url(payload["target"])
            ensure_public_url_if_required(target, self.get_settings()["block_private_networks"])
            default_interval = self.config.default_website_interval
        else:
            raise ValueError("Unsupported monitor type")
        return {
            "type": monitor_type,
            "name": payload["name"].strip(),
            "target": target,
            "interval_seconds": int(payload.get("interval_seconds") or default_interval),
            "enabled": bool(payload.get("enabled", True)),
            "config": config,
        }

    @staticmethod
    def _hydrate_monitor(row: dict[str, Any]) -> dict[str, Any]:
        row["enabled"] = bool(row["enabled"])
        row["config"] = loads_json(row.pop("config_json", None), {})
        return row


def _normalize_content(html: str, config: dict[str, Any]) -> str:
    selector = str(config.get("css_selector") or "").strip()
    content = html
    if selector:
        soup = BeautifulSoup(html, "html.parser")
        selected = soup.select_one(selector)
        content = selected.get_text("\n", strip=True) if selected else ""
    else:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        content = soup.get_text("\n", strip=True)

    ignore_patterns = config.get("ignore_patterns") or []
    for pattern in ignore_patterns:
        try:
            content = re.sub(str(pattern), "", content, flags=re.MULTILINE)
        except re.error:
            LOGGER.warning("Ignoring invalid content regex: %s", pattern)
    content = re.sub(r"\s+", " ", content).strip()
    return content


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
