from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..config import AppConfig
from ..ha import HomeAssistantClient


@dataclass(slots=True)
class MonitorContext:
    config: AppConfig
    settings: dict[str, Any]
    ha: HomeAssistantClient


@dataclass(slots=True)
class CheckResult:
    status: str
    response_ms: float | None = None
    http_status: int | None = None
    packet_loss: float | None = None
    error: str | None = None
    content_changed: bool = False
    content_hash: str | None = None
    normalized_content: str | None = None
    raw_excerpt: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)


class MonitorTypePlugin(Protocol):
    type: str
    label: str
    category: str
    default_interval: int

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        ...

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        ...


def positive_int(value: Any, default: int, minimum: int = 1, maximum: int = 65535) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def positive_float(value: Any, default: float, minimum: float = 0.1, maximum: float = 300.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def csv_ints(value: Any, default: list[int]) -> list[int]:
    if value is None or value == "":
        return default
    if isinstance(value, list):
        source = value
    else:
        source = str(value).split(",")
    result: list[int] = []
    for item in source:
        try:
            result.append(int(str(item).strip()))
        except ValueError:
            continue
    return result or default


def is_success_status(status: str) -> bool:
    return status in {"online", "ok", "open", "warning"}
