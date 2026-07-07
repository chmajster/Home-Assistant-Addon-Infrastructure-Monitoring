from __future__ import annotations

from fastapi.testclient import TestClient

from monitoring_center.config import AppConfig
from monitoring_center.database import Database
from monitoring_center.monitoring import MonitorService


def test_topology_api_roundtrip_and_monitor_status(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    from monitoring_center import main as app_main

    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monitor_id = service._insert_monitor(
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
    db.execute("UPDATE monitors SET status = 'online' WHERE id = ?", (monitor_id,))
    monkeypatch.setattr(app_main, "service", service)

    payload = {
        "nodes": [
            {"id": 1, "name": "Internet", "type": "internet", "x": 10, "y": 20, "metadata": {}},
            {
                "id": 2,
                "name": "Router",
                "type": "router",
                "monitor_id": monitor_id,
                "x": 180,
                "y": 20,
                "metadata": {},
            },
        ],
        "edges": [{"source_node_id": 1, "target_node_id": 2, "label": "WAN", "metadata": {}}],
    }

    client = TestClient(app_main.app)
    saved = client.put("/api/topology", json=payload).json()
    loaded = client.get("/api/topology").json()

    service.stop()

    assert len(saved["nodes"]) == 2
    assert loaded["nodes"][1]["status"] == "online"
    assert loaded["nodes"][1]["monitor"]["id"] == monitor_id
    assert loaded["edges"][0]["label"] == "WAN"


def test_topology_auto_layout_seeds_simple_map(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    from monitoring_center import main as app_main

    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    service._insert_monitor(
        {
            "type": "ping_host",
            "name": "NAS",
            "target": "192.168.1.50",
            "interval_seconds": 60,
            "group_id": None,
            "enabled": True,
            "config": {},
        }
    )
    monkeypatch.setattr(app_main, "service", service)

    client = TestClient(app_main.app)
    topology = client.post("/api/topology/auto-layout").json()

    service.stop()

    names = {node["name"] for node in topology["nodes"]}
    assert {"Internet", "Router", "NAS"} <= names
    assert topology["edges"]
