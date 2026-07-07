from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import AppConfig
from .database import Database
from .ha import HomeAssistantClient
from .logging_config import configure_logging
from .migrations import migrate
from .monitoring import MonitorService
from .schemas import (
    DiscoveryImportIn,
    DiscoveryScanIn,
    GroupIn,
    GroupUpdate,
    MaintenanceIn,
    MonitorIn,
    MonitorsImportIn,
    MonitorUpdate,
    SettingsIn,
    TopologyIn,
)

config = AppConfig.load()
configure_logging(config.log_level, config.log_file)
db = Database(config.database_path)
migrate(db)
ha = HomeAssistantClient(config)
service = MonitorService(db, config, ha)

scheduler_task: asyncio.Task[Any] | None = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global scheduler_task
    scheduler_task = asyncio.create_task(service.scheduler())
    try:
        yield
    finally:
        service.stop()
        if scheduler_task:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
        scheduler_task = None
        db.close()


app = FastAPI(title="Monitoring Center", version=__version__, lifespan=lifespan)
static_path = Path(__file__).resolve().parent.parent / "static"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, Any]:
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
    monitors = await service.create_monitors_bulk([monitor.model_dump() for monitor in payload.monitors])
    return {"created": len(monitors), "monitors": monitors}


@app.post("/api/discovery/scan")
async def discovery_scan(payload: DiscoveryScanIn) -> list[dict[str, Any]]:
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
async def check_monitor(monitor_id: int) -> dict[str, Any]:
    try:
        return await service.run_check(monitor_id)
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


@app.get("/api/settings")
async def settings() -> dict[str, Any]:
    return service.get_settings()


@app.put("/api/settings")
async def update_settings(payload: SettingsIn) -> dict[str, Any]:
    return service.update_settings(payload.model_dump())


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
        {**node, "type": payload.nodes[index].normalized_type()}
        for index, node in enumerate(data["nodes"])
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
    content = config.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


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
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
