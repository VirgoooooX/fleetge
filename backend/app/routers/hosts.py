"""Host router — overview, Docker info, live metrics."""

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from app.auth.handler import get_current_user
from app.config import get_settings
from app.schemas import DockerInfo, DockerDiskUsage, HostMetrics, HostListResponse, AppSummary
from app.services.snapshot import snapshot_manager

router = APIRouter(prefix="/api", tags=["hosts"], dependencies=[Depends(get_current_user)])


@router.get("/apps", response_model=list[AppSummary])
async def list_apps():
    """Aggregate all stacks from all host snapshots, enriched with app profile metadata."""
    snapshots = snapshot_manager.list_snapshots()
    apps = []
    for snap in snapshots:
        cfg = snap.host_config
        if not cfg or not cfg.enabled:
            continue
        
        for stack in snap.stacks:
            # Determine update_status
            update_status = "up_to_date"
            stack_containers = [
                c for c in snap.containers
                if c.stack_name == stack.name and c.image
            ]
            for c in stack_containers:
                status = snap.update_results.get(c.image)
                if status == "updatable":
                    update_status = "updatable"
                    break
            
            apps.append(
                AppSummary(
                    host_id=cfg.host_id,
                    host_name=cfg.display_name or cfg.host_id,
                    host_status=snap.status,
                    stack_name=stack.name,
                    status=stack.status,
                    service_count=stack.service_count,
                    running_count=stack.running_count,
                    management_status=stack.management_status,
                    title=stack.title,
                    app_url=stack.app_url,
                    group=stack.group,
                    icon_url=stack.icon_url,
                    services=stack.services,
                    update_status=update_status,
                )
            )
    return apps


@router.get("/hosts", response_model=HostListResponse)
async def list_hosts():
    """Return a summary of all configured hosts with live status and metrics."""
    snapshots = snapshot_manager.list_snapshots()
    summaries = [snapshot_manager.build_host_summary(s) for s in snapshots]
    return HostListResponse(hosts=summaries)


@router.post("/hosts/refresh", response_model=HostListResponse)
async def refresh_hosts_structure():
    """Refresh Docker/Agent structure for all hosts on frontend demand."""
    summaries = await snapshot_manager.refresh_all_structure_now()
    return HostListResponse(hosts=summaries)


@router.get("/hosts/{host_id}", response_model=dict)
async def get_host_details(host_id: str):
    """Return cached Docker/Agent structure and stats for one host instantly."""
    await snapshot_manager.refresh_hosts()
    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    host = snapshot_manager.build_host_summary(snap)
    return {
        "host": host.model_dump(),
        "stacks": [stack.model_dump() for stack in snap.stacks],
        "containers": [container.model_dump() for container in snap.containers],
        "container_stats": {
            cid: stats.model_dump()
            for cid, stats in snap.container_stats.items()
        },
    }


@router.post("/hosts/{host_id}/refresh", response_model=dict)
async def refresh_host_structure(host_id: str):
    """Refresh Docker/Agent structure for one host on frontend demand."""
    snap = await snapshot_manager.refresh_host_structure_now(host_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    host = snapshot_manager.build_host_summary(snap)
    return {
        "host": host.model_dump(),
        "stacks": [stack.model_dump() for stack in snap.stacks],
        "containers": [container.model_dump() for container in snap.containers],
        "container_stats": {
            cid: stats.model_dump()
            for cid, stats in snap.container_stats.items()
        },
    }


@router.get("/hosts/{host_id}/docker", response_model=dict)
async def host_docker_info(host_id: str):
    """Return Docker /info and /system/df for a specific host."""
    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    return {
        "info": snap.docker_info.model_dump() if snap.docker_info else None,
        "disk_usage": snap.docker_disk.model_dump() if snap.docker_disk else None,
        "status": snap.status,
    }


@router.get("/hosts/{host_id}/metrics", response_model=dict)
async def host_metrics(host_id: str):
    """Return host metrics from the Fleetge Agent."""
    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    return {
        "metrics": snap.metrics.model_dump() if snap.metrics else None,
        "updated": snap.metrics_updated,
        "status": snap.status,
    }


def _sse_event(event: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


@router.get("/hosts/metrics/stream")
async def host_metrics_stream():
    """Stream refreshed host metrics for live dashboard cards."""
    settings = get_settings()
    interval = max(settings.METRICS_STREAM_INTERVAL, 0.5)

    async def generate():
        snapshot_manager.increment_connections()
        try:
            while True:
                summaries = await snapshot_manager.refresh_metrics_now()
                yield _sse_event(
                    "hosts",
                    {
                        "hosts": [summary.model_dump() for summary in summaries],
                        "updated": time.time(),
                    },
                )
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        finally:
            snapshot_manager.decrement_connections()

    return StreamingResponse(generate(), media_type="text/event-stream")
