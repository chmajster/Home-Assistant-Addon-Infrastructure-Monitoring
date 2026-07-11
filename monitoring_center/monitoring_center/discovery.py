from __future__ import annotations

import asyncio
import ipaddress
import platform
import re
from dataclasses import dataclass, field
from typing import Any

from .ha import HomeAssistantClient
from .monitor_types import get_plugin
from .monitor_types.ssh_common import run_ssh_command

DISCOVERY_ENTITY_DOMAINS = {"binary_sensor", "sensor", "device_tracker", "switch", "light", "update"}
NETWORK_PORTS = [22, 53, 80, 443, 8123, 1883, 8080, 8443]
NETWORK_CONCURRENCY = 32


@dataclass
class DiscoveryProposal:
    name: str
    type: str
    target: str
    config: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    reason: str = ""
    duplicate_of_monitor_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "target": self.target,
            "config": self.config,
            "confidence": round(max(0.0, min(float(self.confidence), 1.0)), 2),
            "reason": self.reason,
            "duplicate_of_monitor_id": self.duplicate_of_monitor_id,
        }


class DiscoveryService:
    def __init__(self, ha: HomeAssistantClient) -> None:
        self.ha = ha

    async def scan(
        self,
        payload: dict[str, Any],
        existing_monitors: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        sources = payload.get("sources") or []
        timeout = float(payload.get("timeout_seconds") or 3)
        max_hosts = int(payload.get("max_hosts") or 64)
        tasks = []
        if "home_assistant" in sources:
            tasks.append(self._scan_home_assistant(timeout))
        if "network" in sources:
            tasks.append(self._scan_network(str(payload.get("network_cidr") or ""), timeout, max_hosts))
        if "docker" in sources:
            tasks.append(self._scan_docker(existing_monitors, timeout))
        if "unifi" in sources:
            tasks.append(self._scan_unifi(existing_monitors))
        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        proposals: list[DiscoveryProposal] = []
        for result in results:
            if not isinstance(result, list):
                continue
            proposals.extend(result)
        return [proposal.as_dict() for proposal in self._deduplicate_proposals(proposals, existing_monitors)]

    async def _scan_home_assistant(self, timeout: float) -> list[DiscoveryProposal]:
        states = await asyncio.wait_for(self.ha.list_states(timeout=timeout), timeout=timeout + 1)
        proposals: list[DiscoveryProposal] = []
        for state in states:
            entity_id = str(state.get("entity_id") or "").strip()
            if "." not in entity_id or entity_id.split(".", 1)[0] not in DISCOVERY_ENTITY_DOMAINS:
                continue
            raw_attrs = state.get("attributes")
            attrs: dict[str, Any] = raw_attrs if isinstance(raw_attrs, dict) else {}
            name = str(attrs.get("friendly_name") or entity_id).strip()
            proposals.append(
                DiscoveryProposal(
                    name=f"HA {name}",
                    type="ha_entity",
                    target=entity_id,
                    config={"alert_states": _default_alert_states(entity_id)},
                    confidence=0.85,
                    reason=f"Encja Home Assistant {entity_id} jest dostepna przez lokalne API.",
                )
            )
        return proposals

    async def _scan_network(self, cidr: str, timeout: float, max_hosts: int) -> list[DiscoveryProposal]:
        hosts = _hosts_from_cidr(cidr, max_hosts)
        if not hosts:
            return []
        semaphore = asyncio.Semaphore(NETWORK_CONCURRENCY)
        tasks = [self._scan_network_host(str(host), timeout, semaphore) for host in hosts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        proposals: list[DiscoveryProposal] = []
        for result in results:
            if not isinstance(result, list):
                continue
            proposals.extend(result)
        return proposals

    async def _scan_network_host(
        self,
        host: str,
        timeout: float,
        semaphore: asyncio.Semaphore,
    ) -> list[DiscoveryProposal]:
        async with semaphore:
            ping_ok = await _ping_host(host, timeout)
            open_ports = await asyncio.gather(*(_port_open(host, port, timeout) for port in NETWORK_PORTS))
        ports = [port for port, is_open in zip(NETWORK_PORTS, open_ports, strict=False) if is_open]
        proposals: list[DiscoveryProposal] = []
        if ping_ok:
            proposals.append(
                DiscoveryProposal(
                    name=f"Ping {host}",
                    type="ping_host",
                    target=host,
                    config={},
                    confidence=0.7,
                    reason="Host odpowiedzial na ping sweep w podanym zakresie.",
                )
            )
        for port in ports:
            proposals.append(_port_proposal(host, port))
        return proposals

    async def _scan_docker(self, existing_monitors: list[dict[str, Any]], timeout: float) -> list[DiscoveryProposal]:
        proposals: list[DiscoveryProposal] = []
        seen_hosts: set[str] = set()
        for monitor in existing_monitors:
            if monitor["type"] not in {
                "docker_container",
                "docker_healthcheck",
                "docker_compose_service",
                "linux_host",
                "ssh_command",
            }:
                continue
            config = dict(monitor.get("config") or {})
            host = str(config.get("host") or "").strip()
            if not host or host in seen_hosts:
                continue
            seen_hosts.add(host)
            try:
                result = await asyncio.wait_for(
                    run_ssh_command(config, "docker ps --format '{{.Names}}|{{.Status}}'"),
                    timeout=timeout,
                )
            except Exception:
                continue
            for line in str(result.stdout or "").splitlines():
                name = line.split("|", 1)[0].strip()
                if not name:
                    continue
                base_config = {
                    key: value
                    for key, value in config.items()
                    if key in {"host", "port", "username", "auth_method", "known_hosts_policy"}
                }
                base_config.update({"container_name": name, "check_running": True, "check_health": True})
                proposals.append(
                    DiscoveryProposal(
                        name=f"Docker {name}",
                        type="docker_container",
                        target=f"{host}:{name}",
                        config=base_config,
                        confidence=0.9,
                        reason=f"Kontener {name} wykryty przez docker ps na {host}.",
                    )
                )
                proposals.append(
                    DiscoveryProposal(
                        name=f"Docker health {name}",
                        type="docker_healthcheck",
                        target=f"{host}:{name}",
                        config=base_config,
                        confidence=0.8,
                        reason=f"Kontener {name} moze miec healthcheck Dockera.",
                    )
                )
        return proposals

    async def _scan_unifi(self, existing_monitors: list[dict[str, Any]]) -> list[DiscoveryProposal]:
        proposals: list[DiscoveryProposal] = []
        for monitor in existing_monitors:
            if monitor["type"] not in {"unifi_device", "unifi_wan", "snmp_oid", "snmp_interface"}:
                continue
            config = dict(monitor.get("config") or {})
            host = str(config.get("host") or monitor.get("target") or "").split(":", 1)[0].strip()
            if not host:
                continue
            proposals.append(
                DiscoveryProposal(
                    name=f"UniFi/SNMP {host}",
                    type="unifi_device",
                    target=host,
                    config={
                        key: value
                        for key, value in config.items()
                        if key in {"host", "port", "username", "auth_method", "known_hosts_policy"}
                    },
                    confidence=0.65,
                    reason="Istniejaca konfiguracja UniFi/SNMP wskazuje urzadzenie sieciowe do monitorowania.",
                )
            )
        return proposals

    def _deduplicate_proposals(
        self,
        proposals: list[DiscoveryProposal],
        existing_monitors: list[dict[str, Any]],
    ) -> list[DiscoveryProposal]:
        output: list[DiscoveryProposal] = []
        seen: set[tuple[str, str]] = set()
        for proposal in proposals:
            key = _proposal_key(proposal.type, proposal.target, proposal.config)
            if key in seen:
                continue
            seen.add(key)
            duplicate = _find_existing_duplicate(proposal, existing_monitors)
            if duplicate:
                proposal.duplicate_of_monitor_id = int(duplicate["id"])
            output.append(proposal)
        return output


def _default_alert_states(entity_id: str) -> list[str]:
    domain = entity_id.split(".", 1)[0]
    if domain in {"binary_sensor", "device_tracker"}:
        return ["unavailable", "unknown", "off", "not_home"]
    if domain == "update":
        return ["unavailable", "unknown", "on"]
    return ["unavailable", "unknown"]


def _hosts_from_cidr(cidr: str, max_hosts: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    if not cidr:
        return []
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return []
    hosts = []
    for index, host in enumerate(network.hosts()):
        if index >= max_hosts:
            break
        hosts.append(host)
    return [host for host in hosts if isinstance(host, ipaddress.IPv4Address | ipaddress.IPv6Address)]


async def _ping_host(host: str, timeout: float) -> bool:
    timeout_ms = max(100, int(timeout * 1000))
    if platform.system().lower() == "windows":
        command = ["ping", "-n", "1", "-w", str(timeout_ms), host]
    else:
        command = ["ping", "-c", "1", "-W", str(max(1, int(timeout))), host]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await asyncio.wait_for(process.wait(), timeout=timeout + 1) == 0
    except Exception:
        return False


async def _port_open(host: str, port: int, timeout: float) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


def _port_proposal(host: str, port: int) -> DiscoveryProposal:
    if port in {80, 443, 8080, 8443, 8123}:
        scheme = "https" if port in {443, 8443} else "http"
        target = f"{scheme}://{host}" if port in {80, 443} else f"{scheme}://{host}:{port}"
        return DiscoveryProposal(
            name=f"HTTP {host}:{port}",
            type="http_status",
            target=target,
            config={"expected_status_codes": [200, 204, 301, 302, 401, 403]},
            confidence=0.75,
            reason=f"Port {port} jest otwarty i wyglada jak usluga HTTP.",
        )
    if port == 53:
        return DiscoveryProposal(
            name=f"DNS {host}",
            type="dns_lookup",
            target=host,
            config={"record_type": "A"},
            confidence=0.65,
            reason="Port DNS 53 jest otwarty.",
        )
    if port == 1883:
        return DiscoveryProposal(
            name=f"MQTT {host}",
            type="mqtt_monitor",
            target=f"{host}:1883",
            config={"host": host, "port": 1883},
            confidence=0.75,
            reason="Port MQTT 1883 jest otwarty.",
        )
    return DiscoveryProposal(
        name=f"TCP {host}:{port}",
        type="tcp_port",
        target=f"{host}:{port}",
        config={"host": host, "port": port},
        confidence=0.7,
        reason=f"Port TCP {port} jest otwarty.",
    )


def _find_existing_duplicate(
    proposal: DiscoveryProposal,
    existing_monitors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    proposal_key = _proposal_key(proposal.type, proposal.target, proposal.config)
    for monitor in existing_monitors:
        if _proposal_key(monitor["type"], monitor["target"], monitor.get("config") or {}) == proposal_key:
            return monitor
    return None


def _proposal_key(monitor_type: str, target: str, config: dict[str, Any]) -> tuple[str, str]:
    try:
        plugin = get_plugin(monitor_type)
        normalized_target, normalized_config = plugin.validate(target, dict(config), None)  # type: ignore[arg-type]
        target = normalized_target
        config = normalized_config
    except Exception:
        pass
    host = str(config.get("host") or "").lower().strip()
    port = config.get("port")
    entity = target.lower().strip()
    if host and port:
        entity = f"{host}:{port}"
    if monitor_type in {"docker_container", "docker_healthcheck", "docker_compose_service"}:
        entity = f"{host}:{config.get('container_name') or config.get('service_name') or target}".lower()
    return monitor_type, re.sub(r"/+$", "", entity)
