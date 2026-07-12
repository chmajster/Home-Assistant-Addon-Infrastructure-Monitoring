from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Any, cast

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import AppConfig
from .database import Database
from .ha import HomeAssistantClient
from .logging_config import configure_logging
from .migrations import migrate
from .monitoring import MonitorService
from .schemas import (
    CredentialCreate,
    CredentialUpdate,
    DiscoveryImportIn,
    DiscoveryScanIn,
    GroupIn,
    GroupUpdate,
    IncidentActionIn,
    MaintenanceIn,
    MonitorIn,
    MonitorsImportIn,
    MonitorUpdate,
    Page,
    SettingsIn,
    TopologyIn,
)
from .secret_store import SecretStore, SecretStoreError
from .security import sanitize_secrets

LOGGER = logging.getLogger(__name__)
config = cast(AppConfig, None)
db = cast(Database, None)
ha = cast(HomeAssistantClient, None)
service = cast(MonitorService, None)
scheduler_task: asyncio.Task[Any] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global config, db, ha, scheduler_task, service
    config = AppConfig.load()
    configure_logging(config.log_level, config.log_file)
    db = Database(config.database_path)
    migrate(db)
    try:
        secrets = SecretStore(db, config.database_path.parent / "monitoring_center.key")
        ha = HomeAssistantClient(config)
        service = MonitorService(db, config, ha, secrets)
    except SecretStoreError as exc:
        app.state.config = config
        app.state.db = db
        app.state.ready_error = str(exc)
        LOGGER.error("SecretStore not ready: %s", exc)
        try:
            yield
        finally:
            db.close()
        return
    except Exception:
        db.close()
        raise
    scheduler_task = asyncio.create_task(service.scheduler(), name="monitoring-scheduler")
    app.state.config = config
    app.state.db = db
    app.state.ha = ha
    app.state.service = service
    app.state.scheduler_task = scheduler_task
    app.state.ready_error = None
    try:
        yield
    finally:
        service.stop()
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler_task
        await service.wait_for_tasks()
        await ha.close()
        db.checkpoint(truncate=True)
        db.optimize()
        db.close()
        scheduler_task = None


def create_app() -> FastAPI:
    return FastAPI(title="Monitoring Center", version=__version__, lifespan=lifespan)


app = create_app()
static_path = Path(__file__).resolve().parent.parent / "static"


def _service(request: Request | None = None) -> MonitorService:
    target = request.app if request else app
    service = getattr(target.state, "service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Aplikacja nie jest gotowa")
    return service


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error_id = uuid.uuid4().hex
    LOGGER.exception(
        "Nieobsłużony błąd API id=%s path=%s detail=%s", error_id, request.url.path, sanitize_secrets(str(exc))
    )
    return JSONResponse(
        status_code=500,
        content={"error": {"id": error_id, "code": "internal_error", "message": "Wewnętrzny błąd serwera"}},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, Any]:
    ready_error = getattr(app.state, "ready_error", None)
    if ready_error:
        return {
            "status": "not_ready",
            "database": True,
            "data_dir_writable": os.access(config.database_path.parent, os.W_OK),
            "scheduler": False,
            "schema_version": None,
            "reason": ready_error,
        }
    diagnostics = service.diagnostics()
    data_dir = config.database_path.parent
    writable = os.access(data_dir, os.W_OK)
    scheduler_running = scheduler_task is not None and not scheduler_task.done()
    return {
        "status": "ready" if diagnostics["database_exists"] and writable and scheduler_running else "not_ready",
        "database": diagnostics["database_exists"],
        "data_dir_writable": writable,
        "scheduler": scheduler_running,
        "schema_version": diagnostics.get("schema_version"),
    }


@app.get("/api/summary")
async def summary() -> dict[str, Any]:
    return service.get_summary()


@app.get("/api/bootstrap")
async def bootstrap() -> dict[str, Any]:
    return service.get_bootstrap()


@app.get("/api/slo")
async def slo(group_id: int | None = None, monitor_id: int | None = None) -> dict[str, Any]:
    return service.get_slo_stats(group_id=group_id, monitor_id=monitor_id)


