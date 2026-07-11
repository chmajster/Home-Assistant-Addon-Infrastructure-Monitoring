from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..config import AppConfig
from ..validators import ensure_public_url_if_required, validate_url
from .base import (
    CheckResult,
    MonitorContext,
    csv_ints,
    normalize_timeout_config,
    positive_float,
    timeout_seconds_from_config,
)

LOGGER = logging.getLogger(__name__)
PAGE_SIZE_LIMIT_ERROR = "Configured page size limit exceeded"


class PageSizeLimitExceeded(ValueError):
    pass


class HttpStatusMonitor:
    type = "http_status"
    label = "WWW - status HTTP/HTTPS"
    category = "website"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        config["expected_status_codes"] = csv_ints(config.get("expected_status_codes"), [200])
        normalize_timeout_config(config, app_config.default_timeout_minutes * 60)
        return validate_url(target), config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        return await _http_fetch(monitor, context, hash_content=False)


class HttpHashMonitor:
    type = "http_hash"
    label = "WWW - hash zawartosci"
    category = "website"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        config["expected_status_codes"] = csv_ints(config.get("expected_status_codes"), [200])
        normalize_timeout_config(config, app_config.default_timeout_minutes * 60)
        max_page_size_mb = config.pop("max_page_size_kb", None)
        if "max_page_size_mb" not in config and max_page_size_mb not in (None, ""):
            max_page_size_mb = positive_float(max_page_size_mb, app_config.max_page_size_mb * 1024, 1, None) / 1024
        else:
            max_page_size_mb = config.get("max_page_size_mb")
        config["max_page_size_mb"] = positive_float(max_page_size_mb, app_config.max_page_size_mb, 1 / 1024, None)
        return validate_url(target), config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        return await _http_fetch(monitor, context, hash_content=True)


async def _http_fetch(monitor: dict[str, Any], context: MonitorContext, hash_content: bool) -> CheckResult:
    try:
        url = validate_url(monitor["target"])
        ensure_public_url_if_required(url, bool(context.settings["block_private_networks"]))
        expected = csv_ints(monitor["config"].get("expected_status_codes"), [200])
        timeout = timeout_seconds_from_config(
            monitor["config"],
            float(context.settings["default_timeout_minutes"]) * 60,
        )
        max_page_size_mb = monitor["config"].get("max_page_size_mb")
        if max_page_size_mb in (None, "") and monitor["config"].get("max_page_size_kb") not in (None, ""):
            max_page_size_mb = (
                positive_float(
                    monitor["config"]["max_page_size_kb"],
                    float(context.settings["max_page_size_mb"]) * 1024,
                    1,
                    None,
                )
                / 1024
            )
        effective_max_page_size_mb = positive_float(
            max_page_size_mb,
            float(context.settings["max_page_size_mb"]),
            1 / 1024,
            None,
        )
        max_bytes = int(effective_max_page_size_mb * 1024 * 1024)
        started = time.perf_counter()
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            trust_env=False,
            headers={"User-Agent": "MonitoringCenter/0.2"},
        ) as client:
            current_url = url
            body = bytearray()
            for _redirect in range(6):
                # Resolve and validate every hop. This also detects a hostname whose
                # answers change between the initial request and a redirect.
                ensure_public_url_if_required(current_url, bool(context.settings["block_private_networks"]))
                async with client.stream("GET", current_url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            break
                        current_url = validate_url(urljoin(current_url, location))
                        continue
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise PageSizeLimitExceeded(PAGE_SIZE_LIMIT_ERROR)
                    break
            else:
                raise ValueError("Too many HTTP redirects")
        elapsed_ms = (time.perf_counter() - started) * 1000
        status = "ok" if response.status_code in expected else ("warning" if response.status_code < 400 else "error")
        details: dict[str, Any] = {
            "final_url": str(response.url),
            "bytes": len(body),
            "expected_status_codes": expected,
        }
        result = CheckResult(
            status=status,
            response_ms=elapsed_ms,
            http_status=response.status_code,
            error=None if status != "error" else f"HTTP {response.status_code}",
            details=details,
        )
        if not hash_content:
            return result

        text = bytes(body).decode(response.encoding or "utf-8", errors="replace")
        normalized = normalize_content(text, monitor["config"])
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        previous_hash = monitor.get("last_content_hash")
        changed = bool(previous_hash and previous_hash != content_hash)
        result.content_hash = content_hash
        result.content_changed = changed
        result.normalized_content = normalized
        result.raw_excerpt = text[:4000]
        result.details.update(
            {
                "previous_hash": previous_hash,
                "current_hash": content_hash,
                "hash_changed": changed,
            }
        )
        if changed:
            result.events.append("website_hash_changed")
        return result
    except PageSizeLimitExceeded as exc:
        return CheckResult(
            "error",
            error=str(exc),
            details={
                "stop_checks": True,
                "stop_reason": "page_size_limit_exceeded",
                "max_page_size_mb": effective_max_page_size_mb,
            },
        )
    except Exception as exc:
        return CheckResult("error", error=str(exc))


def normalize_content(html: str, config: dict[str, Any]) -> str:
    selector = str(config.get("css_selector") or "").strip()
    if selector:
        soup = BeautifulSoup(html, "html.parser")
        selected = soup.select_one(selector)
        content = selected.get_text("\n", strip=True) if selected else ""
    else:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        content = soup.get_text("\n", strip=True)

    for pattern in config.get("ignore_patterns") or []:
        try:
            content = re.sub(str(pattern), "", content, flags=re.MULTILINE)
        except re.error:
            LOGGER.warning("Ignoring invalid content regex: %s", pattern)
    return re.sub(r"\s+", " ", content).strip()
