"""Host router — overview, Docker info, live metrics."""

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from app.auth.handler import get_current_user
from app.config import get_settings
from app.schemas import DockerInfo, DockerDiskUsage, HostMetrics, HostListResponse, AppSummary
from app.services.snapshot import snapshot_manager

router = APIRouter(prefix="/api", tags=["hosts"], dependencies=[Depends(get_current_user)])


def _configured_app_placeholders(cfg) -> list[dict[str, Any]]:
    """Return app-profile placeholders used when a host has no live stack snapshot."""
    if not cfg.app_profiles:
        return []
    try:
        profiles = json.loads(cfg.app_profiles)
    except Exception:
        return []
    if not isinstance(profiles, list):
        return []

    stack_icons: dict[str, str] = {}
    if cfg.stack_icons:
        try:
            parsed_icons = json.loads(cfg.stack_icons)
            if isinstance(parsed_icons, dict):
                stack_icons = parsed_icons
        except Exception:
            stack_icons = {}

    def resolve_icon_url(icon_value: Any) -> str | None:
        if not isinstance(icon_value, str) or not icon_value:
            return None
        if icon_value.startswith(("http://", "https://", "/")):
            return icon_value
        return f"/api/static/icons/{icon_value.lstrip('/')}"

    placeholders: list[dict[str, Any]] = []
    seen: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        stack_pattern = str(profile.get("stack_pattern") or "").strip()
        if not stack_pattern or stack_pattern in seen:
            continue
        seen.add(stack_pattern)
        icon_url = resolve_icon_url(profile.get("icon_value"))
        if icon_url is None:
            icon_url = resolve_icon_url(snapshot_manager._match_icon(stack_pattern, stack_icons))
        placeholders.append({
            "stack_name": stack_pattern,
            "title": profile.get("title") or stack_pattern,
            "app_url": profile.get("app_url"),
            "group": profile.get("group") or "未分组",
            "icon_url": icon_url,
        })
    return placeholders


@router.get("/apps", response_model=list[AppSummary])
async def list_apps():
    """Aggregate all stacks from all host snapshots, enriched with app profile metadata."""
    snapshots = snapshot_manager.list_snapshots()
    apps = []
    for snap in snapshots:
        cfg = snap.host_config
        if not cfg or not cfg.enabled:
            continue

        stacks = list(snap.stacks)
        if not stacks:
            for app in _configured_app_placeholders(cfg):
                apps.append(
                    AppSummary(
                        host_id=cfg.host_id,
                        host_name=cfg.display_name or cfg.host_id,
                        host_status=snap.status,
                        stack_name=app["stack_name"],
                        status="unknown",
                        service_count=0,
                        running_count=0,
                        management_status="file-only",
                        title=app["title"],
                        app_url=app["app_url"],
                        group=app["group"],
                        icon_url=app["icon_url"],
                        services=[],
                        update_status="up_to_date",
                    )
                )
            continue

        for stack in stacks:
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
