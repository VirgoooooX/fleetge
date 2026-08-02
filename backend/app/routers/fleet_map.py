"""Fleet Map snapshot, control-center settings, and location endpoints."""

from __future__ import annotations

import ipaddress
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
    location_for_host,
    search_location_names,
    suggest_location_from_ip,
)
from app.services.network_identity_service import (
    get_stored_network_identity,
    refresh_host_network_identity,
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
            "network_identity": get_stored_network_identity(host),
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
    host.location_confidence = "manual" if host.location_confirmed else None
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
    try:
        evidence = await refresh_host_network_identity(host_id, force=False)
    except LookupError:
        raise HTTPException(status_code=404, detail="Host not found")
    suggestion = evidence.get("locationSuggestion")
    if not suggestion:
        raise HTTPException(status_code=409, detail="公网 IP 证据未形成共识或地理数据库冲突；请检查探测依据或手动填写")
    session.add(AuditLog(user=username, action="host.location.suggest", host_id=host_id, result="success", detail=f"source={suggestion.get('source') or 'ip-geolocation'}", ip_address=request.client.host if request.client else None))
    session.commit()
    write_hosts_to_yaml()
    return {"host_id": host_id, "location": suggestion}


@admin_router.get("/hosts/{host_id}/network-identity")
async def get_host_network_identity(
    host_id: str,
    username: str = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _require_admin(username)
    host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
    if host is None:
        raise HTTPException(status_code=404, detail="Host not found")
    return {
        "host_id": host_id,
        "fixed_override": host.public_ip_override,
        "effective_ip": host.public_ip_effective,
        "effective_source": host.public_ip_source,
        "checked_at": host.network_identity_checked_at,
        "evidence": get_stored_network_identity(host),
    }


@admin_router.post("/hosts/{host_id}/network-identity/refresh")
async def refresh_network_identity(
    host_id: str,
    request: Request,
    force: bool = Query(True),
    username: str = Depends(get_current_user),
):
    _require_admin(username)
    try:
        evidence = await refresh_host_network_identity(host_id, force=force)
    except LookupError:
        raise HTTPException(status_code=404, detail="Host not found")
    with Session(engine) as session:
        session.add(AuditLog(
            user=username,
            action="host.network_identity.refresh",
            host_id=host_id,
            result="success",
            detail=f"confidence={evidence.get('confidence')}",
            ip_address=request.client.host if request.client else None,
        ))
        session.commit()
    write_hosts_to_yaml()
    return evidence


@admin_router.put("/hosts/{host_id}/network-identity/override")
async def update_network_identity_override(
    host_id: str,
    body: dict,
    request: Request,
    username: str = Depends(get_current_user),
):
    _require_admin(username)
    raw = str(body.get("ip") or "").strip()
    normalized = None
    if raw:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid public IP address")
        if not address.is_global:
            raise HTTPException(status_code=400, detail="Override must be a public IP address")
        normalized = address.compressed
    with Session(engine) as session:
        host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
        if host is None:
            raise HTTPException(status_code=404, detail="Host not found")
        host.public_ip_override = normalized
        session.add(host)
        session.add(AuditLog(
            user=username,
            action="host.network_identity.override",
            host_id=host_id,
            result="success",
            detail="set" if normalized else "cleared",
            ip_address=request.client.host if request.client else None,
        ))
        session.commit()
    evidence = await refresh_host_network_identity(host_id, force=True)
    write_hosts_to_yaml()
    return evidence
