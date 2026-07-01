from __future__ import annotations

from monitoring_center.monitor_types.base import normalize_timeout_config, timeout_seconds_from_config


def test_timeout_seconds_from_config_prefers_minutes() -> None:
    assert timeout_seconds_from_config({"timeout_minutes": 2, "timeout_seconds": 5}, 300) == 120


def test_timeout_seconds_from_config_accepts_seconds() -> None:
    assert timeout_seconds_from_config({"timeout_seconds": 12.5}, 300) == 12.5


def test_timeout_seconds_from_config_falls_back_to_default() -> None:
    assert timeout_seconds_from_config({"timeout_minutes": "nope"}, 300) == 300


def test_normalize_timeout_config_keeps_per_monitor_minutes() -> None:
    config = {"timeout_minutes": "0.5", "timeout_seconds": 10}

    normalize_timeout_config(config, default_seconds=300)

    assert config == {"timeout_minutes": 0.5}
