from __future__ import annotations

import asyncio
import time
from typing import Any

from ..config import AppConfig
from .base import CheckResult, MonitorContext, positive_float, positive_int


class MqttMonitor:
    type = "mqtt_monitor"
    label = "MQTT monitor"
    category = "network"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        host, port = _host_port(target, config)
        config["host"] = host
        config["port"] = port
        config["timeout_seconds"] = positive_float(config.get("timeout_seconds"), 5.0, 1, 120)
        config["topic_timeout_seconds"] = positive_float(config.get("topic_timeout_seconds"), 30.0, 1, 3600)
        return f"{host}:{port}", config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        host, port = _host_port(monitor["target"], monitor["config"])
        timeout = positive_float(monitor["config"].get("timeout_seconds"), 5.0, 1, 120)
        topic = str(monitor["config"].get("topic") or "").strip()
        started = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
            writer.close()
            await writer.wait_closed()
            elapsed_ms = (time.perf_counter() - started) * 1000
            details = {"host": host, "port": port, "topic": topic or None}
            if topic:
                message = await asyncio.to_thread(_wait_for_topic, host, port, topic, monitor["config"])
                details["last_topic_payload"] = message[:1000]
                details["topic_received"] = True
            return CheckResult("ok", response_ms=elapsed_ms, details=details)
        except asyncio.TimeoutError:
            return CheckResult(
                "timeout",
                error=f"MQTT broker {host}:{port} timed out",
                details={"host": host, "port": port, "topic": topic or None},
                events=["mqtt_monitor_timeout"],
            )
        except TimeoutError as exc:
            return CheckResult(
                "timeout",
                error=str(exc),
                details={"host": host, "port": port, "topic": topic or None},
                events=["mqtt_monitor_timeout"],
            )
        except Exception as exc:
            return CheckResult("error", error=str(exc), details={"host": host, "port": port, "topic": topic or None})


def _host_port(target: str, config: dict[str, Any]) -> tuple[str, int]:
    host = str(config.get("host") or "").strip()
    port_value = config.get("port")
    if not host:
        if target.count(":") == 1:
            host, port_text = target.rsplit(":", 1)
            port_value = port_value or port_text
        else:
            host = target.strip()
    return host, positive_int(port_value, 1883, 1, 65535)


def _wait_for_topic(host: str, port: int, topic: str, config: dict[str, Any]) -> str:
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise RuntimeError("paho-mqtt is required for MQTT topic checks") from exc

    timeout = positive_float(config.get("topic_timeout_seconds"), 30.0, 1, 3600)
    username = str(config.get("username") or "").strip()
    password = str(config.get("password") or "")
    received: dict[str, str] = {}

    def on_connect(client: Any, userdata: Any, flags: Any, rc: int) -> None:
        if rc == 0:
            client.subscribe(topic)

    def on_message(client: Any, userdata: Any, message: Any) -> None:
        received["payload"] = message.payload.decode(errors="replace")
        client.disconnect()

    client = mqtt.Client()
    if username:
        client.username_pw_set(username, password or None)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, keepalive=max(5, int(timeout)))
    client.loop_start()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "payload" in received:
                return received["payload"]
            time.sleep(0.1)
        raise TimeoutError(f"No MQTT message received on topic {topic} within {timeout}s")
    finally:
        client.loop_stop()
        client.disconnect()
