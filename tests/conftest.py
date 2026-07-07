from __future__ import annotations

from pathlib import Path

import pytest

from monitoring_center.config import AppConfig
from monitoring_center.database import Database
from monitoring_center.migrations import migrate


class DummyHomeAssistant:
    def __init__(self) -> None:
        self.states: list[dict] = []

    async def list_states(self, timeout: float = 10.0) -> list[dict]:
        return self.states

    async def get_api_status(self, timeout: float = 5.0) -> dict:
        return {"ok": True, "available": True, "status_code": 200}

    async def publish_monitor_state(self, monitor: dict) -> None:
        return None

    async def fire_event(self, event_type: str, payload: dict) -> bool:
        return False

    async def publish_test_state(self, entity_id: str, state: object, attributes: dict) -> bool:
        return True


@pytest.fixture
def ha_client() -> DummyHomeAssistant:
    return DummyHomeAssistant()


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        log_level="debug",
        database_path=tmp_path / "monitoring_center.db",
        log_file=tmp_path / "monitoring_center.log",
        retention_days=30,
        default_interval_seconds=300,
        default_device_interval=60,
        default_website_interval=300,
        default_timeout_minutes=5,
        max_concurrent_checks=2,
        failure_threshold=3,
        recovery_threshold=2,
        retry_delay_seconds=10,
        max_page_size_mb=5,
        block_private_networks=False,
        publish_home_assistant_entities=False,
        publish_home_assistant_events=False,
        entity_prefix="monitoring_center",
        options_path=tmp_path / "options.json",
    )


@pytest.fixture
def db(app_config: AppConfig) -> Database:
    database = Database(app_config.database_path)
    migrate(database)
    try:
        yield database
    finally:
        database.close()
