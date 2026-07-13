from __future__ import annotations

import asyncio
import ipaddress
import platform
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any

from .ha import HomeAssistantClient
from .monitor_types import get_plugin
from .monitor_types.ssh_common import run_ssh_command

DISCOVERY_ENTITY_DOMAINS = {"binary_sensor", "sensor", "device_tracker", "switch", "light", "update"}
NETWORK_PORTS = [22, 53, 80, 443, 8123, 1883, 8080, 8443]
NETWORK_CONCURRENCY = 32
DEVICE_ICONS = {
    "router": "📡",
    "access_point": "📶",
    "nas": "💾",
    "server": "🖥️",
    "camera": "📷",
    "printer": "🖨️",
    "television": "📺",
    "speaker": "🔊",
    "phone": "📱",
    "iot": "💡",
    "computer": "💻",
    "unknown": "🌐",
}
OUI_HINTS = {
    "00:08:9B": ("QNAP", "nas"),
    "00:11:32": ("Synology", "nas"),
    "24:5E:BE": ("QNAP", "nas"),
    "24:A4:3C": ("Ubiquiti", "access_point"),
    "74:83:C2": ("Ubiquiti", "access_point"),
    "F0:9F:C2": ("Ubiquiti", "access_point"),
    "4C:5E:0C": ("MikroTik", "router"),
    "DC:2C:6E": ("MikroTik", "router"),
    "50:C7:BF": ("TP-Link", "router"),
    "EC:08:6B": ("TP-Link", "router"),
    "B8:27:EB": ("Raspberry Pi", "server"),
    "DC:A6:32": ("Raspberry Pi", "server"),
    "E4:5F:01": ("Raspberry Pi", "server"),
    "2C:CF:67": ("Raspberry Pi", "server"),
}
SOURCE_LABELS = {
    "home_assistant": "Home Assistant",
    "network": "Sieć lokalna",
    "docker": "Docker",
    "unifi": "UniFi / SNMP",
}


@dataclass
class DiscoveryProposal:
    name: str
    type: str
    target: str
    config: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    reason: str = ""
    duplicate_of_monitor_id: int | None = None
    hostname: str | None = None
    mac_address: str | None = None
    vendor: str | None = None
    device_kind: str | None = None
    icon: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "target": self.target,
            "config": self.config,
            "confidence": round(max(0.0, min(float(self.confidence), 1.0)), 2),
            "reason": self.reason,
            "duplicate_of_monitor_id": self.duplicate_of_monitor_id,
            "hostname": self.hostname,
            "mac_address": self.mac_address,
            "vendor": self.vendor,
            "device_kind": self.device_kind,
            "icon": self.icon,
        }


@dataclass
class DiscoverySourceBatch:
    proposals: list[DiscoveryProposal]
    status: str | None = None
    message: str | None = None


class DiscoverySourceSkipped(Exception):
    """Raised when a selected source cannot run without additional configuration."""


