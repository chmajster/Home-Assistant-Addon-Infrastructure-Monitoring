from __future__ import annotations

import asyncio

from monitoring_center.config import AppConfig
from monitoring_center.database import Database
from monitoring_center.monitor_types.base import CheckResult
from monitoring_center.monitoring import MonitorService


def test_failure_and_recovery_thresholds(db: Database, app_config: AppConfig, ha_client: object) -> None:
    asyncio.run(_test_failure_and_recovery_thresholds(db, app_config, ha_client))


async def _test_failure_and_recovery_thresholds(db: Database, app_config: AppConfig, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    created = await service.create_monitor(
        {
            "type": "ping_host",
            "name": "Router",
            "target": "127.0.0.1",
            "interval_seconds": 30,
            "test_on_save": False,
            "config": {"failure_threshold": 3, "recovery_threshold": 2},
        }
    )
    monitor_id = int(created["id"])
    results = [
        CheckResult("offline", error="drop 1"),
        CheckResult("offline", error="drop 2"),
        CheckResult("offline", error="drop 3"),
        CheckResult("online"),
        CheckResult("online"),
    ]

    async def fake_check(monitor: dict) -> CheckResult:
        return results.pop(0)

    service._check = fake_check  # type: ignore[method-assign]

    assert (await service.run_check(monitor_id))["status"] == "unknown"
    assert service.get_monitor(monitor_id)["failure_count"] == 1
    assert (await service.run_check(monitor_id))["status"] == "unknown"
    assert service.get_monitor(monitor_id)["failure_count"] == 2
    assert (await service.run_check(monitor_id))["status"] == "offline"
    assert service.get_monitor(monitor_id)["failure_count"] == 0
    assert (await service.run_check(monitor_id))["status"] == "offline"
    assert service.get_monitor(monitor_id)["recovery_count"] == 1
    assert (await service.run_check(monitor_id))["status"] == "online"
    assert service.get_monitor(monitor_id)["recovery_count"] == 0


def test_run_check_respects_concurrency_limit(db: Database, app_config: AppConfig, ha_client: object) -> None:
    asyncio.run(_test_run_check_respects_concurrency_limit(db, app_config, ha_client))


async def _test_run_check_respects_concurrency_limit(
    db: Database,
    app_config: AppConfig,
    ha_client: object,
) -> None:
    app_config.max_concurrent_checks = 1
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monitor_ids: list[int] = []
    for index in range(3):
        created = await service.create_monitor(
            {
                "type": "ping_host",
                "name": f"Host {index}",
                "target": "127.0.0.1",
                "interval_seconds": 30,
                "test_on_save": False,
                "config": {},
            }
        )
        monitor_ids.append(int(created["id"]))

    active = 0
    max_active = 0

    async def fake_run_check_now(monitor_id: int) -> dict:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return service.get_monitor(monitor_id)

    service._run_check_now = fake_run_check_now  # type: ignore[method-assign]

    await asyncio.gather(*(service.run_check(monitor_id) for monitor_id in monitor_ids))

    assert max_active == 1
