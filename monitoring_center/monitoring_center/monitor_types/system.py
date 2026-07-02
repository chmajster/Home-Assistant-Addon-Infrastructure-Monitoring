from __future__ import annotations

# ruff: noqa: E501

import hashlib
from typing import Any

from ..config import AppConfig
from .base import CheckResult, MonitorContext, positive_float, positive_int
from .ssh_common import normalize_ssh_config, quote, regex_matches, run_ssh_command


class DockerContainerMonitor:
    type = "docker_container"
    label = "Docker Container"
    category = "system"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        original_target = target
        target, config = normalize_ssh_config(target, config, app_config)
        config["connection_method"] = "ssh"
        config["container_name"] = str(config.get("container_name") or _target_suffix(original_target) or "").strip()
        if not config["container_name"]:
            raise ValueError("container_name is required")
        config["check_running"] = bool(config.get("check_running", True))
        config["check_health"] = bool(config.get("check_health", True))
        config["max_restart_count"] = positive_int(config.get("max_restart_count"), 3, 0, 100000)
        config["cpu_warning_percent"] = positive_float(config.get("cpu_warning_percent"), 80, 0, 1000)
        config["memory_warning_percent"] = positive_float(config.get("memory_warning_percent"), 85, 0, 1000)
        config["log_tail_lines"] = positive_int(config.get("log_tail_lines"), 100, 0, 5000)
        config["store_logs"] = bool(config.get("store_logs", False))
        return f"{config['host']}:{config['container_name']}", config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        config = monitor["config"]
        name = config["container_name"]
        command = _docker_command(name, int(config.get("log_tail_lines") or 0))
        try:
            result = await run_ssh_command(config, command)
        except Exception as exc:
            return CheckResult("offline", error=str(exc), details={"container_name": name}, events=["docker_container_error"])
        details = _parse_key_values(result.stdout)
        details["container_name"] = name
        logs = details.pop("logs", "")
        if config.get("store_logs"):
            details["log_excerpt"] = logs
        status = "online"
        events = ["docker_container_ok"]
        error = None
        if details.get("docker") != "ok":
            return CheckResult("offline", response_ms=result.elapsed_ms, error="Docker unavailable", details=details, events=["docker_container_error"])
        if details.get("exists") != "yes":
            return CheckResult("error", response_ms=result.elapsed_ms, error="Docker container does not exist", details=details, events=["docker_container_error"])
        if config.get("check_running") and details.get("running") != "running":
            status, error, events = "error", "Docker container is not running", ["docker_container_error"]
        if status != "error" and config.get("check_health") and details.get("health") == "unhealthy":
            status, error, events = "error", "Docker container is unhealthy", ["docker_container_unhealthy"]
        if status == "online" and int(details.get("restart_count") or 0) > int(config.get("max_restart_count") or 0):
            status, error, events = "warning", "Docker restart count exceeded", ["docker_container_restarted", "docker_container_warning"]
        if status == "online" and _percent(details.get("cpu_percent")) > float(config.get("cpu_warning_percent") or 0):
            status, error, events = "warning", "Docker CPU usage exceeded", ["docker_container_warning"]
        if status == "online" and _percent(details.get("memory_percent")) > float(config.get("memory_warning_percent") or 0):
            status, error, events = "warning", "Docker memory usage exceeded", ["docker_container_warning"]
        if logs and regex_matches(config.get("log_error_regex"), logs):
            details["log_regex_alert"] = True
            if status == "online":
                status, error = "warning", "Docker log regex matched"
            events.append("docker_log_regex_alert")
        return CheckResult(status, response_ms=result.elapsed_ms, error=error, details=details, events=events)


class DockerComposeServiceMonitor(DockerContainerMonitor):
    type = "docker_compose_service"
    label = "Docker Compose Service"

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        if not config.get("container_name") and config.get("service_name"):
            config["container_name"] = config["service_name"]
        return super().validate(target, config, app_config)


class DockerHealthcheckMonitor(DockerContainerMonitor):
    type = "docker_healthcheck"
    label = "Docker Healthcheck"