@app.get("/api/monitors")
async def monitors() -> list[dict[str, Any]]:
    return service.list_monitors()


@app.get("/api/monitors/{monitor_id}")
async def get_monitor(monitor_id: int) -> dict[str, Any]:
    try:
        return service.get_monitor(monitor_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Monitor not found") from exc


@app.get("/api/monitor-types")
async def monitor_types() -> list[dict[str, Any]]:
    return service.get_monitor_types()


@app.get("/api/presets")
async def presets() -> list[dict[str, Any]]:
    return service.get_presets()


@app.get("/api/credentials")
async def credentials() -> list[dict[str, Any]]:
    return service.list_credentials()


@app.get("/api/credentials/{credential_id}")
async def get_credential(credential_id: int) -> dict[str, Any]:
    try:
        return service.get_credential(credential_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profil danych dostępowych nie istnieje") from exc


@app.post("/api/credentials")
async def create_credential(payload: CredentialCreate) -> dict[str, Any]:
    return service.create_credential(payload.model_dump())


@app.put("/api/credentials/{credential_id}")
async def update_credential(credential_id: int, payload: CredentialUpdate) -> dict[str, Any]:
    try:
        return service.update_credential(credential_id, payload.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profil danych dostępowych nie istnieje") from exc


@app.delete("/api/credentials/{credential_id}")
async def delete_credential(credential_id: int) -> dict[str, str]:
    try:
        service.delete_credential(credential_id)
        return {"status": "deleted"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profil danych dostępowych nie istnieje") from exc


@app.get("/api/groups")
async def groups() -> list[dict[str, Any]]:
    return service.list_groups()


@app.post("/api/groups")
async def create_group(payload: GroupIn) -> dict[str, Any]:
    return service.create_group(payload.model_dump())


@app.put("/api/groups/{group_id}")
async def update_group(group_id: int, payload: GroupUpdate) -> dict[str, Any]:
    try:
        return service.update_group(group_id, payload.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc


@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: int) -> dict[str, str]:
    service.delete_group(group_id)
    return {"status": "deleted"}


@app.post("/api/groups/{group_id}/maintenance")
async def set_group_maintenance(group_id: int, payload: MaintenanceIn) -> dict[str, Any]:
    try:
        return service.set_group_maintenance(group_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc


@app.delete("/api/groups/{group_id}/maintenance")
async def clear_group_maintenance(group_id: int) -> dict[str, Any]:
    try:
        return service.clear_group_maintenance(group_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc


@app.post("/api/monitors")
async def create_monitor(payload: MonitorIn) -> dict[str, Any]:
    return await service.create_monitor(payload.model_dump())


@app.post("/api/monitors/test")
async def test_monitor(payload: MonitorIn) -> dict[str, Any]:
    return await service.test_monitor(payload.model_dump())


@app.post("/api/monitors/import")
async def import_monitors(payload: MonitorsImportIn) -> dict[str, Any]:
    values = [monitor.model_dump() for monitor in payload.monitors]
    warnings: list[str] = []
    for index, monitor in enumerate(values):
        credential_id = monitor.get("credential_id")
        if credential_id is None:
            continue
        try:
            service.get_credential(int(credential_id))
        except KeyError:
            monitor["credential_id"] = None
            warnings.append(f"Monitor {index + 1}: pominięto nieistniejący profil danych dostępowych {credential_id}")
    monitors = await service.create_monitors_bulk(values)
    return {"created": len(monitors), "monitors": monitors, "warnings": warnings}


@app.post("/api/discovery/scan")
async def discovery_scan(payload: DiscoveryScanIn) -> dict[str, Any]:
    data = payload.model_dump()
    data["sources"] = payload.normalized_sources()
    return await service.scan_discovery(data)


@app.post("/api/discovery/import")
async def discovery_import(payload: DiscoveryImportIn) -> dict[str, Any]:
    monitors = await service.import_discovery([monitor.model_dump() for monitor in payload.monitors])
    return {"created": len(monitors), "monitors": monitors}


@app.put("/api/monitors/{monitor_id}")
async def update_monitor(monitor_id: int, payload: MonitorUpdate) -> dict[str, Any]:
    try:
        data = payload.model_dump(exclude_unset=True)
        return await service.update_monitor(monitor_id, data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Monitor not found") from exc


@app.delete("/api/monitors/{monitor_id}")
async def delete_monitor(monitor_id: int) -> dict[str, str]:
    try:
        service.delete_monitor(monitor_id)
        return {"status": "deleted"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Monitor not found") from exc


@app.post("/api/monitors/{monitor_id}/check")
async def check_monitor(monitor_id: int, force: bool = False) -> dict[str, Any]:
    try:
        return await service.run_check(monitor_id, force=force)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Monitor not found") from exc


@app.post("/api/monitors/{monitor_id}/enable")
async def enable_monitor(monitor_id: int) -> dict[str, Any]:
    try:
        return service.set_monitor_enabled(monitor_id, True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Monitor not found") from exc


@app.post("/api/monitors/{monitor_id}/disable")
async def disable_monitor(monitor_id: int) -> dict[str, Any]:
    try:
        return service.set_monitor_enabled(monitor_id, False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Monitor not found") from exc


@app.post("/api/monitors/{monitor_id}/maintenance")
async def set_monitor_maintenance(monitor_id: int, payload: MaintenanceIn) -> dict[str, Any]:
    try:
        return service.set_monitor_maintenance(monitor_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Monitor not found") from exc


@app.delete("/api/monitors/{monitor_id}/maintenance")
async def clear_monitor_maintenance(monitor_id: int) -> dict[str, Any]:
    try:
        return service.clear_monitor_maintenance(monitor_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Monitor not found") from exc


@app.get("/api/monitors/{monitor_id}/snapshots")
async def snapshots(monitor_id: int) -> list[dict[str, Any]]:
    return service.get_snapshots(monitor_id)


@app.get("/api/monitors/{monitor_id}/timeline")
async def monitor_timeline(
    monitor_id: int,
    limit: int = Query(default=120, ge=1, le=500),
) -> list[dict[str, Any]]:
    try:
        return service.get_monitor_timeline(monitor_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Monitor not found") from exc


@app.get("/api/history")
async def history(
    monitor_id: int | None = None,
    type: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = Query(default=250, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return service.get_history(
        {
            "monitor_id": monitor_id,
            "type": type,
            "status": status,
            "severity": severity,
            "from_date": from_date,
            "to_date": to_date,
            "limit": limit,
        }
    )


@app.delete("/api/history")
async def cleanup_history() -> dict[str, str]:
    await service.cleanup_history()
    return {"status": "cleaned"}


@app.get("/api/events")
async def events() -> list[dict[str, Any]]:
    return service.get_events()


@app.get("/api/incidents")
async def incidents(
    monitor_id: int | None = None,
    active_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return service.list_incidents(limit=limit, active_only=active_only, monitor_id=monitor_id)


@app.post("/api/incidents/{incident_id}/acknowledge")
async def acknowledge_incident(incident_id: int, payload: IncidentActionIn) -> dict[str, Any]:
    return service.update_incident(incident_id, "acknowledged", payload.comment)


@app.post("/api/incidents/{incident_id}/close")
async def close_incident(incident_id: int, payload: IncidentActionIn) -> dict[str, Any]:
    return service.update_incident(incident_id, "closed", payload.comment)


@app.get("/api/v2/history", response_model=Page)
async def history_page(
    monitor_id: int | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    return service.get_cursor_page("history", limit, cursor, monitor_id=monitor_id, status=status)


@app.get("/api/v2/events", response_model=Page)
async def events_page(cursor: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return service.get_cursor_page("events", limit, cursor)


@app.get("/api/v2/incidents", response_model=Page)
async def incidents_page(
    monitor_id: int | None = None,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    return service.get_cursor_page("incidents", limit, cursor, monitor_id=monitor_id)


@app.get("/api/v2/monitors", response_model=Page)
async def monitors_page(cursor: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return service.get_cursor_page("monitors", limit, cursor)


@app.get("/api/v2/monitors/{monitor_id}/snapshots", response_model=Page)
async def snapshots_page(
    monitor_id: int, cursor: str | None = None, limit: int = Query(default=100, ge=1, le=500)
) -> dict[str, Any]:
    return service.get_cursor_page("snapshots", limit, cursor, monitor_id=monitor_id)


@app.get("/api/settings")
async def settings() -> dict[str, Any]:
    return service.get_settings()


@app.put("/api/settings")
async def update_settings(payload: SettingsIn) -> dict[str, Any]:
    return service.update_settings(payload.model_dump(exclude_none=True))


@app.get("/api/diagnostics")
async def diagnostics() -> dict[str, Any]:
    return service.diagnostics()


@app.get("/api/topology")
async def get_topology() -> dict[str, Any]:
    return service.get_topology()


@app.put("/api/topology")
async def put_topology(payload: TopologyIn) -> dict[str, Any]:
    data = payload.model_dump()
    data["nodes"] = [
        {**node, "type": payload.nodes[index].normalized_type()} for index, node in enumerate(data["nodes"])
    ]
    return service.save_topology(data)


@app.post("/api/topology/auto-layout")
async def topology_auto_layout() -> dict[str, Any]:
    return service.auto_layout_topology()


@app.get("/api/diagnostics/full")
async def diagnostics_full() -> dict[str, Any]:
    data = await service.full_diagnostics()
    data["ready"] = await ready()
    return data


@app.post("/api/diagnostics/self-check")
async def diagnostics_self_check() -> dict[str, Any]:
    return await service.run_self_check()


@app.get("/api/logs", response_class=PlainTextResponse)
async def logs(lines: int = Query(default=300, ge=1, le=2000)) -> str:
    if not config.log_file.exists():
        return ""
    with config.log_file.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        chunks: list[bytes] = []
        newline_count = 0
        while position > 0 and newline_count <= lines:
            size = min(8192, position)
            position -= size
            handle.seek(position)
            chunk = handle.read(size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")
    return "\n".join(b"".join(reversed(chunks)).decode("utf-8", errors="replace").splitlines()[-lines:])


@app.post("/api/database/backups")
async def create_database_backup() -> dict[str, Any]:
    stamp = uuid.uuid4().hex[:8]
    schema = db.fetchone("SELECT MAX(version) AS version FROM schema_migrations") or {"version": 0}
    destination = db.path.parent / f"monitoring-center.schema-{schema['version']}.{stamp}.sqlite"
    db.backup(destination)
    return {"name": destination.name, "size": destination.stat().st_size, "schema_version": schema["version"]}


@app.get("/api/database/backups/{name}")
async def download_database_backup(name: str) -> FileResponse:
    safe_name = Path(name).name
    if safe_name != name or not safe_name.startswith("monitoring-center.schema-"):
        raise HTTPException(status_code=404, detail="Backup nie istnieje")
    path = db.path.parent / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Backup nie istnieje")
    return FileResponse(path, filename=safe_name)


@app.post("/api/database/restore")
async def restore_database(confirm: bool, backup: Annotated[UploadFile, File()]) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(status_code=409, detail="Restore wymaga jawnego potwierdzenia")
    temporary = db.path.parent / f"restore-{uuid.uuid4().hex}.sqlite"
    try:
        with temporary.open("wb") as handle:
            while chunk := await backup.read(1024 * 1024):
                handle.write(chunk)
        before = db.path.parent / f"monitoring-center.pre-restore-{uuid.uuid4().hex[:8]}.sqlite"
        db.backup(before)
        db.restore(temporary)
        migrate(db)
        return {"status": "restored", "safety_backup": before.name}
    finally:
        temporary.unlink(missing_ok=True)


app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        static_path / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


def main() -> None:
    uvicorn.run(
        app,
        host=os.environ.get("MONITORING_CENTER_HOST", "0.0.0.0"),
        port=int(os.environ.get("MONITORING_CENTER_PORT", "8099")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("MONITORING_CENTER_TRUSTED_PROXIES", "127.0.0.1,::1,172.30.32.2"),
    )


if __name__ == "__main__":
    main()
