from __future__ import annotations

from typing import Any

from ..config import AppConfig
from .base import CheckResult, MonitorContext, csv_ints, positive_int
from .ssh_common import normalize_ssh_config, regex_matches, run_ssh_command


class SshCommandMonitor:
    type = "ssh_command"
    label = "SSH / Bash"
    category = "system"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        target, config = normalize_ssh_config(target, config, app_config)
        config["command"] = str(config.get("command") or "").strip()
        config["shell"] = str(config.get("shell") or "bash").strip()
        config["command_timeout_seconds"] = positive_int(config.get("command_timeout_seconds"), 30, 1, 3600)
        config["success_exit_codes"] = csv_ints(config.get("success_exit_codes"), [0])
        config["warning_exit_codes"] = csv_ints(config.get("warning_exit_codes"), [1])
        config["error_exit_codes"] = csv_ints(config.get("error_exit_codes"), [2, 3, 4, 5])
        config["max_output_chars"] = positive_int(config.get("max_output_chars"), 4000, 1, 200000)
        config["store_output"] = bool(config.get("store_output", True))
        return target, config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        config = monitor["config"]
        try:
            result = await run_ssh_command(config, config.get("command") or None)
        except TimeoutError as exc:
            return CheckResult(
                "offline",
                error=str(exc),
                details={"target": monitor["target"]},
                events=["ssh_connection_failed"],
            )
        except Exception as exc:
            return CheckResult(
                "offline",
                error=str(exc),
                details={"target": monitor["target"]},
                events=["ssh_connection_failed"],
            )

        details: dict[str, Any] = {
            "target": monitor["target"],
            "exit_code": result.exit_code,
            "duration_ms": round(result.elapsed_ms, 2),
        }
        if config.get("store_output", True):
            details["stdout_excerpt"] = result.stdout
            details["stderr_excerpt"] = result.stderr

        if result.exit_code is None:
            return CheckResult("online", response_ms=result.elapsed_ms, details=details, events=["ssh_command_ok"])

        regex_alert = regex_matches(config.get("alert_on_stdout_regex"), result.stdout) or regex_matches(
            config.get("alert_on_stderr_regex"),
            result.stderr,
        )
        status = self._status_from_regex(config, result.stdout, result.stderr) or self._status_from_exit_code(
            config,
            result.exit_code,
        )
        events = [_event_for_status(status)]
        if regex_alert:
            events.append("ssh_command_regex_alert")
            details["regex_alert"] = True
        return CheckResult(
            status,
            response_ms=result.elapsed_ms,
            error=None if status in {"online", "ok", "warning"} else "SSH command check failed",
            details=details,
            events=events,
        )

    @staticmethod
    def _status_from_regex(config: dict[str, Any], stdout: str, stderr: str) -> str | None:
        if regex_matches(config.get("error_stdout_regex"), stdout) or regex_matches(
            config.get("error_stderr_regex"),
            stderr,
        ):
            return "error"
        if regex_matches(config.get("warning_stdout_regex"), stdout) or regex_matches(
            config.get("warning_stderr_regex"),
            stderr,
        ):
            return "warning"
        if regex_matches(config.get("success_stdout_regex"), stdout) or regex_matches(
            config.get("success_stderr_regex"),
            stderr,
        ):
            return "online"
        return None

    @staticmethod
    def _status_from_exit_code(config: dict[str, Any], exit_code: int) -> str:
        if exit_code in csv_ints(config.get("success_exit_codes"), [0]):
            return "online"
        if exit_code in csv_ints(config.get("warning_exit_codes"), [1]):
            return "warning"
        if exit_code in csv_ints(config.get("error_exit_codes"), [2, 3, 4, 5]):
            return "error"
        return "error"


def _event_for_status(status: str) -> str:
    if status == "warning":
        return "ssh_command_warning"
    if status == "error":
        return "ssh_command_error"
    return "ssh_command_ok"