class LinuxHostMonitor:
    type = "linux_host"
    label = "Linux Host Health"
    category = "system"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        target, config = normalize_ssh_config(target, config, app_config)
        for key, default in {
            "cpu_load_warning": 4.0,
            "cpu_load_error": 8.0,
            "memory_warning_percent": 85,
            "memory_error_percent": 95,
            "swap_warning_percent": 50,
            "disk_warning_percent": 85,
            "disk_error_percent": 95,
            "inode_warning_percent": 85,
            "temperature_warning_c": 70,
            "temperature_error_c": 85,
        }.items():
            config[key] = positive_float(config.get(key), default, 0, None)
        config["systemd_services"] = _list(config.get("systemd_services"))
        return target, config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        services = " ".join(quote(item) for item in monitor["config"].get("systemd_services", []))
        command = _linux_host_command(services)
        try:
            result = await run_ssh_command(monitor["config"], command)
        except Exception as exc:
            return CheckResult("offline", error=str(exc), details={"target": monitor["target"]}, events=["linux_host_error"])
        details = _parse_key_values(result.stdout)
        status, error, events = _linux_status(details, monitor["config"])
        return CheckResult(status, response_ms=result.elapsed_ms, error=error, details=details, events=events)


class DiskUsageMonitor:
    type = "disk_usage"
    label = "Disk Usage"
    category = "system"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        original_target = target
        target, config = normalize_ssh_config(target, config, app_config)
        config["mountpoint"] = str(config.get("mountpoint") or _target_suffix(original_target) or "/").strip()
        config["warning_percent"] = positive_float(config.get("warning_percent"), 85, 0, 100)
        config["error_percent"] = positive_float(config.get("error_percent"), 95, 0, 100)
        config["warning_free_gb"] = positive_float(config.get("warning_free_gb"), 10, 0, None)
        config["error_free_gb"] = positive_float(config.get("error_free_gb"), 2, 0, None)
        config["check_inodes"] = bool(config.get("check_inodes", True))
        config["check_readonly"] = bool(config.get("check_readonly", True))
        return f"{config['host']}:{config['mountpoint']}", config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        mount = monitor["config"]["mountpoint"]
        command = _disk_command(mount)
        try:
            result = await run_ssh_command(monitor["config"], command)
        except Exception as exc:
            return CheckResult("offline", error=str(exc), details={"mountpoint": mount}, events=["disk_usage_error"])
        details = _parse_key_values(result.stdout)
        details["mountpoint"] = mount
        if details.get("exists") != "yes":
            return CheckResult("error", response_ms=result.elapsed_ms, error="Mountpoint does not exist", details=details, events=["disk_usage_error"])
        used = _float(details.get("used_percent"))
        free_gb = _float(details.get("free_gb"))
        inode_used = _float(details.get("inode_used_percent"))
        if monitor["config"].get("check_readonly") and details.get("readonly") == "yes":
            return CheckResult("error", response_ms=result.elapsed_ms, error="Filesystem is read-only", details=details, events=["disk_readonly"])
        if used >= float(monitor["config"].get("error_percent") or 95) or free_gb <= float(monitor["config"].get("error_free_gb") or 0):
            return CheckResult("error", response_ms=result.elapsed_ms, error="Disk usage threshold exceeded", details=details, events=["disk_usage_error"])
        if monitor["config"].get("check_inodes") and inode_used >= float(monitor["config"].get("inode_warning_percent") or 85):
            return CheckResult("warning", response_ms=result.elapsed_ms, error="Disk inode usage threshold exceeded", details=details, events=["disk_inode_warning"])
        if used >= float(monitor["config"].get("warning_percent") or 85) or free_gb <= float(monitor["config"].get("warning_free_gb") or 0):
            return CheckResult("warning", response_ms=result.elapsed_ms, error="Disk usage warning threshold exceeded", details=details, events=["disk_usage_warning"])
        return CheckResult("online", response_ms=result.elapsed_ms, details=details)


