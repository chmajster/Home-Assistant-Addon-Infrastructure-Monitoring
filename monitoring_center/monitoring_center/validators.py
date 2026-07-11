from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException

HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)" r"(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$")


def validate_device_target(target: str) -> str:
    value = target.strip()
    if not value:
        raise HTTPException(status_code=422, detail="Device target is required")
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if not HOSTNAME_RE.match(value):
        raise HTTPException(status_code=422, detail="Invalid IP address or hostname")
    return value.rstrip(".")


def validate_url(target: str) -> str:
    value = target.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=422, detail="Only http and https URLs are allowed")
    if not parsed.hostname:
        raise HTTPException(status_code=422, detail="URL hostname is required")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="URL port is invalid") from exc
    return value


def normalize_url_key(target: str) -> str:
    parsed = urlparse(validate_url(target))
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    include_port = port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443))
    netloc = f"{hostname}:{port}" if include_port else hostname
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def ensure_public_url_if_required(url: str, block_private_networks: bool) -> None:
    if not block_private_networks:
        return
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=422, detail="URL hostname is required")

    addresses: set[str] = set()
    try:
        for result in socket.getaddrinfo(hostname, parsed.port or _default_port(parsed.scheme)):
            addresses.add(result[4][0])
    except socket.gaierror as exc:
        raise HTTPException(status_code=422, detail=f"Cannot resolve URL hostname: {exc}") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise HTTPException(
                status_code=422,
                detail="URL resolves to a blocked local or private address",
            )


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80
