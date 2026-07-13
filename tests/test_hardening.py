from __future__ import annotations

import asyncio
from pathlib import Path

from monitoring_center.database import Database, dumps_json
from monitoring_center.ha import HomeAssistantClient, get_supervisor_token
from monitoring_center.monitoring import MonitorService
from monitoring_center.security import MASKED_SECRET


def test_supervisor_token_uses_current_environment(monkeypatch: object) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", " current-token ")  # type: ignore[attr-defined]
    monkeypatch.setenv("HASSIO_TOKEN", "legacy-token")  # type: ignore[attr-defined]
    assert get_supervisor_token() == "current-token"


def test_supervisor_token_supports_legacy_environment(monkeypatch: object) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)  # type: ignore[attr-defined]
    monkeypatch.setenv("HASSIO_TOKEN", "legacy-token")  # type: ignore[attr-defined]
    assert get_supervisor_token() == "legacy-token"


def test_plaintext_secrets_are_migrated_and_absent_from_database_and_backup(
    db: Database, app_config: object, ha_client: object, tmp_path: Path
) -> None:
    marker = "characteristic-secret-7d08d4"
    cursor = db.execute(
        """INSERT INTO monitors(type,name,target,interval_seconds,config_json)
           VALUES ('ssh_command','SSH','server.local',60,?)""",
        (dumps_json({"username": "operator", "password": marker}),),
    )
    monitor_id = int(cursor.lastrowid)
    db.execute("INSERT INTO monitor_runtime(monitor_id) VALUES (?)", (monitor_id,))
    db.execute("INSERT INTO scheduler_state(monitor_id,next_check_at) VALUES (?,datetime('now'))", (monitor_id,))

    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    backup = tmp_path / "safe.sqlite"
    db.checkpoint(truncate=True)
    db.backup(backup)

    assert service.get_monitor(monitor_id)["config"]["password"] == MASKED_SECRET
    assert service.get_monitor(monitor_id, include_secrets=True)["config"]["password"] == marker
    for path in (db.path, db.path.with_name(f"{db.path.name}-wal"), backup, app_config.log_file):  # type: ignore[attr-defined]
        if path.exists():
            assert marker.encode() not in path.read_bytes()


def test_scheduler_keeps_due_time_across_service_restart(db: Database, app_config: object, ha_client: object) -> None:
    first = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monitor_id = first._insert_monitor(
        {
            "type": "ping_host",
            "name": "Router",
            "target": "192.168.1.1",
            "interval_seconds": 60,
            "group_id": None,
            "enabled": True,
            "config": {},
        }
    )
    db.execute("UPDATE scheduler_state SET next_check_at=datetime('now','+1 hour') WHERE monitor_id=?", (monitor_id,))
    before = db.fetchone("SELECT next_check_at FROM scheduler_state WHERE monitor_id=?", (monitor_id,))
    second = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    after = db.fetchone("SELECT next_check_at FROM scheduler_state WHERE monitor_id=?", (monitor_id,))
    asyncio.run(second._tick())
    assert before == after
    assert monitor_id not in second.running


def test_cursor_page_has_stable_next_cursor(db: Database, app_config: object, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monitor_id = service._insert_monitor(
        {
            "type": "ping_host",
            "name": "Host",
            "target": "192.0.2.10",
            "interval_seconds": 60,
            "group_id": None,
            "enabled": True,
            "config": {},
        }
    )
    for _ in range(3):
        db.execute("INSERT INTO monitor_checks(monitor_id,status) VALUES (?,'online')", (monitor_id,))
    first = service.get_cursor_page("history", 2, monitor_id=monitor_id)
    second = service.get_cursor_page("history", 2, first["pagination"]["next_cursor"], monitor_id=monitor_id)
    assert first["pagination"] == {
        "limit": 2,
        "next_cursor": str(first["items"][-1]["id"]),
        "has_more": True,
        "total": 3,
    }
    assert len(second["items"]) == 1
    assert {row["id"] for row in first["items"]}.isdisjoint(row["id"] for row in second["items"])


def test_home_assistant_entity_ids_do_not_depend_on_name(app_config: object) -> None:
    async def run() -> None:
        client = HomeAssistantClient(app_config)  # type: ignore[arg-type]
        client.token = "test"
        captured: list[str] = []

        async def capture(entity_id: str, state: object, attributes: dict[str, object]) -> None:
            captured.append(entity_id)

        client._set_state = capture  # type: ignore[method-assign]
        base = {"id": 15, "type": "ping_host", "target": "router.local", "status": "online", "config": {}}
        await client.publish_monitor_state({**base, "name": "Router"})
        first = set(captured)
        captured.clear()
        await client.publish_monitor_state({**base, "name": "Nowa nazwa"})
        assert first == set(captured)
        assert "binary_sensor.monitoring_center_15_status" in first
        await client.close()

    app_config.publish_home_assistant_entities = True  # type: ignore[attr-defined]
    asyncio.run(run())


def test_topology_upsert_preserves_ids(db: Database, app_config: object, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    initial = service.save_topology({"nodes": [{"id": -1, "name": "Router", "type": "router"}], "edges": []})
    node_id = initial["nodes"][0]["id"]
    updated = service.save_topology(
        {
            "version": initial["version"],
            "nodes": [{"id": node_id, "name": "Router główny", "type": "router"}],
            "edges": [],
        }
    )
    assert updated["nodes"][0]["id"] == node_id
    assert updated["version"] == initial["version"] + 1


def test_topology_identifies_parent_root_cause(db: Database, app_config: object, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    parent = service._insert_monitor(
        {
            "type": "ping_host",
            "name": "Router",
            "target": "192.168.1.1",
            "interval_seconds": 60,
            "group_id": None,
            "enabled": True,
            "config": {},
        }
    )
    child = service._insert_monitor(
        {
            "type": "tcp_port",
            "name": "NAS",
            "target": "192.168.1.2:443",
            "interval_seconds": 60,
            "group_id": None,
            "enabled": True,
            "config": {"host": "192.168.1.2", "port": 443},
        }
    )
    db.execute("UPDATE monitors SET status='offline' WHERE id=?", (parent,))
    topology = service.save_topology(
        {
            "nodes": [
                {"id": -1, "name": "Router", "type": "router", "monitor_id": parent},
                {"id": -2, "name": "NAS", "type": "server", "monitor_id": child},
            ],
            "edges": [],
        }
    )
    service.save_topology(
        {
            "version": topology["version"],
            "nodes": topology["nodes"],
            "edges": [{"source_node_id": topology["nodes"][0]["id"], "target_node_id": topology["nodes"][1]["id"]}],
        }
    )
    cause = service._root_cause_for_monitor(child)
    assert cause and cause["monitor_id"] == parent
    assert cause["affected_count"] == 2