class BackupMonitor:
    type = "backup_age"
    label = "Backup Age"
    category = "backup"
    default_interval = 3600

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        original_target = target
        target, config = normalize_ssh_config(target, config, app_config)
        config["path"] = str(config.get("path") or _target_suffix(original_target) or "/backup").strip()
        config["filename_regex"] = str(config.get("filename_regex") or ".*").strip()
        config["max_age_hours"] = positive_float(config.get("max_age_hours"), 24, 0, None)
        config["min_size_mb"] = positive_float(config.get("min_size_mb"), 1, 0, None)
        config["max_size_mb"] = positive_float(config.get("max_size_mb"), 50000, 0, None)
        config["check_latest_only"] = bool(config.get("check_latest_only", True))
        return f"{config['host']}:{config['path']}", config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        cfg = monitor["config"]
        command = _latest_file_command(cfg["path"], cfg["filename_regex"])
        try:
            result = await run_ssh_command(cfg, command)
        except Exception as exc:
            return CheckResult("offline", error=str(exc), details={"path": cfg["path"]}, events=["backup_failed"])
        details = _parse_key_values(result.stdout)
        if details.get("exists") != "yes":
            return CheckResult("error", response_ms=result.elapsed_ms, error="Backup missing", details=details, events=["backup_missing"])
        age_hours = _float(details.get("age_hours"))
        size_mb = _float(details.get("size_mb"))
        if size_mb <= 0:
            return CheckResult("error", response_ms=result.elapsed_ms, error="Backup has zero size", details=details, events=["backup_failed"])
        if size_mb < float(cfg.get("min_size_mb") or 0) or size_mb > float(cfg.get("max_size_mb") or 0):
            return CheckResult("warning", response_ms=result.elapsed_ms, error="Backup size outside threshold", details=details, events=["backup_size_warning"])
        if age_hours > float(cfg.get("max_age_hours") or 0):
            return CheckResult("warning", response_ms=result.elapsed_ms, error="Backup is too old", details=details, events=["backup_old"])
        return CheckResult("online", response_ms=result.elapsed_ms, details=details, events=["backup_ok"])


class BackupFileMonitor(BackupMonitor):
    type = "backup_file"
    label = "Backup File"


class HomeAssistantBackupMonitor(BackupMonitor):
    type = "ha_backup"
    label = "Home Assistant Backup"


class FileExistsMonitor(BackupMonitor):
    type = "file_exists"
    label = "File Exists"
    category = "files"

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        path = monitor["config"]["path"]
        try:
            result = await run_ssh_command(monitor["config"], f"test -e {quote(path)} && echo exists=yes || echo exists=no")
        except Exception as exc:
            return CheckResult("offline", error=str(exc), details={"path": path}, events=["file_missing"])
        details = _parse_key_values(result.stdout)
        status = "online" if details.get("exists") == "yes" else "error"
        return CheckResult(status, response_ms=result.elapsed_ms, error=None if status == "online" else "File missing", details=details, events=[] if status == "online" else ["file_missing"])


class FileAgeMonitor(BackupMonitor):
    type = "file_age"
    label = "File Age"
    category = "files"

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        return await super().check(monitor, context)


class FileHashMonitor(BackupMonitor):
    type = "file_hash"
    label = "File Hash"
    category = "files"

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        target, config = super().validate(target, config, app_config)
        config["hash_algorithm"] = str(config.get("hash_algorithm") or "sha256")
        return target, config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        path = monitor["config"]["path"]
        algo = monitor["config"].get("hash_algorithm") or "sha256"
        command = f"test -f {quote(path)} && {quote(algo)}sum {quote(path)} | awk '{{print \"hash=\"$1}}' || echo exists=no"
        try:
            result = await run_ssh_command(monitor["config"], command)
        except Exception as exc:
            return CheckResult("offline", error=str(exc), details={"path": path}, events=["file_missing"])
        details = _parse_key_values(result.stdout)
        if details.get("exists") == "no":
            return CheckResult("error", response_ms=result.elapsed_ms, error="File missing", details=details, events=["file_missing"])
        previous = monitor["config"].get("last_hash")
        changed = bool(previous and previous != details.get("hash"))
        details["last_hash"] = details.get("hash")
        return CheckResult("warning" if changed else "online", response_ms=result.elapsed_ms, content_changed=changed, content_hash=details.get("hash"), error="File hash changed" if changed else None, details=details, events=["file_hash_changed"] if changed else [])