class DiscoveryService:
    def __init__(self, ha: HomeAssistantClient) -> None:
        self.ha = ha

    async def scan(
        self,
        payload: dict[str, Any],
        existing_monitors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        sources = payload.get("sources") or []
        timeout = float(payload.get("timeout_seconds") or 3)
        max_hosts = int(payload.get("max_hosts") or 64)
        total_timeout = float(payload.get("total_timeout_seconds") or 60)
        tasks: list[asyncio.Task[tuple[list[DiscoveryProposal], dict[str, Any]]]] = []
        if "home_assistant" in sources:
            tasks.append(
                asyncio.create_task(
                    self._run_source("home_assistant", self._scan_home_assistant(timeout), total_timeout)
                )
            )
        if "network" in sources:
            tasks.append(
                asyncio.create_task(
                    self._run_source(
                        "network",
                        self._scan_network(str(payload.get("network_cidr") or ""), timeout, max_hosts),
                        total_timeout,
                    )
                )
            )
        if "docker" in sources:
            tasks.append(
                asyncio.create_task(
                    self._run_source("docker", self._scan_docker(existing_monitors, timeout), total_timeout)
                )
            )
        if "unifi" in sources:
            tasks.append(
                asyncio.create_task(self._run_source("unifi", self._scan_unifi(existing_monitors), total_timeout))
            )
        if not tasks:
            return self._scan_response([], [])

        results = await asyncio.gather(*tasks)
        proposals: list[DiscoveryProposal] = []
        source_results: list[dict[str, Any]] = []
        for result, source_result in results:
            proposals.extend(result)
            source_results.append(source_result)
        deduplicated = self._deduplicate_proposals(proposals, existing_monitors)
        return self._scan_response(deduplicated, source_results)

    async def _run_source(
        self,
        source: str,
        scan: Any,
        total_timeout: float,
    ) -> tuple[list[DiscoveryProposal], dict[str, Any]]:
        started = time.perf_counter()
        proposals: list[DiscoveryProposal] = []
        status = "empty"
        message = "Skan zakończony poprawnie, ale nie znaleziono nowych kandydatów."
        try:
            result = await asyncio.wait_for(scan, timeout=total_timeout)
            if isinstance(result, DiscoverySourceBatch):
                proposals = result.proposals
                status = result.status or ("success" if proposals else "empty")
                message = result.message or message
            else:
                proposals = result
                if proposals:
                    status = "success"
                    message = f"Znaleziono {len(proposals)} kandydatów."
        except DiscoverySourceSkipped as exc:
            status = "skipped"
            message = str(exc)
        except TimeoutError:
            status = "error"
            message = f"Źródło przekroczyło limit czasu {total_timeout:g} s."
        except Exception as exc:
            status = "error"
            message = _source_error_message(exc)
        duration_ms = round((time.perf_counter() - started) * 1000)
        return proposals, {
            "source": source,
            "label": SOURCE_LABELS[source],
            "status": status,
            "found": len(proposals),
            "duration_ms": duration_ms,
            "message": message,
        }

    @staticmethod
    def _scan_response(
        proposals: list[DiscoveryProposal],
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        serialized = [proposal.as_dict() for proposal in proposals]
        failed = sum(source["status"] == "error" for source in sources)
        skipped = sum(source["status"] == "skipped" for source in sources)
        return {
            "proposals": serialized,
            "sources": sources,
            "summary": {
                "selected_sources": len(sources),
                "completed_sources": len(sources) - failed - skipped,
                "failed_sources": failed,
                "skipped_sources": skipped,
                "proposals": len(serialized),
            },
        }

    async def _scan_home_assistant(self, timeout: float) -> list[DiscoveryProposal]:
        if getattr(self.ha, "available", True) is False:
            raise DiscoverySourceSkipped("Brak połączenia z Home Assistant: SUPERVISOR_TOKEN nie jest dostępny.")
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

    async def _scan_network(
        self,
        cidr: str,
        timeout: float,
        max_hosts: int,
    ) -> DiscoverySourceBatch:
        if not cidr:
            raise ValueError("Podaj zakres sieci w formacie CIDR, np. 192.168.1.0/24.")
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ValueError(f"Nieprawidłowy zakres CIDR: {cidr}.") from exc
        hosts = _hosts_from_cidr(cidr, max_hosts)
        if not hosts:
            return DiscoverySourceBatch([])
        semaphore = asyncio.Semaphore(NETWORK_CONCURRENCY)
        tasks = [self._scan_network_host(str(host), timeout, semaphore) for host in hosts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        proposals: list[DiscoveryProposal] = []
        failed_hosts = 0
        for result in results:
            if not isinstance(result, list):
                failed_hosts += 1
                continue
            proposals.extend(result)
        if failed_hosts == len(hosts):
            raise RuntimeError("Nie udało się przeskanować żadnego hosta w podanym zakresie sieci.")
        if failed_hosts:
            return DiscoverySourceBatch(
                proposals,
                status="partial",
                message=f"Skan zakończono częściowo; błędy wystąpiły dla {failed_hosts} hostów.",
            )
        return DiscoverySourceBatch(proposals)

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
        hostname, mac_address = await asyncio.gather(_reverse_hostname(host, timeout), _neighbor_mac(host, timeout))
        vendor, vendor_kind = _vendor_hint(mac_address)
        device_kind = _infer_device_kind(hostname, vendor, vendor_kind, ports)
        icon = DEVICE_ICONS[device_kind]
        display_name = hostname or host
        identity_reason = _identity_reason(hostname, mac_address, vendor, device_kind)
        proposals: list[DiscoveryProposal] = []
        if ping_ok:
            proposals.append(
                DiscoveryProposal(
                    name=f"Ping {display_name}",
                    type="ping_host",
                    target=host,
                    config={},
                    confidence=0.8 if hostname or mac_address else 0.7,
                    reason=f"Host odpowiedział na ping sweep. {identity_reason}",
                    hostname=hostname,
                    mac_address=mac_address,
                    vendor=vendor,
                    device_kind=device_kind,
                    icon=icon,
                )
            )
        for port in ports:
            proposals.append(
                _port_proposal(host, port, display_name, hostname, mac_address, vendor, device_kind, icon)
            )
        return proposals

    async def _scan_docker(
        self,
        existing_monitors: list[dict[str, Any]],
        timeout: float,
    ) -> DiscoverySourceBatch:
        proposals: list[DiscoveryProposal] = []
        seen_hosts: set[str] = set()
        failed_hosts: list[str] = []
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
                if result.exit_code not in {None, 0}:
                    failed_hosts.append(host)
                    continue
            except Exception:
                failed_hosts.append(host)
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
        if not seen_hosts:
            raise DiscoverySourceSkipped(
                "Brak skonfigurowanego monitora Docker/Linux/SSH, z którego można pobrać listę kontenerów."
            )
        if failed_hosts and not proposals:
            raise RuntimeError(f"Nie udało się połączyć z hostami Docker: {', '.join(failed_hosts)}.")
        if failed_hosts:
            return DiscoverySourceBatch(
                proposals,
                status="partial",
                message=f"Wykryto kontenery, ale nie udało się przeskanować: {', '.join(failed_hosts)}.",
            )
        return DiscoverySourceBatch(proposals)

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
        if not proposals:
            raise DiscoverySourceSkipped(
                "Brak istniejącej konfiguracji UniFi/SNMP, na podstawie której można wykryć urządzenia."
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
    except FileNotFoundError as exc:
        raise RuntimeError("Narzędzie systemowe ping nie jest dostępne.") from exc
    except TimeoutError:
        return False
    except OSError as exc:
        raise RuntimeError(f"Nie udało się uruchomić ping: {exc}") from exc
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


def _port_proposal(
    host: str,
    port: int,
    display_name: str | None = None,
    hostname: str | None = None,
    mac_address: str | None = None,
    vendor: str | None = None,
    device_kind: str = "unknown",
    icon: str = DEVICE_ICONS["unknown"],
) -> DiscoveryProposal:
    label = display_name or host
    identity = {
        "hostname": hostname,
        "mac_address": mac_address,
        "vendor": vendor,
        "device_kind": device_kind,
        "icon": icon,
    }
    if port in {80, 443, 8080, 8443, 8123}:
        scheme = "https" if port in {443, 8443} else "http"
        target = f"{scheme}://{host}" if port in {80, 443} else f"{scheme}://{host}:{port}"
        return DiscoveryProposal(
            name=f"HTTP {label}:{port}",
            type="http_status",
            target=target,
            config={"expected_status_codes": [200, 204, 301, 302, 401, 403]},
            confidence=0.75,
            reason=f"Port {port} jest otwarty i wyglada jak usluga HTTP.",
            **identity,
        )
    if port == 53:
        return DiscoveryProposal(
            name=f"DNS {label}",
            type="dns_lookup",
            target=host,
            config={"record_type": "A"},
            confidence=0.65,
            reason="Port DNS 53 jest otwarty.",
            **identity,
        )
    if port == 1883:
        return DiscoveryProposal(
            name=f"MQTT {label}",
            type="mqtt_monitor",
            target=f"{host}:1883",
            config={"host": host, "port": 1883},
            confidence=0.75,
            reason="Port MQTT 1883 jest otwarty.",
            **identity,
        )
    return DiscoveryProposal(
        name=f"TCP {label}:{port}",
        type="tcp_port",
        target=f"{host}:{port}",
        config={"host": host, "port": port},
        confidence=0.7,
        reason=f"Port TCP {port} jest otwarty.",
        **identity,
    )


async def _reverse_hostname(host: str, timeout: float) -> str | None:
    try:
        result = await asyncio.wait_for(asyncio.to_thread(socket.gethostbyaddr, host), timeout=max(0.2, timeout))
        hostname = str(result[0]).strip().rstrip(".")
        return hostname if hostname and hostname != host else None
    except (OSError, TimeoutError):
        return None


async def _neighbor_mac(host: str, timeout: float) -> str | None:
    commands = (["ip", "neigh", "show", host], ["arp", "-n", host])
    for command in commands:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=max(0.2, timeout))
        except (FileNotFoundError, OSError, TimeoutError):
            continue
        match = re.search(rb"\b([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\b", stdout)
        if match:
            return match.group(1).decode("ascii").upper()
    return None


def _vendor_hint(mac_address: str | None) -> tuple[str | None, str | None]:
    if not mac_address:
        return None, None
    return OUI_HINTS.get(mac_address.upper()[:8], (None, None))


def _infer_device_kind(
    hostname: str | None,
    vendor: str | None,
    vendor_kind: str | None,
    ports: list[int],
) -> str:
    text = f"{hostname or ''} {vendor or ''}".lower()
    rules = (
        ("router", ("router", "gateway", "mikrotik", "fritz")),
        ("access_point", ("unifi", "access-point", "accesspoint", "wifi", "wlan", " ap")),
        ("nas", ("nas", "synology", "qnap")),
        ("camera", ("camera", "cam-", "ipc", "hikvision", "reolink")),
        ("printer", ("printer", "drukarka", "laserjet", "officejet")),
        ("television", ("tv", "bravia", "webos", "chromecast")),
        ("speaker", ("sonos", "speaker", "audio", "homepod")),
        ("phone", ("iphone", "android", "phone", "telefon")),
        ("iot", ("shelly", "tuya", "tasmota", "esphome", "zigbee", "sensor", "light")),
        ("server", ("server", "docker", "homeassistant", "home-assistant", "pihole", "raspberry")),
        ("computer", ("desktop", "laptop", "macbook", "notebook", "workstation")),
    )
    for kind, tokens in rules:
        if any(token in text for token in tokens):
            return kind
    if vendor_kind:
        return vendor_kind
    if 8123 in ports or 22 in ports:
        return "server"
    if 1883 in ports:
        return "iot"
    if 53 in ports:
        return "router"
    return "unknown"


def _identity_reason(
    hostname: str | None,
    mac_address: str | None,
    vendor: str | None,
    device_kind: str,
) -> str:
    details = []
    if hostname:
        details.append(f"hostname: {hostname}")
    if mac_address:
        details.append(f"MAC: {mac_address}")
    if vendor:
        details.append(f"producent: {vendor}")
    details.append(f"rozpoznany typ: {device_kind}")
    return "Identyfikacja lokalna: " + ", ".join(details) + "."


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


def _source_error_message(exc: Exception) -> str:
    detail = re.sub(r"\s+", " ", str(exc)).strip()
    if not detail:
        detail = exc.__class__.__name__
    return f"Skan źródła zakończył się błędem: {detail[:300]}"
