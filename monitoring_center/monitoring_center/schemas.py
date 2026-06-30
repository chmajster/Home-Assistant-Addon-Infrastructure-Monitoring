from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MonitorIn(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=2048)
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    group_id: int | None = None
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    test_on_save: bool = True


class MonitorUpdate(BaseModel):
    type: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target: str | None = Field(default=None, min_length=1, max_length=2048)
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    group_id: int | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    test_on_save: bool = False


class MonitorsImportIn(BaseModel):
    monitors: list[MonitorIn] = Field(default_factory=list, max_length=1000)


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    color: str = Field(default="#0f766e", min_length=4, max_length=16)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    color: str | None = Field(default=None, min_length=4, max_length=16)


class MaintenanceIn(BaseModel):
    duration_minutes: int | None = Field(default=None, ge=1, le=525600)
    until: str | None = None
    reason: str | None = Field(default=None, max_length=500)


class SettingsIn(BaseModel):
    retention_days: int = Field(ge=1, le=3650)
    default_interval_seconds: int = Field(ge=5, le=86400)
    default_timeout_minutes: float = Field(gt=0)
    max_page_size_mb: float = Field(gt=0)
    block_private_networks: bool
    publish_home_assistant_entities: bool
    publish_home_assistant_events: bool
    entity_prefix: str = Field(min_length=1, max_length=64)