class DirectorySizeMonitor(BackupMonitor):
    type = "directory_size"
    label = "Directory Size"
    category = "files"

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        path = monitor["config"]["path"]
        command = f"test -d {quote(path)} || {{ echo exists=no; exit 0; }}; echo exists=yes; du -sm {quote(path)} | awk '{{print \"size_mb=\"$1}}'"
        try:
            result = await run_ssh_command(monitor["config"], command)
        except Exception as exc:
            return CheckResult("offline", error=str(exc), details={"path": path}, events=["directory_size_warning"])
        details = _parse_key_values(result.stdout)
        size = _float(details.get("size_mb"))
        max_size = float(monitor["config"].get("max_size_mb") or 50000)
        status = "warning" if size > max_size else "online"
        return CheckResult(status, response_ms=result.elapsed_ms, error="Directory size threshold exceeded" if status == "warning" else None, details=details, events=["directory_size_warning"] if status == "warning" else [])


class DirectoryFileCountMonitor(BackupMonitor):
    type = "directory_file_count"
    label = "Directory File Count"
    category = "files"

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        path = monitor["config"]["path"]
        regex = monitor["config"].get("filename_regex") or ".*"
        command = f"test -d {quote(path)} || {{ echo exists=no; exit 0; }}; echo exists=yes; find {quote(path)} -type f | grep -E {quote(regex)} | wc -l | awk '{{print \"file_count=\"$1}}'"
        try:
            result = await run_ssh_command(monitor["config"], command)
        except Exception as exc:
            return CheckResult("offline", error=str(exc), details={"path": path}, events=["directory_file_count_warning"])
        details = _parse_key_values(result.stdout)
        count = int(_float(details.get("file_count")))
        max_count = int(monitor["config"].get("max_file_count") or 1000000)
        status = "warning" if count > max_count else "online"
        return CheckResult(status, response_ms=result.elapsed_ms, error="Directory file count threshold exceeded" if status == "warning" else None, details=details, events=["directory_file_count_warning"] if status == "warning" else [])


class LogRegexMonitor:
    type = "ssh_log_regex"
    label = "SSH Log Regex"
    category = "logs"
    default_interval = 300

    def validate(self, target: str, config: dict[str, Any], app_config: AppConfig) -> tuple[str, dict[str, Any]]:
        original_target = target
        target, config = normalize_ssh_config(target, config, app_config)
        config["path"] = str(config.get("path") or _target_suffix(original_target) or "/var/log/syslog").strip()
        config["regex"] = str(config.get("regex") or config.get("error_regex") or "error|failed").strip()
        config["warning_regex"] = str(config.get("warning_regex") or "warning").strip()
        config["error_regex"] = str(config.get("error_regex") or config["regex"]).strip()
        config["tail_lines"] = positive_int(config.get("tail_lines"), 500, 1, 10000)
        config["max_matches"] = positive_int(config.get("max_matches"), 20, 1, 1000)
        config["only_new_matches"] = bool(config.get("only_new_matches", True))
        return f"{config['host']}:{config['path']}", config

    async def check(self, monitor: dict[str, Any], context: MonitorContext) -> CheckResult:
        cfg = monitor["config"]
        command = self._command(cfg)
        try:
            result = await run_ssh_command(cfg, command)
        except Exception as exc:
            return CheckResult("offline", error=str(exc), details={"path": cfg.get("path")}, events=["log_error_match"])
        output_hash = hashlib.sha256(result.stdout.encode()).hexdigest()
        if cfg.get("only_new_matches") and cfg.get("last_output_hash") == output_hash:
            return CheckResult("online", response_ms=result.elapsed_ms, details={"match_count": 0, "last_output_hash": output_hash})
        matches = [line for line in result.stdout.splitlines() if line.strip()]
        details = {"match_count": len(matches), "matches": matches[: int(cfg.get("max_matches") or 20)], "last_output_hash": output_hash}
        if any(regex_matches(cfg.get("error_regex"), line) for line in matches):
            return CheckResult("error", response_ms=result.elapsed_ms, error="Log error regex matched", details=details, events=["log_error_match"])
        if any(regex_matches(cfg.get("warning_regex"), line) for line in matches):
            return CheckResult("warning", response_ms=result.elapsed_ms, error="Log warning regex matched", details=details, events=["log_warning_match"])
        if matches:
            return CheckResult("warning", response_ms=result.elapsed_ms, error="Log regex matched", details=details, events=["log_regex_match"])
        return CheckResult("online", response_ms=result.elapsed_ms, details=details)

    def _command(self, cfg: dict[str, Any]) -> str:
        return f"tail -n {int(cfg.get('tail_lines') or 500)} {quote(cfg.get('path'))} 2>/dev/null | grep -E {quote(cfg.get('regex'))} | tail -n {int(cfg.get('max_matches') or 20)} || true"


