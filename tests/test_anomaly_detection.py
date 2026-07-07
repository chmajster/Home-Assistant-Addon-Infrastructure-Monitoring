from __future__ import annotations

import asyncio

from monitoring_center.database import Database, dumps_json, loads_json
from monitoring_center.monitor_types.base import CheckResult
from monitoring_center.monitoring import MonitorService, utc_now


def test_baseline_from_response_history(db: Database, app_config, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monitor_id = service._insert_monitor(_monitor_payload())
    for value in [100, 110, 90, 100, 105]:
        _insert_check(db, monitor_id, response_ms=value)

    baseline = service.metric_baseline(monitor_id, "response_ms", window_hours=24, min_samples=5)

    assert baseline is not None
    assert baseline["mean"] == 101
    assert baseline["median"] == 100
    assert baseline["sample_count"] == 5


def test_anomaly_detection_marks_response_spike(db: Database, app_config, ha_client: object) -> None:
    asyncio.run(_test_anomaly_detection_marks_response_spike(db, app_config, ha_client))


async def _test_anomaly_detection_marks_response_spike(db: Database, app_config, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monitor_id = service._insert_monitor(
        _monitor_payload(
            {
                "anomaly_detection_enabled": True,
                "anomaly_min_samples": 4,
                "anomaly_warn_percent_over_baseline": 25,
                "anomaly_error_percent_over_baseline": 80,
                "failure_threshold": 1,
            }
        )
    )
    for value in [100, 102, 98, 100]:
        _insert_check(db, monitor_id, response_ms=value)

    async def fake_check(monitor: dict) -> CheckResult:
        return CheckResult("online", response_ms=220, details={})

    service._check = fake_check  # type: ignore[method-assign]
    updated = await service.run_check(monitor_id)

    assert updated["status"] == "error"
    check = db.fetchone("SELECT details_json FROM monitor_checks WHERE monitor_id = ? ORDER BY id DESC", (monitor_id,))
    details = loads_json(check["details_json"], {})  # type: ignore[index]
    assert details["anomaly_metric"] == "response_ms"
    assert details["anomaly_reason"]
    assert "monitor_anomaly_detected" in [event["event_type"] for event in service.get_events()]


def test_anomaly_detection_requires_min_samples(db: Database, app_config, ha_client: object) -> None:
    asyncio.run(_test_anomaly_detection_requires_min_samples(db, app_config, ha_client))


async def _test_anomaly_detection_requires_min_samples(db: Database, app_config, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monitor_id = service._insert_monitor(
        _monitor_payload({"anomaly_detection_enabled": True, "anomaly_min_samples": 5})
    )
    for value in [100, 101]:
        _insert_check(db, monitor_id, response_ms=value)

    async def fake_check(monitor: dict) -> CheckResult:
        return CheckResult("online", response_ms=300, details={})

    service._check = fake_check  # type: ignore[method-assign]
    updated = await service.run_check(monitor_id)

    assert updated["status"] == "online"
    check = db.fetchone("SELECT details_json FROM monitor_checks WHERE monitor_id = ? ORDER BY id DESC", (monitor_id,))
    details = loads_json(check["details_json"], {})  # type: ignore[index]
    assert "anomaly_reason" not in details


def test_anomaly_details_are_sanitized(db: Database, app_config, ha_client: object) -> None:
    asyncio.run(_test_anomaly_details_are_sanitized(db, app_config, ha_client))


async def _test_anomaly_details_are_sanitized(db: Database, app_config, ha_client: object) -> None:
    service = MonitorService(db, app_config, ha_client)  # type: ignore[arg-type]
    monitor_id = service._insert_monitor(
        _monitor_payload({"anomaly_detection_enabled": True, "anomaly_min_samples": 2})
    )
    for value in [10, 11]:
        _insert_check(db, monitor_id, response_ms=value)

    async def fake_check(monitor: dict) -> CheckResult:
        return CheckResult("online", response_ms=100, details={"password": "secret-value"})

    service._check = fake_check  # type: ignore[method-assign]
    await service.run_check(monitor_id)

    check = db.fetchone("SELECT details_json FROM monitor_checks WHERE monitor_id = ? ORDER BY id DESC", (monitor_id,))
    details = loads_json(check["details_json"], {})  # type: ignore[index]
    assert details["password"] == "********"
    assert details["anomaly_reason"]


def _monitor_payload(config: dict | None = None) -> dict:
    return {
        "type": "ping_host",
        "name": "Router",
        "target": "127.0.0.1",
        "interval_seconds": 60,
        "group_id": None,
        "enabled": True,
        "config": config or {},
    }


def _insert_check(db: Database, monitor_id: int, *, response_ms: float, details: dict | None = None) -> None:
    db.execute(
        """
        INSERT INTO monitor_checks(
            monitor_id, checked_at, status, response_ms, details_json
        ) VALUES (?, ?, 'online', ?, ?)
        """,
        (monitor_id, utc_now(), response_ms, dumps_json(details or {})),
    )
