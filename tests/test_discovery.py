from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from monitoring_center import discovery
from monitoring_center.config import AppConfig
from monitoring_center.database import Database
from monitoring_center.monitoring import MonitorService


def test_discovery_scan_api_returns_structured_source_report(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    from monitoring_center import main as app_main

    ha_client.states = []  # type: ignore[attr-defined]
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monkeypatch.setattr(app_main, "service", service)

    response = TestClient(app_main.app).post(
        "/api/discovery/scan",
        json={"sources": ["home_assistant"], "timeout_seconds": 1, "max_hosts": 10},
    )
    body = response.json()
    service.stop()

    assert response.status_code == 200
    assert body["proposals"] == []
    assert body["sources"][0]["source"] == "home_assistant"
    assert body["sources"][0]["status"] == "empty"
    assert body["summary"]["completed_sources"] == 1


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

    result = await service.scan_discovery({"sources": ["home_assistant"], "timeout_seconds": 1, "max_hosts": 10})
    proposals = result["proposals"]

    assert len(proposals) == 1
    assert proposals[0]["type"] == "ha_entity"
    assert proposals[0]["target"] == "sensor.nas_temperature"
    assert proposals[0]["duplicate_of_monitor_id"] is None
    assert result["sources"][0]["status"] == "success"
    assert result["sources"][0]["found"] == 1


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

    result = await service.scan_discovery({"sources": ["home_assistant"], "timeout_seconds": 1, "max_hosts": 10})
    proposals = result["proposals"]

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

    async def fake_hostname(host: str, timeout: float) -> str | None:
        return f"host-{host.rsplit('.', 1)[-1]}.local"

    async def fake_mac(host: str, timeout: float) -> str | None:
        return "B8:27:EB:00:00:01"

    monkeypatch.setattr(discovery, "_ping_host", fake_ping)
    monkeypatch.setattr(discovery, "_port_open", fake_port_open)
    monkeypatch.setattr(discovery, "_reverse_hostname", fake_hostname)
    monkeypatch.setattr(discovery, "_neighbor_mac", fake_mac)
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]

    result = await service.scan_discovery(
        {
            "sources": ["network"],
            "network_cidr": "192.168.50.0/29",
            "timeout_seconds": 1,
            "max_hosts": 3,
        }
    )
    proposals = result["proposals"]

    assert scanned_hosts == ["192.168.50.1", "192.168.50.2", "192.168.50.3"]
    assert len([proposal for proposal in proposals if proposal["type"] == "ping_host"]) == 3
    assert proposals[0]["hostname"] == "host-1.local"
    assert proposals[0]["vendor"] == "Raspberry Pi"
    assert proposals[0]["device_kind"] == "server"
    assert proposals[0]["icon"] == "🖥️"


def test_network_identity_classifies_popular_devices() -> None:
    assert discovery._infer_device_kind("diskstation.local", "Synology", "nas", [80]) == "nas"
    assert discovery._infer_device_kind("front-camera.local", None, None, [80]) == "camera"
    assert discovery._infer_device_kind(None, "Ubiquiti", "access_point", [443]) == "access_point"
    assert discovery._infer_device_kind(None, None, None, [8123]) == "server"
    assert discovery._vendor_hint("00:11:32:AA:BB:CC") == ("Synology", "nas")


def test_port_22_is_proposed_as_live_ssh_probe() -> None:
    proposal = discovery._port_proposal("192.168.1.10", 22, "nas.local")
    assert proposal.name == "SSH nas.local"
    assert proposal.type == "tcp_port"
    assert proposal.config == {"host": "192.168.1.10", "port": 22}
    assert "banner" in proposal.reason


def test_tcp_monitor_reads_ssh_banner(
    db: Database, app_config: AppConfig, ha_client: object, monkeypatch
) -> None:
    async def run() -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(b"SSH-2.0-OpenSSH_test\r\n")
        reader.feed_eof()

        class Writer:
            def close(self) -> None:
                pass

            async def wait_closed(self) -> None:
                pass

        async def fake_open_connection(host: str, port: int):
            assert (host, port) == ("127.0.0.1", 22)
            return reader, Writer()

        monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)
        service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
        result = await service.test_monitor(
            {
                "type": "tcp_port",
                "name": "SSH test",
                "target": "127.0.0.1:22",
                "interval_seconds": 60,
                "config": {"host": "127.0.0.1", "port": 22},
            }
        )
        assert result["details"]["protocol"] == "ssh"
        assert result["details"]["banner"].startswith("SSH-2.0-")

    asyncio.run(run())