class JournaldRegexMonitor(LogRegexMonitor):
    type = "journald_regex"
    label = "Journald Regex"

    def _command(self, cfg: dict[str, Any]) -> str:
        return f"journalctl -n {int(cfg.get('tail_lines') or 500)} --no-pager 2>/dev/null | grep -E {quote(cfg.get('regex'))} | tail -n {int(cfg.get('max_matches') or 20)} || true"


class DockerLogRegexMonitor(LogRegexMonitor):
    type = "docker_log_regex"
    label = "Docker Log Regex"

    def _command(self, cfg: dict[str, Any]) -> str:
        container = quote(cfg.get("container_name") or cfg.get("path") or "")
        return f"docker logs --tail {int(cfg.get('tail_lines') or 500)} {container} 2>&1 | grep -E {quote(cfg.get('regex'))} | tail -n {int(cfg.get('max_matches') or 20)} || true"


def _docker_command(name: str, tail_lines: int) -> str:
    qname = quote(name)
    return "\n".join(
        [
            "docker info >/dev/null 2>&1 || { echo docker=unavailable; exit 0; }",
            "echo docker=ok",
            f"docker inspect {qname} >/dev/null 2>&1 || {{ echo exists=no; exit 0; }}",
            "echo exists=yes",
            f"docker inspect --format 'running={{{{.State.Status}}}}' {qname}",
            f"docker inspect --format 'restart_count={{{{.RestartCount}}}}' {qname}",
            f"docker inspect --format 'health={{{{if .State.Health}}}}{{{{.State.Health.Status}}}}{{{{else}}}}none{{{{end}}}}' {qname}",
            f"docker stats --no-stream --format 'cpu_percent={{{{.CPUPerc}}}}\\nmemory_percent={{{{.MemPerc}}}}' {qname} 2>/dev/null || true",
            f"printf 'logs<<MCLOG\\n'; docker logs --tail {tail_lines} {qname} 2>&1 || true; printf '\\nMCLOG\\n'",
        ]
    )


def _linux_host_command(services: str) -> str:
    return f"""
echo load1=$(awk '{{print $1}}' /proc/loadavg)
free | awk '/Mem:/ {{printf "memory_percent=%.1f\\n", $3*100/$2}} /Swap:/ {{if ($2>0) printf "swap_percent=%.1f\\n", $3*100/$2; else print "swap_percent=0"}}'
cut -d. -f1 /proc/uptime | awk '{{print "uptime_seconds="$1}}'
df -P / | awk 'NR==2 {{gsub("%","",$5); print "disk_percent="$5; print "disk_free_gb="$4/1024/1024}}'
df -Pi / | awk 'NR==2 {{gsub("%","",$5); print "inode_percent="$5}}'
ps -eo stat= | awk 'BEGIN {{z=0}} /^Z/ {{z++}} END {{print "zombie_processes="z}}'
ps -e --no-headers | wc -l | awk '{{print "process_count="$1}}'
test -f /var/run/reboot-required && echo reboot_required=yes || echo reboot_required=no
for t in /sys/class/thermal/thermal_zone*/temp; do test -r "$t" && awk '{{printf "temperature_c=%.1f\\n", $1/1000}}' "$t" && break; done
for svc in {services}; do systemctl is-active "$svc" 2>/dev/null | awk -v s="$svc" '{{print "service_"s"="$1}}'; done
"""


