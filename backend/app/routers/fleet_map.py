"""Fleet Map snapshot, control-center settings, and location endpoints."""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from app.auth.handler import get_current_user
from app.config import get_settings
from app.database import engine, get_session
from app.models import AuditLog, HostConfig, Setting
from app.schemas import FleetMapSettingsRequest, HostLocationRequest
from app.services.enrollment_service import (
    candidate_host_ip,
    is_private_host,
    location_for_host,
    search_location_names,
    suggest_location_from_ip,
)
from app.services.host_writer import write_hosts_to_yaml
from app.services.snapshot import snapshot_manager

router = APIRouter(prefix="/api", tags=["fleet-map"], dependencies=[Depends(get_current_user)])
admin_router = APIRouter(prefix="/api/admin", tags=["fleet-map"], dependencies=[Depends(get_current_user)])


def _require_admin(username: str) -> None:
    if username != get_settings().ADMIN_USERNAME:
        raise HTTPException(status_code=403, detail="Administrator access required")


def _setting(session: Session, key: str, default: str = "") -> str:
    row = session.exec(select(Setting).where(Setting.setting_key == key)).first()
    return row.setting_value if row else default


def _set_setting(session: Session, key: str, value: str) -> None:
    row = session.exec(select(Setting).where(Setting.setting_key == key)).first()
    if row:
        row.setting_value = value
    else:
        session.add(Setting(setting_key=key, setting_value=value))


def _center_settings(session: Session) -> dict[str, Any]:
    return {
        "name": _setting(session, "FLEET_MAP_CENTER_NAME", "Fleetge Control Center"),
        "city": _setting(session, "FLEET_MAP_CENTER_CITY", "") or None,
        "region": _setting(session, "FLEET_MAP_CENTER_REGION", "") or None,
        "country": _setting(session, "FLEET_MAP_CENTER_COUNTRY", "") or None,
        "country_code": _setting(session, "FLEET_MAP_CENTER_COUNTRY_CODE", "") or None,
        "latitude": float(_setting(session, "FLEET_MAP_CENTER_LATITUDE", "0") or 0),
        "longitude": float(_setting(session, "FLEET_MAP_CENTER_LONGITUDE", "0") or 0),
        "confirmed": _setting(session, "FLEET_MAP_CENTER_CONFIRMED", "false").lower() == "true",
    }


def _service_rows(snap, stack_name: str) -> list[dict[str, Any]]:
    rows = []
    for container in snap.containers:
        if container.stack_name != stack_name:
            continue
        rows.append(
            {
                "name": container.service_name or container.name,
                "container_id": container.id,
                "state": container.state,
                "status": container.status,
                "health": container.health,
            }
        )
    return rows


@router.get("/fleet-map")
async def fleet_map_snapshot():
    snapshots = {snap.host_config.host_id: snap for snap in snapshot_manager.list_snapshots() if snap.host_config}
    with Session(engine) as session:
        hosts = session.exec(select(HostConfig).order_by(HostConfig.sort_order, HostConfig.id)).all()
        center = _center_settings(session)

    nodes: list[dict[str, Any]] = []
    for host in hosts:
        snap = snapshots.get(host.host_id)
        summary = snapshot_manager.build_host_summary(snap).model_dump() if snap else None
        stacks = []
        if snap:
            for stack in snap.stacks:
                services = _service_rows(snap, stack.name)
                stacks.append(
                    {
                        "name": stack.name,
                        "status": stack.status,
                        "service_count": stack.service_count or len(services),
                        "running_count": stack.running_count or sum(1 for s in services if s["state"] == "running"),
                        "services": services or [service.model_dump() for service in stack.services],
                    }
                )
        node = {
            "host_id": host.host_id,
            "display_name": host.display_name or host.host_id,
            "enabled": host.enabled,
            "status": summary.get("status") if summary else (host.status or "unknown"),
            "metrics": summary.get("metrics") if summary else None,
            "container_count": summary.get("container_total", 0) if summary else 0,
            "last_seen": host.last_seen.isoformat() if host.last_seen else None,
            "error_message": summary.get("error_message") if summary else host.error_message,
            "agent_instance_id": host.agent_instance_id,
            "location": location_for_host(host),
            "stacks": stacks,
        }
        nodes.append(node)

    status_counts = {
        "total": len(nodes),
        "online": sum(1 for n in nodes if n["status"] == "online"),
        "degraded": sum(1 for n in nodes if n["status"] == "degraded"),
        "offline": sum(1 for n in nodes if n["status"] in {"offline", "unknown"}),
        "unlocated": sum(1 for n in nodes if not n["location"]),
    }
    return {"center": center, "hosts": nodes, "counts": status_counts, "updated_at": datetime.now(timezone.utc).isoformat()}


@admin_router.get("/fleet-map/settings")
async def get_fleet_map_settings(username: str = Depends(get_current_user), session: Session = Depends(get_session)):
    _require_admin(username)
    return _center_settings(session)


