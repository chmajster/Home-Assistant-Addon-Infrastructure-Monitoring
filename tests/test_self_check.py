from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient

from monitoring_center.config import AppConfig
from monitoring_center.database import Database
from monitoring_center.monitor_types import get_plugin
from monitoring_center.monitor_types import self_check as self_check_module
from monitoring_center.monitor_types.base import MonitorContext
from monitoring_center.monitoring import MonitorService


def test_diagnostics_full_api(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    from monitoring_center import main as app_main

    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monkeypatch.setattr(app_main, "config", app_config)
    monkeypatch.setattr(app_main, "service", service)

    client = TestClient(app_main.app)
    body = client.get("/api/diagnostics/full").json()

    service.stop()

    assert body["ready"]["database"] is True
    assert body["ready"]["data_dir_writable"] is True
    assert body["addon_version"]
    assert body["schema_version"] >= 1
    assert body["process"]["python_version"]
    assert "home_assistant_api" in body
    assert "data_writable" in body
    assert "log_file_status" in body


def test_self_check_records_event_and_sanitizes_payload(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
    monkeypatch,
) -> None:
    from monitoring_center import main as app_main

    async def fake_api_status(timeout: float = 5.0) -> dict[str, Any]:
        return {
            "name": "home_assistant_api",
            "ok": False,
            "available": True,
            "password": "super-secret",
            "token": "abc123",
        }

    ha_client.get_api_status = fake_api_status  # type: ignore[attr-defined]
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monkeypatch.setattr(app_main, "config", app_config)
    monkeypatch.setattr(app_main, "service", service)

    client = TestClient(app_main.app)
    body = client.post("/api/diagnostics/self-check").json()
    events = service.get_events()

    service.stop()

    assert body["status"] == "error"
    assert any(check["name"] == "sqlite_read_write" and check["ok"] for check in body["checks"])
    assert events[0]["event_type"] == "diagnostics_self_check"
    payload = events[0]["payload"]
    ha_check = next(check for check in payload["checks"] if check["name"] == "home_assistant_api")
    assert ha_check["password"] == "********"
    assert ha_check["token"] == "********"


def test_monitoring_center_health_monitor_type(
    app_config: AppConfig,
    monkeypatch,
) -> None:
    asyncio.run(_test_monitoring_center_health_monitor_type(app_config, monkeypatch))


async def _test_monitoring_center_health_monitor_type(app_config: AppConfig, monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "scheduler_running": True,
                "database_exists": True,
                "data_writable": {"ok": True},
                "home_assistant_api": {"ok": True, "available": True},
                "log_file_status": {"writable": True},
                "scheduler_error_count": 0,
            }

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(self_check_module.httpx, "AsyncClient", FakeClient)
    plugin = get_plugin("monitoring_center_health")
    result = await plugin.check(
        {"config": {}, "target": "self"},
        MonitorContext(config=app_config, settings={}, ha=None),  # type: ignore[arg-type]
    )

    assert result.status == "online"
    assert result.details["checks"]["database"] is True
