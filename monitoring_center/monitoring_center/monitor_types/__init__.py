from __future__ import annotations

from typing import Any

from .base import MonitorTypePlugin
from .dns_lookup import DnsLookupMonitor
from .ha_entity import HomeAssistantEntityMonitor
from .http import HttpHashMonitor, HttpStatusMonitor
from .integrations import (
    HomeAssistantHealthMonitor,
    PiHoleHealthMonitor,
    SnmpInterfaceMonitor,
    SnmpOidMonitor,
    UniFiDeviceMonitor,
    UniFiWanMonitor,
)
from .mqtt import MqttMonitor
from .ping import PingHostMonitor
from .rest_api import RestApiMonitor
from .self_check import MonitoringCenterHealthMonitor
from .ssh_command import SshCommandMonitor
from .ssl_certificate import SslCertificateMonitor
from .system import (
    BackupFileMonitor,
    BackupMonitor,
    DirectoryFileCountMonitor,
    DirectorySizeMonitor,
    DiskUsageMonitor,
    DockerComposeServiceMonitor,
    DockerContainerMonitor,
    DockerHealthcheckMonitor,
    DockerLogRegexMonitor,
    FileAgeMonitor,
    FileExistsMonitor,
    FileHashMonitor,
    HomeAssistantBackupMonitor,
    JournaldRegexMonitor,
    LinuxHostMonitor,
    LogRegexMonitor,
)
from .tcp import TcpPortMonitor

_PLUGIN_LIST: list[MonitorTypePlugin] = [
    PingHostMonitor(),
    TcpPortMonitor(),
    HttpStatusMonitor(),
    HttpHashMonitor(),
    DnsLookupMonitor(),
    SslCertificateMonitor(),
    RestApiMonitor(),
    HomeAssistantEntityMonitor(),
    MqttMonitor(),
    MonitoringCenterHealthMonitor(),
    SshCommandMonitor(),
    DockerContainerMonitor(),
    DockerComposeServiceMonitor(),
    DockerHealthcheckMonitor(),
    LinuxHostMonitor(),
    DiskUsageMonitor(),
    BackupMonitor(),
    BackupFileMonitor(),
    HomeAssistantBackupMonitor(),
    HomeAssistantHealthMonitor(),
    PiHoleHealthMonitor(),
    UniFiDeviceMonitor(),
    UniFiWanMonitor(),
    SnmpOidMonitor(),
    SnmpInterfaceMonitor(),
    LogRegexMonitor(),
    JournaldRegexMonitor(),
    DockerLogRegexMonitor(),
    FileExistsMonitor(),
    FileAgeMonitor(),
    FileHashMonitor(),
    DirectorySizeMonitor(),
    DirectoryFileCountMonitor(),
]
PLUGINS: dict[str, MonitorTypePlugin] = {plugin.type: plugin for plugin in _PLUGIN_LIST}

LEGACY_TYPE_MAP = {
    "device": "ping_host",
    "www": "http_hash",
    "website": "http_hash",
}

SSH_CREDENTIAL_TYPES = {
    "ssh_command",
    "docker_container",
    "docker_compose_service",
    "docker_healthcheck",
    "linux_host",
    "disk_usage",
    "backup_age",
    "backup_file",
    "ha_backup",
    "file_exists",
    "file_age",
    "file_hash",
    "directory_size",
    "directory_file_count",
    "ssh_log_regex",
    "journald_regex",
    "docker_log_regex",
    "unifi_device",
    "unifi_wan",
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
    {
        "name": "SSH - Docker active",
        "type": "ssh_command",
        "target": "192.168.1.10:22",
        "interval_seconds": 300,
        "config": {
            "host": "192.168.1.10",
            "port": 22,
            "username": "root",
            "auth_method": "private_key",
            "command": "systemctl is-active docker",
            "success_exit_codes": [0],
            "warning_exit_codes": [3],
        },
    },
    {
        "name": "Docker - Home Assistant container",
        "type": "docker_container",
        "target": "192.168.1.50:homeassistant",
        "interval_seconds": 300,
        "config": {
            "host": "192.168.1.50",
            "username": "root",
            "auth_method": "private_key",
            "container_name": "homeassistant",
            "check_running": True,
            "check_health": True,
        },
    },
    {
        "name": "Linux host - NAS",
        "type": "linux_host",
        "target": "192.168.1.50:22",
        "interval_seconds": 300,
        "config": {
            "host": "192.168.1.50",
            "username": "root",
            "auth_method": "private_key",
            "systemd_services": ["docker", "ssh"],
        },
    },
    {
        "name": "Dysk root przez SSH",
        "type": "disk_usage",
        "target": "192.168.1.50:/",
        "interval_seconds": 300,
        "config": {"host": "192.168.1.50", "username": "root", "auth_method": "private_key", "mountpoint": "/"},
    },
    {
        "name": "Backup - ostatni plik tar",
        "type": "backup_age",
        "target": "192.168.1.50:/backup",
        "interval_seconds": 3600,
        "config": {
            "host": "192.168.1.50",
            "username": "root",
            "auth_method": "private_key",
            "path": "/backup",
            "filename_regex": ".*\\.tar$",
            "max_age_hours": 24,
        },
    },
]


def resolve_type(monitor_type: str) -> str:
    return LEGACY_TYPE_MAP.get(monitor_type, monitor_type)


def get_plugin(monitor_type: str) -> MonitorTypePlugin:
    resolved = resolve_type(monitor_type)
    if resolved not in PLUGINS:
        raise KeyError(monitor_type)
    return PLUGINS[resolved]


def credential_kinds_for_type(monitor_type: str) -> list[str]:
    resolved = resolve_type(monitor_type)
    if resolved in SSH_CREDENTIAL_TYPES:
        return ["username_password", "ssh_private_key"]
    if resolved == "mqtt_monitor":
        return ["username_password"]
    return []


def list_types() -> list[dict[str, Any]]:
    return [
        {
            "type": plugin.type,
            "label": plugin.label,
            "category": plugin.category,
            "default_interval": plugin.default_interval,
            "credential_kinds": credential_kinds_for_type(plugin.type),
        }
        for plugin in PLUGINS.values()
    ]