@admin_router.post("/fleet-map/settings/suggest")
async def suggest_fleet_map_settings(request: Request, username: str = Depends(get_current_user)):
    _require_admin(username)
    # Resolve the Dashboard server's public egress, rather than the
    # administrator's browser IP forwarded by a reverse proxy.
    suggestion = await suggest_location_from_ip(None)
    if not suggestion:
        raise HTTPException(status_code=409, detail="控制中心位置建议不可用；请手动填写")
    return suggestion


@admin_router.get("/location/search")
async def search_locations(
    q: str = Query(..., min_length=2, max_length=120),
    language: str = Query("zh", min_length=2, max_length=8),
    username: str = Depends(get_current_user),
):
    _require_admin(username)
    return {"results": await search_location_names(q, language)}


@admin_router.put("/fleet-map/settings")
async def update_fleet_map_settings(
    req: FleetMapSettingsRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    _require_admin(username)
    if not (-90 <= req.latitude <= 90 and -180 <= req.longitude <= 180):
        raise HTTPException(status_code=400, detail="Coordinates are out of range")
    _set_setting(session, "FLEET_MAP_CENTER_NAME", req.name.strip()[:120] or "Fleetge Control Center")
    _set_setting(session, "FLEET_MAP_CENTER_CITY", (req.city or "").strip()[:120])
    _set_setting(session, "FLEET_MAP_CENTER_REGION", (req.region or "").strip()[:120])
    _set_setting(session, "FLEET_MAP_CENTER_COUNTRY", (req.country or "").strip()[:120])
    _set_setting(session, "FLEET_MAP_CENTER_COUNTRY_CODE", (req.country_code or "").strip().upper()[:8])
    _set_setting(session, "FLEET_MAP_CENTER_LATITUDE", str(req.latitude))
    _set_setting(session, "FLEET_MAP_CENTER_LONGITUDE", str(req.longitude))
    _set_setting(session, "FLEET_MAP_CENTER_CONFIRMED", str(bool(req.confirmed)).lower())
    session.add(AuditLog(user=username, action="fleet-map.settings.update", result="success", detail="center updated", ip_address=request.client.host if request.client else None))
    session.commit()
    return {
        "name": req.name.strip()[:120] or "Fleetge Control Center",
        "city": (req.city or "").strip()[:120] or None,
        "region": (req.region or "").strip()[:120] or None,
        "country": (req.country or "").strip()[:120] or None,
        "country_code": (req.country_code or "").strip().upper()[:8] or None,
        "latitude": req.latitude,
        "longitude": req.longitude,
        "confirmed": req.confirmed,
    }


@admin_router.put("/hosts/{host_id}/location")
async def update_host_location(
    host_id: str,
    req: HostLocationRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    _require_admin(username)
    if req.latitude is None or req.longitude is None or not (-90 <= req.latitude <= 90 and -180 <= req.longitude <= 180):
        raise HTTPException(status_code=400, detail="Valid latitude and longitude are required")
    host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
    if host is None:
        raise HTTPException(status_code=404, detail="Host not found")
    host.location_latitude = req.latitude
    host.location_longitude = req.longitude
    host.location_city = (req.city or "").strip()[:120] or None
    host.location_region = (req.region or "").strip()[:120] or None
    host.location_country = (req.country or "").strip()[:120] or None
    host.location_country_code = (req.country_code or "").strip().upper()[:8] or None
    host.location_source = req.source or "manual"
    host.location_confirmed = bool(req.confirmed)
    session.add(AuditLog(user=username, action="host.location.update", host_id=host_id, result="success", detail=f"source={host.location_source}", ip_address=request.client.host if request.client else None))
    session.commit()
    write_hosts_to_yaml()
    return {"host_id": host_id, "location": location_for_host(host)}


@admin_router.post("/hosts/{host_id}/location/suggest")
async def suggest_host_location(
    host_id: str,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    _require_admin(username)
    host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
    if host is None:
        raise HTTPException(status_code=404, detail="Host not found")
    ip = candidate_host_ip(host.agent_url)
    if not ip:
        try:
            parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(host.agent_url or "")
            hostname = parsed.hostname
            if hostname:
                ip = next(
                    (item[4][0] for item in socket.getaddrinfo(hostname, None)
                     if "." in item[4][0] and not is_private_host(item[4][0])),
                    None,
                )
        except Exception:
            ip = None
    suggestion = await suggest_location_from_ip(ip)
    if not suggestion:
        raise HTTPException(status_code=409, detail="Location suggestion unavailable; enter coordinates manually")
    host.location_latitude = suggestion["latitude"]
    host.location_longitude = suggestion["longitude"]
    host.location_city = suggestion.get("city")
    host.location_region = suggestion.get("region")
    host.location_country = suggestion.get("country")
    host.location_country_code = suggestion.get("country_code")
    host.location_source = suggestion.get("source") or "ipwho.is"
    host.location_confirmed = False
    session.add(AuditLog(user=username, action="host.location.suggest", host_id=host_id, result="success", detail=f"source={host.location_source}", ip_address=request.client.host if request.client else None))
    session.commit()
    write_hosts_to_yaml()
    return {"host_id": host_id, "location": suggestion}
