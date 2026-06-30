from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_OPTIONS: dict[str, Any] = {
    "log_level": "info",
    "database_path": "/data/monitoring_center.db",
    "log_file": "/data/monitoring_center.log",
    "retention_days": 30,
    "default_device_interval": 60,
    "default_website_interval": 300,
    "default_timeout_minutes": 5,
    "max_page_size_mb": 5,
    "block_private_networks": False,
    "publish_home_assistant_entities": True,
    "publish_home_assistant_events": True,
    "entity_prefix": "monitoring_center",
}


@dataclass(slots=True)
class AppConfig:
    log_level: str
    database_path: Path
    log_file: Path
    retention_days: int
    default_device_interval: int
    default_website_interval: int
    default_timeout_minutes: float
    max_page_size_mb: float
    block_private_networks: bool
    publish_home_assistant_entities: bool
    publish_home_assistant_events: bool
    entity_prefix: str
    options_path: Path

    @classmethod
    def load(cls) -> "AppConfig":
        options_path = Path(os.environ.get("MONITORING_CENTER_OPTIONS", "/data/options.json"))
        data = DEFAULT_OPTIONS.copy()
        loaded: dict[str, Any] = {}
        if options_path.exists():
            with options_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
                if isinstance(raw, dict):
                    loaded = raw
                    data.update(loaded)

        if "default_timeout_minutes" not in loaded:
            timeout_seconds = data.get("request_timeout_seconds", data.get("ping_timeout_seconds", 300))
            data["default_timeout_minutes"] = max(_safe_float(timeout_seconds, 300) / 60, 1 / 60)
        if "max_page_size_mb" not in loaded:
            data["max_page_size_mb"] = max(_safe_float(data.get("max_page_size_kb", 512), 512) / 1024, 1 / 1024)

        return cls(
            log_level=str(data["log_level"]).lower(),
            database_path=Path(str(data["database_path"])),
            log_file=Path(str(data["log_file"])),
            retention_days=int(data["retention_days"]),
            default_device_interval=int(data["default_device_interval"]),
            default_website_interval=int(data["default_website_interval"]),
            default_timeout_minutes=float(data["default_timeout_minutes"]),
            max_page_size_mb=float(data["max_page_size_mb"]),
            block_private_networks=bool(data["block_private_networks"]),
            publish_home_assistant_entities=bool(data["publish_home_assistant_entities"]),
            publish_home_assistant_events=bool(data["publish_home_assistant_events"]),
            entity_prefix=str(data["entity_prefix"]),
            options_path=options_path,
        )


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