def _disk_command(mount: str) -> str:
    qmount = quote(mount)
    return f"""
test -d {qmount} || {{ echo exists=no; exit 0; }}
echo exists=yes
df -P {qmount} | awk 'NR==2 {{gsub("%","",$5); print "used_percent="$5; printf "free_gb=%.2f\\n", $4/1024/1024}}'
df -Pi {qmount} | awk 'NR==2 {{gsub("%","",$5); print "inode_used_percent="$5}}'
findmnt -no OPTIONS {qmount} 2>/dev/null | grep -qw ro && echo readonly=yes || echo readonly=no
"""


def _latest_file_command(path: str, regex: str) -> str:
    qpath = quote(path)
    qregex = quote(regex)
    return f"""
test -d {qpath} || {{ echo exists=no; exit 0; }}
line=$(find {qpath} -type f | grep -E {qregex} | while read -r f; do stat -c '%Y|%s|%n' "$f"; done | sort -nr | head -1)
test -n "$line" || {{ echo exists=no; exit 0; }}
echo exists=yes
echo "$line" | awk -F'|' '{{print "mtime_epoch="$1; printf "size_mb=%.2f\\n", $2/1024/1024; print "file="$3; printf "age_hours=%.2f\\n", (systime()-$1)/3600}}'
"""


def _linux_status(details: dict[str, Any], config: dict[str, Any]) -> tuple[str, str | None, list[str]]:
    if _float(details.get("load1")) >= float(config.get("cpu_load_error") or 8):
        return "error", "CPU load error threshold exceeded", ["linux_host_error"]
    if _float(details.get("memory_percent")) >= float(config.get("memory_error_percent") or 95):
        return "error", "Memory error threshold exceeded", ["linux_memory_warning", "linux_host_error"]
    if _float(details.get("disk_percent")) >= float(config.get("disk_error_percent") or 95):
        return "error", "Disk error threshold exceeded", ["linux_disk_warning", "linux_host_error"]
    failed_services = [key.removeprefix("service_") for key, value in details.items() if key.startswith("service_") and value != "active"]
    if failed_services:
        details["failed_services"] = failed_services
        return "error", "Systemd service failed", ["linux_service_failed", "linux_host_error"]
    if details.get("reboot_required") == "yes":
        return "warning", "Reboot required", ["linux_reboot_required", "linux_host_warning"]
    if _float(details.get("load1")) >= float(config.get("cpu_load_warning") or 4):
        return "warning", "CPU load warning threshold exceeded", ["linux_host_warning"]
    if _float(details.get("memory_percent")) >= float(config.get("memory_warning_percent") or 85):
        return "warning", "Memory warning threshold exceeded", ["linux_memory_warning", "linux_host_warning"]
    if _float(details.get("swap_percent")) >= float(config.get("swap_warning_percent") or 50):
        return "warning", "Swap warning threshold exceeded", ["linux_host_warning"]
    if _float(details.get("disk_percent")) >= float(config.get("disk_warning_percent") or 85):
        return "warning", "Disk warning threshold exceeded", ["linux_disk_warning", "linux_host_warning"]
    if _float(details.get("inode_percent")) >= float(config.get("inode_warning_percent") or 85):
        return "warning", "Inode warning threshold exceeded", ["linux_disk_warning", "linux_host_warning"]
    if _float(details.get("temperature_c")) >= float(config.get("temperature_error_c") or 85):
        return "error", "Temperature error threshold exceeded", ["linux_host_error"]
    if _float(details.get("temperature_c")) >= float(config.get("temperature_warning_c") or 70):
        return "warning", "Temperature warning threshold exceeded", ["linux_host_warning"]
    return "online", None, []


def _parse_key_values(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    lines = iter(text.splitlines())
    for line in lines:
        if line.endswith("<<MCLOG"):
            key = line.split("<<", 1)[0]
            block: list[str] = []
            for item in lines:
                if item == "MCLOG":
                    break
                block.append(item)
            result[key] = "\n".join(block)
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def _target_suffix(target: str) -> str:
    if target.count(":") != 1:
        return ""
    suffix = target.rsplit(":", 1)[1].strip()
    return "" if suffix.isdigit() else suffix


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _float(value: Any) -> float:
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return 0.0


def _percent(value: Any) -> float:
    return _float(value)
