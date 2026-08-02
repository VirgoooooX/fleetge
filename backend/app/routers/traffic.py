"""Authenticated Host WAN traffic APIs."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.auth.handler import get_current_user
from app.database import engine
from app.models import HostConfig
from app.services.agent_client import AgentClient
from app.services.traffic_service import build_traffic_report, sync_host_traffic

router = APIRouter(prefix="/api/hosts", tags=["traffic"], dependencies=[Depends(get_current_user)])


def _host(host_id: str) -> HostConfig:
    with Session(engine) as session:
        host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
    if host is None:
        raise HTTPException(status_code=404, detail="Host not found")
    return host


async def _current_traffic(host: HostConfig) -> dict | None:
    if not host.agent_url:
        return None
    client = AgentClient(host)
    try:
        return await client.get_traffic_current(activate=False)
    except Exception:
        return None
    finally:
        await client.close()


def _add_open_bucket(report: dict, current: dict | None) -> None:
    if not current or not current.get("currentBucketStart"):
        return
    try:
        bucket_start = datetime.fromisoformat(
            str(current["currentBucketStart"]).replace("Z", "+00:00")
        )
        range_start = datetime.fromisoformat(report["start"])
        range_end = datetime.fromisoformat(report["end"])
        if range_start <= bucket_start < range_end:
            open_rx = max(0, int(current.get("currentBucketRxBytes") or 0))
            open_tx = max(0, int(current.get("currentBucketTxBytes") or 0))
            report["rxBytes"] += open_rx
            report["txBytes"] += open_tx
            report["totalBytes"] += open_rx + open_tx
            report["openBucket"] = {
                "bucketStart": current["currentBucketStart"],
                "rxBytes": open_rx,
                "txBytes": open_tx,
            }
    except (KeyError, TypeError, ValueError):
        return


def _compact_range(report: dict) -> dict:
    return {
        "start": report["start"],
        "end": report["end"],
        "rxBytes": report["rxBytes"],
        "txBytes": report["txBytes"],
        "totalBytes": report["totalBytes"],
        "hasGap": report["hasGap"],
        "hasData": bool(report.get("buckets") or report.get("daily") or report.get("openBucket")),
    }


@router.post("/{host_id}/traffic/sync")
async def sync_traffic(host_id: str):
    _host(host_id)
    return await sync_host_traffic(host_id)


@router.get("/{host_id}/traffic/current")
async def current_traffic(host_id: str, activate: bool = Query(False)):
    host = _host(host_id)
    if not host.agent_url:
        raise HTTPException(status_code=409, detail="Host has no Agent URL")
    client = AgentClient(host)
    try:
        return await client.get_traffic_current(activate=activate)
    finally:
        await client.close()


@router.get("/{host_id}/traffic/summary")
async def traffic_summary(
    host_id: str,
    timezone_name: str = Query("Asia/Shanghai", alias="timezone"),
    sync: bool = Query(True),
):
    """Return compact today/month totals with a single Agent synchronization."""
    host = _host(host_id)
    sync_result = await sync_host_traffic(host_id) if sync else None
    try:
        today = build_traffic_report(host_id, range_name="today", tz_name=timezone_name)
        month = build_traffic_report(
            host_id,
            range_name="month",
            tz_name=timezone_name,
            billing_day=host.traffic_billing_day,
        )
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid traffic range")

    current = await _current_traffic(host)
    _add_open_bucket(today, current)
    _add_open_bucket(month, current)
    return {
        "hostId": host_id,
        "timezone": today["timezone"],
        "billingDay": host.traffic_billing_day,
        "today": _compact_range(today),
        "month": _compact_range(month),
        "sync": sync_result,
    }


@router.get("/{host_id}/traffic")
async def traffic_report(
    host_id: str,
    range: str = Query("today", pattern="^(today|month|custom)$"),
    timezone_name: str = Query("Asia/Shanghai", alias="timezone"),
    start: str | None = None,
    end: str | None = None,
    sync: bool = Query(True),
):
    host = _host(host_id)
    sync_result = await sync_host_traffic(host_id) if sync else None
    try:
        report = build_traffic_report(
            host_id,
            range_name=range,
            tz_name=timezone_name,
            start=start,
            end=end,
            billing_day=host.traffic_billing_day,
        )
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid traffic range")
    current = await _current_traffic(host)
    _add_open_bucket(report, current)
    report["current"] = current
    report["sync"] = sync_result
    return report
