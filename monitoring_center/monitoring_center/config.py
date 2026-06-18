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
    "request_timeout_seconds": 10,
    "ping_timeout_seconds": 3,
    "max_page_size_kb": 512,
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
    request_timeout_seconds: int
    ping_timeout_seconds: int
    max_page_size_kb: int
    block_private_networks: bool
    publish_home_assistant_entities: bool
    publish_home_assistant_events: bool
    entity_prefix: str
    options_path: Path

    @classmethod
    def load(cls) -> "AppConfig":
        options_path = Path(os.environ.get("MONITORING_CENTER_OPTIONS", "/data/options.json"))
        data = DEFAULT_OPTIONS.copy()
        if options_path.exists():
            with options_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
                if isinstance(loaded, dict):
                    data.update(loaded)

        return cls(
            log_level=str(data["log_level"]).lower(),
            database_path=Path(str(data["database_path"])),
            log_file=Path(str(data["log_file"])),
            retention_days=int(data["retention_days"]),
            default_device_interval=int(data["default_device_interval"]),
            default_website_interval=int(data["default_website_interval"]),
            request_timeout_seconds=int(data["request_timeout_seconds"]),
            ping_timeout_seconds=int(data["ping_timeout_seconds"]),
            max_page_size_kb=int(data["max_page_size_kb"]),
            block_private_networks=bool(data["block_private_networks"]),
            publish_home_assistant_entities=bool(data["publish_home_assistant_entities"]),
            publish_home_assistant_events=bool(data["publish_home_assistant_events"]),
            entity_prefix=str(data["entity_prefix"]),
            options_path=options_path,
        )
