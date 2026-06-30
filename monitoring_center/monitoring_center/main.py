from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .config import AppConfig
from .database import Database
from .ha import HomeAssistantClient
from .logging_config import configure_logging
from .migrations import migrate
from .monitoring import MonitorService
from .schemas import GroupIn, GroupUpdate, MaintenanceIn, MonitorIn, MonitorUpdate, SettingsIn

config = AppConfig.load()
configure_logging(config.log_level, config.log_file)
db = Database(config.database_path)
migrate(db)
ha = HomeAssistantClient(config)
service = MonitorService(db, config, ha)

app = FastAPI(title="Monitoring Center", version="0.4.1")
static_path = Path(__file__).resolve().parent.parent / "static"
scheduler_task: asyncio.Task[Any] | None = None


@app.on_event("startup")
async def startup() -> None:
    global scheduler_task
    scheduler_task = asyncio.create_task(service.scheduler())


@app.on_event("shutdown")
async def shutdown() -> None:
    service.stop()
    if scheduler_task:
        scheduler_task.cancel()
    db.close()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/summary")
async def summary() -> dict[str, Any]:
    return service.get_summary()


@app.get("/api/slo")
async def slo(group_id: int | None = None, monitor_id: int | None = None) -> dict[str, Any]:
    return service.get_slo_stats(group_id=group_id, monitor_id=monitor_id)


@app.get("/api/monitors")
async def monitors() -> list[dict[str, Any]]:
    return service.list_monitors()


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


@app.get("/api/history")
async def history(
    monitor_id: int | None = None,
    type: str | None = None,
    status: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = Query(default=250, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return service.get_history(
        {
            "monitor_id": monitor_id,
            "type": type,
            "status": status,
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


@app.get("/api/settings")
async def settings() -> dict[str, Any]:
    return service.get_settings()


@app.put("/api/settings")
async def update_settings(payload: SettingsIn) -> dict[str, Any]:
    return service.update_settings(payload.model_dump())


@app.get("/api/diagnostics")
async def diagnostics() -> dict[str, Any]:
    return service.diagnostics()


@app.get("/api/logs", response_class=PlainTextResponse)
async def logs(lines: int = Query(default=300, ge=1, le=2000)) -> str:
    if not config.log_file.exists():
        return ""
    content = config.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(static_path / "index.html")


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
