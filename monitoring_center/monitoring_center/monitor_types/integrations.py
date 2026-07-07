from __future__ import annotations

# ruff: noqa: E501
import asyncio
import time
from typing import Any

import httpx

from ..config import AppConfig
from .base import CheckResult, MonitorContext, positive_float, positive_int
from .ssh_common import normalize_ssh_config, quote, run_ssh_command


class HomeAssistantHealthMonitor:
    type = "ha_health"
    label = "Home Assistant Health"
    category = "home_assistant"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        config["max_unavailable_entities_warning"] = positive_int(config.get("max_unavailable_entities_warning"), 5, 0, 100000)
        config["max_unavailable_entities_error"] = positive_int(config.get("max_unavailable_entities_error"), 15, 0, 100000)
        config["max_unknown_entities_warning"] = positive_int(config.get("max_unknown_entities_warning"), 10, 0, 100000)
        config["check_supervisor"] = bool(config.get("check_supervisor", True))
        config["check_updates"] = bool(config.get("check_updates", True))
        config["check_recorder"] = bool(config.get("check_recorder", True))
        config["check_log_errors"] = bool(config.get("check_log_errors", True))
        config["log_error_window_minutes"] = positive_int(config.get("log_error_window_minutes"), 60, 1, 1440)
        return target.strip() or "home_assistant", config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        if not context.ha.available:
            return CheckResult("error", error="Home Assistant Supervisor token is unavailable", events=["ha_health_error"])
        started = time.perf_counter()
        details: dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=context.ha._headers) as client:  # noqa: SLF001
                states = (await client.get(f"{context.ha.base_url}/states")).json()
        except Exception as exc:
            return CheckResult("error", error=str(exc), events=["ha_health_error"])
        unavailable = [item for item in states if item.get("state") == "unavailable"]
        unknown = [item for item in states if item.get("state") == "unknown"]
        details["unavailable_entities"] = len(unavailable)
        details["unknown_entities"] = len(unknown)
        events = ["ha_health_ok"]
        status = "online"
        error = None
        cfg = monitor["config"]
        if len(unavailable) >= int(cfg["max_unavailable_entities_error"]):
            status, error, events = "error", "Too many unavailable Home Assistant entities", ["ha_entities_unavailable", "ha_health_error"]
        elif len(unavailable) >= int(cfg["max_unavailable_entities_warning"]) or len(unknown) >= int(cfg["max_unknown_entities_warning"]):
            status, error, events = "warning", "Home Assistant entity warning threshold exceeded", ["ha_entities_unavailable", "ha_health_warning"]
        updates = [item for item in states if item.get("entity_id", "").startswith("update.") and item.get("state") == "on"]
        details["pending_updates"] = len(updates)
        if cfg.get("check_updates") and updates and status == "online":
            status, error, events = "warning", "Home Assistant updates available", ["ha_updates_available", "ha_health_warning"]
        return CheckResult(status, response_ms=(time.perf_counter() - started) * 1000, error=error, details=details, events=events)


class PiHoleHealthMonitor:
    type = "pihole_health"
    label = "Pi-hole Health"
    category = "network"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        config["base_url"] = str(config.get("base_url") or target).rstrip("/")
        if not config["base_url"]:
            raise ValueError("Pi-hole base_url is required")
        config["dns_host"] = str(config.get("dns_host") or "").strip()
        config["dns_port"] = positive_int(config.get("dns_port"), 53, 1, 65535)
        config["test_domain"] = str(config.get("test_domain") or "google.com").strip()
        config["min_queries_last_10m"] = positive_int(config.get("min_queries_last_10m"), 1, 0, 1000000)
        config["max_gravity_age_days"] = positive_int(config.get("max_gravity_age_days"), 7, 0, 3650)
        config["check_upstream"] = bool(config.get("check_upstream", True))
        return config["base_url"], config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        cfg = monitor["config"]
        started = time.perf_counter()
        details: dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{cfg['base_url']}/api.php?summaryRaw", params=_pihole_auth(cfg))
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            return CheckResult("error", error=str(exc), details=details, events=["pihole_error"])
        details["queries_today"] = data.get("dns_queries_today")
        details["ads_percentage_today"] = data.get("ads_percentage_today")
        details["status"] = data.get("status")
        if data.get("status") not in {None, "enabled"}:
            return CheckResult("error", response_ms=(time.perf_counter() - started) * 1000, error="Pi-hole blocking is disabled", details=details, events=["pihole_error"])
        if cfg.get("dns_host"):
            dns_ok = await asyncio.to_thread(_dns_probe, cfg["dns_host"], int(cfg["dns_port"]), cfg["test_domain"])
            details["dns_probe_ok"] = dns_ok
            if not dns_ok:
                return CheckResult("error", response_ms=(time.perf_counter() - started) * 1000, error="Pi-hole DNS probe failed", details=details, events=["pihole_dns_failed"])
        return CheckResult("online", response_ms=(time.perf_counter() - started) * 1000, details=details, events=["pihole_ok"])


