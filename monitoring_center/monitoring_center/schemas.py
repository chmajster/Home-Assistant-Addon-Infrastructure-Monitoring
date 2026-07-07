from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

DISCOVERY_SOURCES = {"home_assistant", "network", "docker", "unifi"}
TOPOLOGY_NODE_TYPES = {"internet", "router", "switch", "ap", "server", "iot", "service", "other"}


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


class DiscoveryScanIn(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["home_assistant"], max_length=4)
    network_cidr: str | None = Field(default=None, max_length=64)
    timeout_seconds: float = Field(default=3, gt=0, le=30)
    max_hosts: int = Field(default=64, ge=1, le=1024)

    def normalized_sources(self) -> list[str]:
        return [source for source in dict.fromkeys(self.sources) if source in DISCOVERY_SOURCES]


class DiscoveryImportMonitorIn(MonitorIn):
    confidence: float | None = None
    reason: str | None = None
    duplicate_of_monitor_id: int | None = None


class DiscoveryImportIn(BaseModel):
    monitors: list[DiscoveryImportMonitorIn] = Field(default_factory=list, max_length=1000)


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
    max_concurrent_checks: int = Field(ge=1, le=100)
    failure_threshold: int = Field(ge=1, le=20)
    recovery_threshold: int = Field(ge=1, le=20)
    retry_delay_seconds: int = Field(ge=0, le=3600)
    max_page_size_mb: float = Field(gt=0)
    block_private_networks: bool
    publish_home_assistant_entities: bool
    publish_home_assistant_events: bool
    entity_prefix: str = Field(min_length=1, max_length=64)


class TopologyNodeIn(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default="other", min_length=1, max_length=32)
    monitor_id: int | None = None
    icon: str | None = Field(default=None, max_length=64)
    x: float = 0
    y: float = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    def normalized_type(self) -> str:
        return self.type if self.type in TOPOLOGY_NODE_TYPES else "other"


class TopologyEdgeIn(BaseModel):
    id: int | None = None
    source_node_id: int
    target_node_id: int
    label: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TopologyIn(BaseModel):
    nodes: list[TopologyNodeIn] = Field(default_factory=list, max_length=500)
    edges: list[TopologyEdgeIn] = Field(default_factory=list, max_length=1000)
