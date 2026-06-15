"""Host router — overview, Docker info, metrics."""

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from app.auth.handler import get_current_user
from app.config import get_settings
from app.schemas import DockerInfo, DockerDiskUsage, HostMetrics, HostListResponse
from app.services.snapshot import snapshot_manager

router = APIRouter(prefix="/api", tags=["hosts"], dependencies=[Depends(get_current_user)])


@router.get("/hosts", response_model=HostListResponse)
async def list_hosts():
    """Return a summary of all configured hosts with live status and metrics."""
    snapshots = snapshot_manager.list_snapshots()
    summaries = [snapshot_manager.build_host_summary(s) for s in snapshots]
    return HostListResponse(hosts=summaries)


@router.post("/hosts/refresh", response_model=HostListResponse)
async def refresh_hosts_structure():
    """Refresh Docker/Dockge structure for all hosts on frontend demand."""
    summaries = await snapshot_manager.refresh_all_structure_now()
    return HostListResponse(hosts=summaries)


@router.post("/hosts/{host_id}/refresh", response_model=dict)
async def refresh_host_structure(host_id: str):
    """Refresh Docker/Dockge structure for one host on frontend demand."""
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
    """Return host metrics from the host-metrics exporter."""
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

    return StreamingResponse(generate(), media_type="text/event-stream")