class SnmpOidMonitor:
    type = "snmp_oid"
    label = "SNMP OID"
    category = "network"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        config["host"] = str(config.get("host") or target).strip()
        config["port"] = positive_int(config.get("port"), 161, 1, 65535)
        config["version"] = str(config.get("version") or "2c")
        config["community"] = str(config.get("community") or "public")
        config["oid"] = str(config.get("oid") or "").strip()
        config["operator"] = str(config.get("operator") or ">").strip()
        config["warning_value"] = positive_float(config.get("warning_value"), 100, -1_000_000_000, None)
        config["error_value"] = positive_float(config.get("error_value"), 200, -1_000_000_000, None)
        return f"{config['host']}:{config['oid']}", config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        try:
            from pysnmp.hlapi.asyncio import (
                CommunityData,
                ContextData,
                ObjectIdentity,
                ObjectType,
                SnmpEngine,
                UdpTransportTarget,
                get_cmd,
            )
        except ImportError:
            return CheckResult("error", error="pysnmp is required for SNMP monitors", details={"host": monitor["config"].get("host")}, events=["snmp_error"])
        cfg = monitor["config"]
        started = time.perf_counter()
        target = await UdpTransportTarget.create((cfg["host"], int(cfg["port"])), timeout=5, retries=1)
        error_indication, error_status, _error_index, var_binds = await get_cmd(
            SnmpEngine(),
            CommunityData(cfg["community"], mpModel=0 if cfg["version"] == "1" else 1),
            target,
            ContextData(),
            ObjectType(ObjectIdentity(cfg["oid"])),
        )
        if error_indication or error_status:
            return CheckResult("error", error=str(error_indication or error_status), events=["snmp_error"])
        value = str(var_binds[0][1]) if var_binds else ""
        numeric = _float(value)
        details = {"host": cfg["host"], "oid": cfg["oid"], "value": value, "numeric_value": numeric}
        if _compare(numeric, cfg["operator"], float(cfg["error_value"])):
            return CheckResult("error", response_ms=(time.perf_counter() - started) * 1000, error="SNMP error threshold exceeded", details=details, events=["snmp_error"])
        if _compare(numeric, cfg["operator"], float(cfg["warning_value"])):
            return CheckResult("warning", response_ms=(time.perf_counter() - started) * 1000, error="SNMP warning threshold exceeded", details=details, events=["snmp_warning"])
        return CheckResult("online", response_ms=(time.perf_counter() - started) * 1000, details=details)


class SnmpInterfaceMonitor(SnmpOidMonitor):
    type = "snmp_interface"
    label = "SNMP Interface"


class UniFiDeviceMonitor:
    type = "unifi_device"
    label = "UniFi Device"
    category = "network"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        target, config = normalize_ssh_config(target, config, app_config, require_username=False)
        config["device_host"] = str(config.get("device_host") or target.split(":", 1)[0]).strip()
        config["packet_loss_warning_percent"] = positive_float(config.get("packet_loss_warning_percent"), 20, 0, 100)
        return f"{config['host']}:{config['device_host']}", config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        cfg = monitor["config"]
        command = f"ping -c 3 -W 2 {quote(cfg['device_host'])}"
        try:
            result = await run_ssh_command(cfg, command)
        except Exception as exc:
            return CheckResult("offline", error=str(exc), details={"device_host": cfg.get("device_host")}, events=["unifi_device_offline"])
        loss = _packet_loss(result.stdout)
        details = {"device_host": cfg["device_host"], "packet_loss_percent": loss, "output_excerpt": result.stdout[-1000:]}
        if result.exit_code != 0:
            return CheckResult("error", response_ms=result.elapsed_ms, packet_loss=loss, error="UniFi device offline", details=details, events=["unifi_device_offline"])
        if loss >= float(cfg.get("packet_loss_warning_percent") or 20):
            return CheckResult("warning", response_ms=result.elapsed_ms, packet_loss=loss, error="UniFi packet loss warning", details=details, events=["unifi_packet_loss"])
        return CheckResult("online", response_ms=result.elapsed_ms, packet_loss=loss, details=details)


class UniFiWanMonitor(UniFiDeviceMonitor):
    type = "unifi_wan"
    label = "UniFi WAN"

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        result = await super().check(monitor, context)
        if result.status == "error":
            result.events = ["unifi_wan_down"]
        return result


def _pihole_auth(config: dict[str, Any]) -> dict[str, str]:
    token = str(config.get("api_token") or "")
    return {"auth": token} if token else {}


def _dns_probe(host: str, port: int, domain: str) -> bool:
    try:
        import dns.resolver

        resolver = dns.resolver.Resolver(configure=False)
        resolver.nameservers = [host]
        resolver.port = port
        resolver.lifetime = 5
        resolver.resolve(domain, "A")
        return True
    except Exception:
        return False


def _compare(left: float, operator: str, right: float) -> bool:
    if operator == ">=":
        return left >= right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator == "==":
        return left == right
    return left > right


def _float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _packet_loss(output: str) -> float:
    marker = "packet loss"
    for part in output.split(","):
        if marker in part:
            return _float(part.replace("%", "").replace(marker, ""))
    return 100.0
