from __future__ import annotations

import asyncio

from monitoring_center import discovery
from monitoring_center.config import AppConfig
from monitoring_center.database import Database
from monitoring_center.monitoring import MonitorService


def test_discovery_finds_home_assistant_entities(db: Database, app_config: AppConfig, ha_client: object) -> None:
    asyncio.run(_test_discovery_finds_home_assistant_entities(db, app_config, ha_client))


async def _test_discovery_finds_home_assistant_entities(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
) -> None:
    ha_client.states = [  # type: ignore[attr-defined]
        {"entity_id": "sensor.nas_temperature", "state": "42", "attributes": {"friendly_name": "NAS Temperature"}},
        {"entity_id": "automation.ignore_me", "state": "on", "attributes": {}},
    ]
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]

    proposals = await service.scan_discovery(
        {"sources": ["home_assistant"], "timeout_seconds": 1, "max_hosts": 10}
    )

    assert len(proposals) == 1
    assert proposals[0]["type"] == "ha_entity"
    assert proposals[0]["target"] == "sensor.nas_temperature"
    assert proposals[0]["duplicate_of_monitor_id"] is None


def test_discovery_marks_duplicates(db: Database, app_config: AppConfig, ha_client: object) -> None:
    asyncio.run(_test_discovery_marks_duplicates(db, app_config, ha_client))


async def _test_discovery_marks_duplicates(db: Database, app_config: AppConfig, ha_client: object) -> None:
    ha_client.states = [{"entity_id": "sensor.router_status", "state": "ok", "attributes": {}}]  # type: ignore[attr-defined]
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    created = await service.create_monitor(
        {
            "type": "ha_entity",
            "name": "Router status",
            "target": "sensor.router_status",
            "interval_seconds": 60,
            "test_on_save": False,
            "config": {"alert_states": ["unavailable"]},
        }
    )

    proposals = await service.scan_discovery(
        {"sources": ["home_assistant"], "timeout_seconds": 1, "max_hosts": 10}
    )

    assert proposals[0]["duplicate_of_monitor_id"] == created["id"]


def test_discovery_import_creates_selected_proposals(db: Database, app_config: AppConfig, ha_client: object) -> None:
    asyncio.run(_test_discovery_import_creates_selected_proposals(db, app_config, ha_client))


async def _test_discovery_import_creates_selected_proposals(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]

    created = await service.import_discovery(
        [
            {
                "type": "ping_host",
                "name": "Router",
                "target": "192.168.1.1",
                "interval_seconds": 60,
                "group_id": None,
                "enabled": True,
                "config": {},
                "confidence": 0.7,
                "reason": "test",
            }
        ]
    )

    assert len(created) == 1
    assert service.list_monitors()[0]["name"] == "Router"


def test_network_discovery_respects_max_hosts(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    asyncio.run(_test_network_discovery_respects_max_hosts(db, app_config, ha_client, monkeypatch))


async def _test_network_discovery_respects_max_hosts(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    scanned_hosts: list[str] = []

    async def fake_ping(host: str, timeout: float) -> bool:
        scanned_hosts.append(host)
        return True

    async def fake_port_open(host: str, port: int, timeout: float) -> bool:
        return False

    monkeypatch.setattr(discovery, "_ping_host", fake_ping)
    monkeypatch.setattr(discovery, "_port_open", fake_port_open)
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]

    proposals = await service.scan_discovery(
        {
            "sources": ["network"],
            "network_cidr": "192.168.50.0/29",
            "timeout_seconds": 1,
            "max_hosts": 3,
        }
    )

    assert scanned_hosts == ["192.168.50.1", "192.168.50.2", "192.168.50.3"]
    assert len([proposal for proposal in proposals if proposal["type"] == "ping_host"]) == 3
