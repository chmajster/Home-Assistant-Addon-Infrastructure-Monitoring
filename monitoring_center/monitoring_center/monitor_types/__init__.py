from __future__ import annotations

from typing import Any

from .base import MonitorTypePlugin
from .dns_lookup import DnsLookupMonitor
from .ha_entity import HomeAssistantEntityMonitor
from .http import HttpHashMonitor, HttpStatusMonitor
from .mqtt import MqttMonitor
from .ping import PingHostMonitor
from .rest_api import RestApiMonitor
from .ssl_certificate import SslCertificateMonitor
from .tcp import TcpPortMonitor

PLUGINS: dict[str, MonitorTypePlugin] = {
    plugin.type: plugin
    for plugin in [
        PingHostMonitor(),
        TcpPortMonitor(),
        HttpStatusMonitor(),
        HttpHashMonitor(),
        DnsLookupMonitor(),
        SslCertificateMonitor(),
        RestApiMonitor(),
        HomeAssistantEntityMonitor(),
        MqttMonitor(),
    ]
}

LEGACY_TYPE_MAP = {
    "device": "ping_host",
    "www": "http_hash",
    "website": "http_hash",
}


PRESETS: list[dict[str, Any]] = [
    {
        "name": "Router - ping gateway",
        "type": "ping_host",
        "target": "192.168.1.1",
        "interval_seconds": 60,
        "config": {},
    },
    {
        "name": "Home Assistant - port 8123",
        "type": "tcp_port",
        "target": "192.168.1.40:8123",
        "interval_seconds": 60,
        "config": {"host": "192.168.1.40", "port": 8123},
    },
    {
        "name": "NAS - ping",
        "type": "ping_host",
        "target": "192.168.1.50",
        "interval_seconds": 60,
        "config": {},
    },
    {
        "name": "NAS - SMB 445",
        "type": "tcp_port",
        "target": "192.168.1.50:445",
        "interval_seconds": 60,
        "config": {"host": "192.168.1.50", "port": 445},
    },
    {
        "name": "SSH server - port 22",
        "type": "tcp_port",
        "target": "192.168.1.10:22",
        "interval_seconds": 60,
        "config": {"host": "192.168.1.10", "port": 22},
    },
    {
        "name": "Strona WWW - status i hash",
        "type": "http_hash",
        "target": "https://example.com",
        "interval_seconds": 300,
        "config": {"expected_status_codes": [200], "max_page_size_mb": 5},
    },
    {
        "name": "SSL domeny - certyfikat HTTPS",
        "type": "ssl_certificate",
        "target": "example.com:443",
        "interval_seconds": 21600,
        "config": {"host": "example.com", "port": 443, "warning_days": 30, "error_days": 7},
    },
    {
        "name": "DNS domeny - rekord A/AAAA",
        "type": "dns_lookup",
        "target": "example.com",
        "interval_seconds": 300,
        "config": {"record_type": "A"},
    },
]


def resolve_type(monitor_type: str) -> str:
    return LEGACY_TYPE_MAP.get(monitor_type, monitor_type)


def get_plugin(monitor_type: str) -> MonitorTypePlugin:
    resolved = resolve_type(monitor_type)
    if resolved not in PLUGINS:
        raise KeyError(monitor_type)
    return PLUGINS[resolved]


def list_types() -> list[dict[str, Any]]:
    return [
        {
            "type": plugin.type,
            "label": plugin.label,
            "category": plugin.category,
            "default_interval": plugin.default_interval,
        }
        for plugin in PLUGINS.values()
    ]
