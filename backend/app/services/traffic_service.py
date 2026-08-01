"""On-demand synchronization and aggregation of Agent traffic ledgers."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlmodel import Session, select

from app.database import engine
from app.models import HostConfig, HostTrafficBucket, HostTrafficCursor, HostTrafficDaily
from app.services.agent_client import AgentClient

_sync_locks: dict[str, asyncio.Lock] = {}


def _parse_timestamp(value: object) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _compact_old_buckets(session: Session) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    rows = session.exec(
        select(HostTrafficBucket).where(HostTrafficBucket.bucket_start < cutoff)
    ).all()
    grouped: dict[tuple[str, str], dict[str, int | bool]] = {}
    for row in rows:
        day = _utc_aware(row.bucket_start).date().isoformat()
        group = grouped.setdefault((row.host_id, day), {"rx": 0, "tx": 0, "gap": False, "count": 0})
        group["rx"] = int(group["rx"]) + row.rx_bytes
        group["tx"] = int(group["tx"]) + row.tx_bytes
        group["gap"] = bool(group["gap"] or row.has_gap)
        group["count"] = int(group["count"]) + 1
    for (host_id, day), values in grouped.items():
        daily = session.exec(
            select(HostTrafficDaily).where(
                HostTrafficDaily.host_id == host_id,
                HostTrafficDaily.day_utc == day,
            )
        ).first()
        if daily is None:
            daily = HostTrafficDaily(host_id=host_id, day_utc=day)
        daily.rx_bytes += int(values["rx"])
        daily.tx_bytes += int(values["tx"])
        daily.has_gap = bool(daily.has_gap or values["gap"])
        daily.bucket_count += int(values["count"])
        session.add(daily)
    for row in rows:
        session.delete(row)


async def sync_host_traffic(host_id: str) -> dict:
    lock = _sync_locks.setdefault(host_id, asyncio.Lock())
    async with lock:
        with Session(engine) as session:
            host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
            cursor_row = session.get(HostTrafficCursor, host_id)
            cursor = cursor_row.cursor if cursor_row else 0
            known_ledger = cursor_row.ledger_id if cursor_row else None
        if host is None or not host.agent_url:
            return {"supported": False, "synced": 0, "error": "host or agent unavailable"}

        client = AgentClient(host)
        synced = 0
        try:
            for _ in range(20):
                payload = await client.get_traffic_history(cursor=cursor, limit=1000)
                ledger_id = str(payload.get("ledgerId") or "legacy")
                if known_ledger and ledger_id != known_ledger:
                    cursor = 0
                    known_ledger = ledger_id
                    continue
                known_ledger = ledger_id
                rows = payload.get("buckets") or []
                retention_gap = bool(payload.get("retentionGap"))
                with Session(engine) as session:
                    cursor_row = session.get(HostTrafficCursor, host_id) or HostTrafficCursor(host_id=host_id)
                    if cursor_row.ledger_id and cursor_row.ledger_id != ledger_id:
                        cursor_row.cursor = 0
                    for item in rows:
                        agent_bucket_id = int(item["id"])
                        existing = session.exec(
                            select(HostTrafficBucket).where(
                                HostTrafficBucket.host_id == host_id,
                                HostTrafficBucket.ledger_id == ledger_id,
                                HostTrafficBucket.agent_bucket_id == agent_bucket_id,
                            )
                        ).first()
                        if existing is not None:
                            continue
                        session.add(
                            HostTrafficBucket(
                                host_id=host_id,
                                ledger_id=ledger_id,
                                agent_bucket_id=agent_bucket_id,
                                bucket_start=_parse_timestamp(item.get("bucketStart")),
                                bucket_seconds=int(item.get("bucketSeconds") or 300),
                                counter_epoch=str(item.get("networkCounterEpoch") or "unknown"),
                                rx_bytes=max(0, int(item.get("rxBytes") or 0)),
                                tx_bytes=max(0, int(item.get("txBytes") or 0)),
                                has_gap=bool(item.get("hasGap") or (retention_gap and item is rows[0])),
                                counter_reset=bool(item.get("counterReset")),
                                interfaces_json=json.dumps(item.get("networkInterfaces") or []),
                            )
                        )
                        synced += 1
                    cursor = int(payload.get("nextCursor") or cursor)
                    cursor_row.cursor = cursor
                    cursor_row.ledger_id = ledger_id
                    cursor_row.last_sync_at = datetime.now(timezone.utc)
                    cursor_row.last_error = None
                    session.add(cursor_row)
                    _compact_old_buckets(session)
                    session.commit()
                if not payload.get("hasMore"):
                    break
            return {"supported": True, "synced": synced, "cursor": cursor, "ledgerId": known_ledger}
        except httpx.HTTPStatusError as exc:
            error = "unsupported" if exc.response.status_code == 404 else f"agent http {exc.response.status_code}"
        except Exception as exc:
            error = type(exc).__name__
        finally:
            await client.close()
        with Session(engine) as session:
            cursor_row = session.get(HostTrafficCursor, host_id) or HostTrafficCursor(host_id=host_id)
            cursor_row.last_sync_at = datetime.now(timezone.utc)
            cursor_row.last_error = error
            session.add(cursor_row)
            session.commit()
        return {"supported": error != "unsupported", "synced": synced, "error": error}


def _range_bounds(range_name: str, tz_name: str, start: str | None, end: str | None) -> tuple[datetime, datetime, str]:
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc
        tz_name = "UTC"
    now = datetime.now(tz)
    if range_name == "month":
        local_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        local_end = now
    elif range_name == "custom" and start and end:
        local_start = _parse_timestamp(start).astimezone(tz)
        local_end = _parse_timestamp(end).astimezone(tz)
    else:
        local_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = now
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc), tz_name


def build_traffic_report(
    host_id: str,
    *,
    range_name: str = "today",
    tz_name: str = "Asia/Shanghai",
    start: str | None = None,
    end: str | None = None,
) -> dict:
    range_start, range_end, resolved_tz = _range_bounds(range_name, tz_name, start, end)
    with Session(engine) as session:
        buckets = session.exec(
            select(HostTrafficBucket).where(
                HostTrafficBucket.host_id == host_id,
                HostTrafficBucket.bucket_start >= range_start,
                HostTrafficBucket.bucket_start < range_end,
            ).order_by(HostTrafficBucket.bucket_start)
        ).all()
        daily = session.exec(select(HostTrafficDaily).where(HostTrafficDaily.host_id == host_id)).all()

    daily_rows = []
    for row in daily:
        day_start = datetime.fromisoformat(row.day_utc).replace(tzinfo=timezone.utc)
        if range_start <= day_start < range_end:
            daily_rows.append(row)
    rx_total = sum(row.rx_bytes for row in buckets) + sum(row.rx_bytes for row in daily_rows)
    tx_total = sum(row.tx_bytes for row in buckets) + sum(row.tx_bytes for row in daily_rows)
    has_gap = any(row.has_gap for row in buckets) or any(row.has_gap for row in daily_rows)
    return {
        "hostId": host_id,
        "range": range_name,
        "timezone": resolved_tz,
        "start": range_start.isoformat(),
        "end": range_end.isoformat(),
        "rxBytes": rx_total,
        "txBytes": tx_total,
        "totalBytes": rx_total + tx_total,
        "hasGap": has_gap,
        "buckets": [
            {
                "bucketStart": _utc_aware(row.bucket_start).isoformat(),
                "bucketSeconds": row.bucket_seconds,
                "rxBytes": row.rx_bytes,
                "txBytes": row.tx_bytes,
                "hasGap": row.has_gap,
                "counterReset": row.counter_reset,
                "networkInterfaces": json.loads(row.interfaces_json or "[]"),
            }
            for row in buckets
        ],
        "daily": [
            {
                "dayUtc": row.day_utc,
                "rxBytes": row.rx_bytes,
                "txBytes": row.tx_bytes,
                "hasGap": row.has_gap,
                "bucketCount": row.bucket_count,
            }
            for row in daily_rows
        ],
    }
