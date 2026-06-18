from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MonitorType = Literal["device", "website"]


class MonitorIn(BaseModel):
    type: MonitorType
    name: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=2048)
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    test_on_save: bool = True


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target: str | None = Field(default=None, min_length=1, max_length=2048)
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    test_on_save: bool = False


class SettingsIn(BaseModel):
    retention_days: int = Field(ge=1, le=3650)
    request_timeout_seconds: int = Field(ge=1, le=120)
    ping_timeout_seconds: int = Field(ge=1, le=30)
    max_page_size_kb: int = Field(ge=16, le=10240)
    block_private_networks: bool
    publish_home_assistant_entities: bool
    publish_home_assistant_events: bool
    entity_prefix: str = Field(min_length=1, max_length=64)
