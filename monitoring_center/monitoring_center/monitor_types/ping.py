from __future__ import annotations

import asyncio
import os
import select
import socket
import struct
import time
from typing import Any

from ..config import AppConfig
from ..validators import validate_device_target
from .base import CheckResult, MonitorContext, positive_int


class PingHostMonitor:
    type = "ping_host"
    label = "Ping hosta"
    category = "network"
    default_interval = 60

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        normalized = validate_device_target(target)
        config["timeout_seconds"] = positive_int(
            config.get("timeout_seconds"),
            app_config.ping_timeout_seconds,
            minimum=1,
            maximum=30,
        )
        return normalized, config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        try:
            target = validate_device_target(monitor["target"])
            timeout = positive_int(
                monitor["config"].get("timeout_seconds"),
                context.config.ping_timeout_seconds,
                minimum=1,
                maximum=30,
            )
            started = time.perf_counter()
            success, error = await asyncio.to_thread(_icmp_echo, target, timeout)
            response_ms = (time.perf_counter() - started) * 1000
            if success:
                return CheckResult(
                    "online",
                    response_ms=response_ms,
                    packet_loss=0.0,
                    details={"host": target, "timeout_seconds": timeout},
                )
            return CheckResult(
                "offline",
                packet_loss=100.0,
                error=error or "Ping failed",
                details={"host": target, "timeout_seconds": timeout},
            )
        except Exception as exc:
            return CheckResult("offline", error=str(exc), packet_loss=100.0)


def _icmp_echo(target: str, timeout: int) -> tuple[bool, str]:
    try:
        addresses = socket.getaddrinfo(target, None, type=socket.SOCK_RAW)
    except socket.gaierror as exc:
        return False, f"Cannot resolve host: {exc}"

    last_error = ""
    for family, _, _, _, sockaddr in addresses:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        try:
            success, error = _send_icmp_echo(family, sockaddr, timeout)
            if success:
                return True, ""
            last_error = error
        except PermissionError:
            return False, "ICMP raw socket permission denied"
        except OSError as exc:
            last_error = str(exc)
    return False, last_error or "No usable IP address found"


def _send_icmp_echo(family: socket.AddressFamily, sockaddr: tuple[Any, ...], timeout: int) -> tuple[bool, str]:
    protocol = socket.IPPROTO_ICMP if family == socket.AF_INET else socket.IPPROTO_ICMPV6
    request_type = 8 if family == socket.AF_INET else 128
    reply_type = 0 if family == socket.AF_INET else 129
    identifier = os.getpid() & 0xFFFF
    sequence = 1

    with socket.socket(family, socket.SOCK_RAW, protocol) as sock:
        connected = False
        if family == socket.AF_INET6:
            sock.connect(sockaddr)
            connected = True
            packet = _build_icmp_packet(
                family,
                request_type,
                identifier,
                sequence,
                source_address=sock.getsockname()[0],
                destination_address=sockaddr[0],
            )
        else:
            packet = _build_icmp_packet(family, request_type, identifier, sequence)
        sock.setblocking(False)
        if connected:
            sock.send(packet)
        else:
            sock.sendto(packet, sockaddr)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False, "Ping timeout"
            readable, _, _ = select.select([sock], [], [], remaining)
            if not readable:
                return False, "Ping timeout"
            data, _ = sock.recvfrom(1024)
            message = _extract_icmp_message(family, data)
            if len(message) < 8:
                continue
            icmp_type, _, _, reply_id, reply_sequence = struct.unpack("!BBHHH", message[:8])
            if icmp_type == reply_type and reply_id == identifier and reply_sequence == sequence:
                return True, ""


def _extract_icmp_message(family: socket.AddressFamily, data: bytes) -> bytes:
    if family == socket.AF_INET and len(data) >= 20:
        header_length = (data[0] & 0x0F) * 4
        return data[header_length:]
    return data


def _build_icmp_packet(
    family: socket.AddressFamily,
    request_type: int,
    identifier: int,
    sequence: int,
    source_address: str = "",
    destination_address: str = "",
) -> bytes:
    payload = struct.pack("!d", time.time()) + b"monitoring-center"
    header = struct.pack("!BBHHH", request_type, 0, 0, identifier, sequence)
    packet = header + payload
    if family == socket.AF_INET:
        checksum = _checksum(packet)
    else:
        pseudo_header = (
            socket.inet_pton(socket.AF_INET6, source_address)
            + socket.inet_pton(socket.AF_INET6, destination_address)
            + struct.pack("!I3xB", len(packet), socket.IPPROTO_ICMPV6)
        )
        checksum = _checksum(pseudo_header + packet)
    return struct.pack("!BBHHH", request_type, 0, checksum, identifier, sequence) + payload


def _checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF
