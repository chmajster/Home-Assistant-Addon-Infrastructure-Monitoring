from __future__ import annotations

import asyncio

from monitoring_center.config import AppConfig
from monitoring_center.database import Database
from monitoring_center.monitor_types.ssh_command import SshCommandMonitor
from monitoring_center.monitoring import MonitorService


def test_ssh_command_status_priority() -> None:
    plugin = SshCommandMonitor()
    config = {
        "success_exit_codes": [0],
        "warning_exit_codes": [1],
        "error_exit_codes": [2],
        "success_stdout_regex": "active",
        "warning_stdout_regex": "degraded",
        "error_stderr_regex": "fatal",
    }

    assert plugin._status_from_regex(config, "active", "fatal") == "error"
    assert plugin._status_from_regex(config, "active degraded", "") == "warning"
    assert plugin._status_from_regex(config, "active", "") == "online"
    assert plugin._status_from_exit_code(config, 0) == "online"
    assert plugin._status_from_exit_code(config, 1) == "warning"
    assert plugin._status_from_exit_code(config, 2) == "error"


def test_ssh_command_validation_normalizes_timeouts(app_config: AppConfig) -> None:
    plugin = SshCommandMonitor()
    target, config = plugin.validate(
        "192.0.2.10:22",
        {
            "username": "root",
            "auth_method": "password",
            "connect_timeout_seconds": "7",
            "command_timeout_seconds": "11",
        },
        app_config,
    )

    assert target == "192.0.2.10:22"
    assert config["connect_timeout_seconds"] == 7
    assert config["command_timeout_seconds"] == 11


def test_monitor_api_masks_and_preserves_secrets(db: Database, app_config: AppConfig, ha_client: object) -> None:
    asyncio.run(_test_monitor_api_masks_and_preserves_secrets(db, app_config, ha_client))


async def _test_monitor_api_masks_and_preserves_secrets(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    created = await service.create_monitor(
        {
            "type": "ssh_command",
            "name": "SSH",
            "target": "192.0.2.10:22",
            "interval_seconds": 300,
            "test_on_save": False,
            "config": {
                "host": "192.0.2.10",
                "port": 22,
                "username": "root",
                "auth_method": "password",
                "password": "secret",
                "command": "true",
            },
        }
    )

    assert created["config"]["password"] == "********"
    monitor_id = int(created["id"])
    assert service.get_monitor(monitor_id)["config"]["password"] == "********"
    assert service.get_monitor(monitor_id, include_secrets=True)["config"]["password"] == "secret"

    updated = await service.update_monitor(
        monitor_id,
        {
            "config": {
                "host": "192.0.2.10",
                "port": 22,
                "username": "root",
                "auth_method": "password",
                "password": "",
                "command": "uptime",
            },
        },
    )

    assert updated["config"]["password"] == "********"
    internal = service.get_monitor(monitor_id, include_secrets=True)
    assert internal["config"]["password"] == "secret"
    assert internal["config"]["command"] == "uptime"


def test_event_payload_masks_secrets(db: Database, app_config: AppConfig, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monitor = {
        "id": None,
        "name": "Secret monitor",
        "type": "ssh_command",
        "target": "192.0.2.10:22",
        "config": {"severity": "critical"},
    }

    service._record_local_event(
        "monitor_alert",
        monitor,
        "online",
        "error",
        {"password": "secret", "private_key": "key", "severity": "critical"},
    )

    event = service.get_events()[0]
    assert event["payload"]["severity"] == "critical"
    assert event["payload"]["details"]["password"] == "********"
    assert event["payload"]["details"]["private_key"] == "********"