def test_discovery_reports_source_errors_without_losing_other_results(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
) -> None:
    asyncio.run(_test_discovery_reports_source_errors_without_losing_other_results(db, app_config, ha_client))


async def _test_discovery_reports_source_errors_without_losing_other_results(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
) -> None:
    ha_client.states = [{"entity_id": "sensor.available", "state": "ok", "attributes": {}}]  # type: ignore[attr-defined]
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]

    result = await service.scan_discovery(
        {
            "sources": ["home_assistant", "network"],
            "network_cidr": "invalid-cidr",
            "timeout_seconds": 1,
            "max_hosts": 10,
        }
    )

    assert len(result["proposals"]) == 1
    assert {source["source"]: source["status"] for source in result["sources"]} == {
        "home_assistant": "success",
        "network": "error",
    }
    network = next(source for source in result["sources"] if source["source"] == "network")
    assert "CIDR" in network["message"]
    assert result["summary"]["failed_sources"] == 1


def test_discovery_reports_home_assistant_failure(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
) -> None:
    asyncio.run(_test_discovery_reports_home_assistant_failure(db, app_config, ha_client))


async def _test_discovery_reports_home_assistant_failure(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
) -> None:
    async def failing_states(timeout: float = 10.0) -> list[dict]:
        raise RuntimeError("Home Assistant API unavailable")

    ha_client.list_states = failing_states  # type: ignore[attr-defined]
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]

    result = await service.scan_discovery({"sources": ["home_assistant"], "timeout_seconds": 1})

    assert result["proposals"] == []
    assert result["sources"][0]["status"] == "error"
    assert "Home Assistant API unavailable" in result["sources"][0]["message"]


def test_discovery_reports_sources_without_configuration_as_skipped(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
) -> None:
    asyncio.run(_test_discovery_reports_sources_without_configuration_as_skipped(db, app_config, ha_client))


async def _test_discovery_reports_sources_without_configuration_as_skipped(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]

    result = await service.scan_discovery({"sources": ["docker", "unifi"], "timeout_seconds": 1})

    assert [source["status"] for source in result["sources"]] == ["skipped", "skipped"]
    assert all(source["message"] for source in result["sources"])
    assert result["summary"]["skipped_sources"] == 2


def test_discovery_reports_source_timeout(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    asyncio.run(_test_discovery_reports_source_timeout(db, app_config, ha_client, monkeypatch))


async def _test_discovery_reports_source_timeout(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]

    async def slow_source(timeout: float) -> list:
        await asyncio.sleep(1)
        return []

    monkeypatch.setattr(service.discovery, "_scan_home_assistant", slow_source)
    result = await service.scan_discovery(
        {"sources": ["home_assistant"], "timeout_seconds": 1, "total_timeout_seconds": 0.01}
    )

    assert result["sources"][0]["status"] == "error"
    assert "limit czasu" in result["sources"][0]["message"]


def test_network_discovery_reports_host_scanner_failure(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    asyncio.run(_test_network_discovery_reports_host_scanner_failure(db, app_config, ha_client, monkeypatch))


async def _test_network_discovery_reports_host_scanner_failure(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    async def failing_ping(host: str, timeout: float) -> bool:
        raise RuntimeError("ping unavailable")

    monkeypatch.setattr(discovery, "_ping_host", failing_ping)
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]

    result = await service.scan_discovery(
        {
            "sources": ["network"],
            "network_cidr": "192.168.50.0/30",
            "timeout_seconds": 1,
            "max_hosts": 2,
        }
    )

    assert result["proposals"] == []
    assert result["sources"][0]["status"] == "error"
    assert "żadnego hosta" in result["sources"][0]["message"]
