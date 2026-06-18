from __future__ import annotations

import asyncio
from typing import Any

from ..config import AppConfig
from .base import CheckResult, MonitorContext, positive_float


class DnsLookupMonitor:
    type = "dns_lookup"
    label = "DNS lookup"
    category = "network"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        domain = target.strip().rstrip(".")
        if not domain:
            raise ValueError("DNS domain is required")
        config["record_type"] = str(config.get("record_type") or "A").upper()
        if config["record_type"] not in {"A", "AAAA", "CNAME", "MX", "TXT"}:
            raise ValueError("Unsupported DNS record type")
        config["timeout_seconds"] = positive_float(config.get("timeout_seconds"), 5.0, 1, 60)
        return domain, config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        try:
            domain = monitor["target"].strip().rstrip(".")
            record_type = str(monitor["config"].get("record_type") or "A").upper()
            timeout = positive_float(monitor["config"].get("timeout_seconds"), 5.0, 1, 60)
            records = await asyncio.wait_for(asyncio.to_thread(_resolve, domain, record_type), timeout=timeout)
            previous = monitor["config"].get("last_dns_result")
            changed = bool(previous and previous != records)
            return CheckResult(
                "ok",
                content_changed=changed,
                details={
                    "domain": domain,
                    "record_type": record_type,
                    "records": records,
                    "previous_records": previous,
                    "dns_changed": changed,
                },
                events=["dns_record_changed"] if changed else [],
            )
        except Exception as exc:
            return CheckResult("error", error=str(exc))


def _resolve(domain: str, record_type: str) -> list[str]:
    try:
        import dns.resolver

        answers = dns.resolver.resolve(domain, record_type)
        return sorted(str(answer).strip('"') for answer in answers)
    except ImportError:
        if record_type not in {"A", "AAAA"}:
            raise RuntimeError("dnspython is required for this DNS record type")
        import socket

        family = socket.AF_INET6 if record_type == "AAAA" else socket.AF_INET
        return sorted({item[4][0] for item in socket.getaddrinfo(domain, None, family)})
