"""Subscription billing calculations and durable Notify Hub alerts."""

import asyncio
import calendar
import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from sqlmodel import Session, select

from app.database import engine
from app.models import (
    HostBillingAlertState,
    HostConfig,
    HostSubscription,
    HostTrafficCursor,
    Setting,
)
from app.services.agent_client import AgentClient
from app.services.auto_update import NOTIFY_KEYS, notify_settings
from app.services.notification_cover import prepare_notification
from app.services.crypto import decrypt_string
from app.services.traffic_service import (
    _billing_cycle_start,
    _parse_timestamp,
    add_open_traffic_bucket,
    build_traffic_report,
    sync_host_traffic,
)

logger = logging.getLogger(__name__)

UNIT_BYTES = {
    "GB": 1_000_000_000,
    "TB": 1_000_000_000_000,
    "GiB": 1_073_741_824,
    "TiB": 1_099_511_627_776,
}
PAYMENT_CYCLE_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "semiannual": 6,
    "annual": 12,
}
QUOTA_ALERT_THRESHOLDS = (80, 90, 95, 100)
MAX_NOTIFY_ATTEMPTS = 5


def get_engine():
    import app.services.billing_service as this_module
    return getattr(this_module, "engine", engine)


def subscription_is_configured(subscription: HostSubscription | None) -> bool:
    if subscription is None:
        return False
    return any((
        subscription.provider,
        subscription.plan_name,
        subscription.payment_amount is not None,
        subscription.payment_cycle,
        subscription.next_payment_date,
        subscription.service_expiry_date,
        subscription.auto_renew,
        subscription.management_url,
        subscription.notes,
        subscription.quota_enabled,
    ))


def subscription_payload(host_id: str, subscription: HostSubscription | None) -> dict:
    subscription = subscription or HostSubscription(host_id=host_id)
    return {
        "host_id": host_id,
        "configured": subscription_is_configured(subscription),
        "provider": subscription.provider,
        "plan_name": subscription.plan_name,
        "payment_amount": float(subscription.payment_amount) if subscription.payment_amount is not None else None,
        "currency": subscription.currency,
        "payment_cycle": subscription.payment_cycle,
        "next_payment_date": subscription.next_payment_date,
        "service_expiry_date": subscription.service_expiry_date,
        "auto_renew": subscription.auto_renew,
        "management_url": subscription.management_url,
        "notes": subscription.notes,
        "quota_enabled": subscription.quota_enabled,
        "traffic_quota_value": float(subscription.traffic_quota_value) if subscription.traffic_quota_value is not None else None,
        "traffic_quota_unit": subscription.traffic_quota_unit,
        "traffic_direction": subscription.traffic_direction,
        "billing_timezone": subscription.billing_timezone,
        "alerts_enabled": subscription.alerts_enabled,
    }


def add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def suggested_next_payment_date(
    subscription: HostSubscription,
    *,
    paid_on: date,
) -> date | None:
    if subscription.payment_cycle == "once":
        return None
    months = PAYMENT_CYCLE_MONTHS.get(subscription.payment_cycle or "")
    if months is None:
        return None
    base = max(paid_on, subscription.next_payment_date or paid_on)
    return add_months(base, months)


def _date_status(value: date | None, today: date) -> tuple[str, int | None]:
    if value is None:
        return "not_scheduled", None
    days = (value - today).days
    if days < 0:
        return "overdue", days
    if days == 0:
        return "due_today", days
    if days <= 30:
        return "due_soon", days
    return "scheduled", days


def billing_summary(
    host_id: str,
    subscription: HostSubscription | None,
    *,
    today: date | None = None,
) -> dict:
    subscription = subscription or HostSubscription(host_id=host_id)
    tz = ZoneInfo(subscription.billing_timezone)
    today = today or datetime.now(tz).date()
    payment_status, payment_days = _date_status(subscription.next_payment_date, today)
    expiry_status, expiry_days = _date_status(subscription.service_expiry_date, today)

    if not subscription_is_configured(subscription):
        status = "unconfigured"
    elif expiry_status == "overdue":
        status = "expired"
    elif payment_status == "overdue":
        status = "overdue"
    elif expiry_status in {"due_today", "due_soon"} or payment_status in {"due_today", "due_soon"}:
        status = "expiring_soon"
    else:
        status = "normal"

    recommended = suggested_next_payment_date(subscription, paid_on=today)
    return {
        "hostId": host_id,
        "configured": subscription_is_configured(subscription),
        "status": status,
        "paymentDate": subscription.next_payment_date,
        "paymentDaysRemaining": payment_days,
        "paymentStatus": payment_status,
        "serviceExpiryDate": subscription.service_expiry_date,
        "serviceDaysRemaining": expiry_days,
        "serviceStatus": expiry_status,
        "autoRenew": subscription.auto_renew,
        "paymentCycle": subscription.payment_cycle,
        "recommendedNextPaymentDate": recommended,
    }


def _next_reset_at(now: datetime, billing_day: int) -> datetime:
    cycle_start = _billing_cycle_start(now, billing_day)
    next_month_index = cycle_start.year * 12 + cycle_start.month
    year, zero_based_month = divmod(next_month_index, 12)
    month = zero_based_month + 1
    day = min(billing_day, calendar.monthrange(year, month)[1])
    return cycle_start.replace(year=year, month=month, day=day)


def _traffic_coverage_complete(report: dict) -> bool:
    """Require continuous coverage of this range, including its open bucket.

    Daily aggregates cannot precisely cover a partial UTC day. Such boundary
    rows remain estimates rather than being presented as exact billing data.
    """
    try:
        start = _parse_timestamp(report["start"])
        end = _parse_timestamp(report["end"])
        intervals: list[tuple[datetime, datetime]] = []
        for bucket in report.get("buckets", []):
            left = _parse_timestamp(bucket["bucketStart"])
            right = left + timedelta(seconds=int(bucket["bucketSeconds"]))
            intervals.append((left, right))
        for daily in report.get("daily", []):
            left = _parse_timestamp(daily["dayUtc"])
            right = left + timedelta(days=1)
            if left < start or right > end:
                return False
            intervals.append((left, right))
        if report.get("openBucket"):
            intervals.append((_parse_timestamp(report["openBucket"]["bucketStart"]), end))
        covered_until = start
        for left, right in sorted(intervals):
            if left > covered_until:
                return False
            covered_until = max(covered_until, right)
            if covered_until >= end:
                return True
        return covered_until >= end
    except (KeyError, TypeError, ValueError):
        return False


def quota_summary(
    host: HostConfig,
    subscription: HostSubscription,
    report: dict,
    *,
    sync_error: str | None = None,
    current_error: str | None = None,
    cursor_error: str | None = None,
    now: datetime | None = None,
) -> dict:
    tz = ZoneInfo(subscription.billing_timezone)
    local_now = (now or datetime.now(timezone.utc)).astimezone(tz)
    rx_bytes = max(0, int(report.get("rxBytes") or 0))
    tx_bytes = max(0, int(report.get("txBytes") or 0))
    direction = subscription.traffic_direction
    if direction == "upload":
        used_bytes = tx_bytes
    elif direction == "download":
        used_bytes = rx_bytes
    elif direction == "max":
        used_bytes = max(rx_bytes, tx_bytes)
    else:
        used_bytes = rx_bytes + tx_bytes

    has_data = bool(report.get("buckets") or report.get("daily") or report.get("openBucket"))
    coverage_complete = _traffic_coverage_complete(report)
    has_gap = bool(report.get("hasGap") or not coverage_complete)
    estimated = bool(
        has_gap
        or not has_data
        or sync_error
        or current_error
        or cursor_error
    )
    configured = bool(
        subscription.quota_enabled
        and subscription.traffic_quota_value is not None
        and subscription.traffic_quota_unit in UNIT_BYTES
    )
    quota_bytes = None
    remaining_bytes = None
    overage_bytes = None
    usage_percent = None
    if configured:
        quota_bytes = int(Decimal(str(subscription.traffic_quota_value)) * UNIT_BYTES[subscription.traffic_quota_unit])
        remaining_bytes = max(0, quota_bytes - used_bytes)
        overage_bytes = max(0, used_bytes - quota_bytes)
        usage_percent = round(used_bytes * 100 / quota_bytes, 2) if quota_bytes else None

    over_quota = bool(configured and used_bytes >= quota_bytes)
    if not configured:
        status = "unconfigured"
    elif estimated:
        status = "incomplete"
    elif over_quota:
        status = "over_quota"
    else:
        status = "normal"

    return {
        "hostId": host.host_id,
        "enabled": subscription.quota_enabled,
        "configured": configured,
        "status": status,
        "billingTimezone": subscription.billing_timezone,
        "billingDay": host.traffic_billing_day,
        "periodStart": report.get("start"),
        "periodEnd": report.get("end"),
        "nextResetAt": _next_reset_at(local_now, host.traffic_billing_day),
        "quotaValue": float(subscription.traffic_quota_value) if configured else None,
        "quotaUnit": subscription.traffic_quota_unit,
        "quotaBytes": quota_bytes,
        "direction": direction,
        "usedBytes": used_bytes if configured else None,
        "remainingBytes": remaining_bytes,
        "overageBytes": overage_bytes,
        "usagePercent": usage_percent,
        "overQuota": over_quota,
        "rxBytes": rx_bytes,
        "txBytes": tx_bytes,
        "hasData": has_data,
        "hasGap": has_gap,
        "coverageComplete": coverage_complete,
        "estimated": estimated,
        "collectionWarnings": report.get("collectionWarnings", []),
        "syncError": sync_error,
        "currentError": current_error,
        "cursorError": cursor_error,
    }


async def calculate_quota(
    host: HostConfig,
    subscription: HostSubscription,
    *,
    sync: bool,
    sync_result: dict | None = None,
) -> dict:
    if sync and sync_result is None:
        sync_result = await sync_host_traffic(host.host_id)
    report = build_traffic_report(
        host.host_id,
        range_name="month",
        tz_name=subscription.billing_timezone,
        billing_day=host.traffic_billing_day,
    )
    current_error = None if host.agent_url else "agent_unavailable"
    current = None
    if host.agent_url:
        client = AgentClient(host)
        try:
            current = await client.get_traffic_current(activate=False)
        except Exception as exc:
            current_error = type(exc).__name__
        finally:
            await client.close()
    add_open_traffic_bucket(report, current)
    warnings = []
    if current:
        if current.get("hasGap") or current.get("counterReset"):
            report["hasGap"] = True
            warnings.append("agent_collection_gap")
        if current.get("persistenceAvailable") is False:
            warnings.append("persistence_unavailable")
        if current.get("networkScope") == "unknown":
            warnings.append("network_scope_unknown")
        sample_age = current.get("sampleAgeSeconds")
        if isinstance(sample_age, (int, float)) and sample_age > 300:
            warnings.append("stale_agent_sample")
        if warnings and current_error is None:
            current_error = ",".join(warnings)
    report["collectionWarnings"] = warnings

    with Session(get_engine()) as session:
        cursor = session.get(HostTrafficCursor, host.host_id)
        cursor_error = cursor.last_error if cursor else None

    sync_error = None
    if sync_result:
        sync_error = sync_result.get("error")
        if sync_result.get("supported") is False and not sync_error:
            sync_error = "unsupported"
    quota = quota_summary(
        host,
        subscription,
        report,
        sync_error=sync_error,
        current_error=current_error,
        cursor_error=cursor_error,
        now=_parse_timestamp(report["end"]),
    )
    quota["sync"] = sync_result
    return quota


def billing_alerts_enabled() -> bool:
    with Session(get_engine()) as session:
        row = session.get(Setting, "BILLING_ALERTS_ENABLED")
    if row is None:
        return True
    return row.setting_value.strip().lower() not in {"0", "false", "off", "no"}


def set_billing_alerts_enabled(enabled: bool) -> None:
    with Session(get_engine()) as session:
        row = session.get(Setting, "BILLING_ALERTS_ENABLED") or Setting(setting_key="BILLING_ALERTS_ENABLED")
        row.setting_value = "true" if enabled else "false"
        session.add(row)
        session.commit()


class BillingAlertManager:
    """Schedules Agent ledger syncs and dispatches persisted, de-duplicated alerts."""

    def __init__(self):
        self.started = False
        self.tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        if self.started:
            return
        self.started = True
        self.tasks = [
            asyncio.create_task(self._periodic(self.check_expiry_alerts, 24 * 60 * 60), name="billing-expiry-alerts"),
            asyncio.create_task(self._periodic(self.check_traffic_alerts, 45 * 60), name="billing-traffic-alerts"),
            asyncio.create_task(self._periodic(self.dispatch_pending, 60), name="billing-notification-delivery"),
        ]

    async def stop(self) -> None:
        self.started = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

    async def _periodic(self, action, interval: int) -> None:
        while self.started:
            try:
                await action()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Billing background task failed: %s", action.__name__)
            await asyncio.sleep(interval)

    def _enqueue(
        self,
        *,
        host_id: str,
        alert_type: str,
        alert_key: str,
        title: str,
        content: str,
        level: str = "warning",
        context: dict | None = None,
    ) -> None:
        with Session(get_engine()) as session:
            existing = session.exec(select(HostBillingAlertState).where(
                HostBillingAlertState.alert_key == alert_key,
            )).first()
            if existing and existing.status != "cancelled":
                return
        config = notify_settings()
        if not all(config.get(key) for key in NOTIFY_KEYS):
            return
        payload = {
            "event_type": f"fleetge.host.{alert_type}",
            "event_key": alert_key,
            "title": title[:200],
            "content": content,
            "level": level,
            "recipients": [config["NOTIFYHUB_RECIPIENT"]],
            "message_type": "text",
            "_host_icon": None,
        }
        if context is not None:
            payload["_billing_context"] = context
        now = datetime.now(timezone.utc)
        with Session(get_engine()) as session:
            row = session.get(HostBillingAlertState, existing.id) if existing else None
            row = row or HostBillingAlertState(
                alert_key=alert_key, host_id=host_id, alert_type=alert_type,
                expires_at=now + timedelta(hours=24),
            )
            row.status = "pending"
            row.notify_url = config["NOTIFYHUB_URL"]
            row.notify_recipient = config["NOTIFYHUB_RECIPIENT"]
            row.payload = json.dumps(payload, ensure_ascii=False)
            row.attempts = 0
            row.next_attempt_at = now
            row.expires_at = now + timedelta(hours=24)
            row.last_error = ""
            session.add(row)
            session.commit()

    async def check_expiry_alerts(self) -> None:
        if not billing_alerts_enabled():
            return
        with Session(get_engine()) as session:
            subscriptions = session.exec(select(HostSubscription).where(
                HostSubscription.alerts_enabled == True,  # noqa: E712
            )).all()
            host_names = {
                host.host_id: host.display_name or host.host_id
                for host in session.exec(select(HostConfig)).all()
            }
        for subscription in subscriptions:
            if subscription.host_id not in host_names:
                continue
            today = datetime.now(ZoneInfo(subscription.billing_timezone)).date()
            targets: dict[date, tuple[list[str], int]] = {}
            for label, due_date in (
                ("付款", subscription.next_payment_date),
                ("服务到期", subscription.service_expiry_date),
            ):
                if due_date is None:
                    continue
                days = (due_date - today).days
                if days < 0 or days > 30:
                    continue
                advance_days = next((threshold for threshold in (1, 3, 7, 30) if days <= threshold), None)
                if advance_days is None:
                    continue
                if due_date not in targets:
                    targets[due_date] = ([], advance_days)
                targets[due_date][0].append(label)
            for due_date, (labels, advance_days) in targets.items():
                days = (due_date - today).days
                alert_key = f"fleetge:billing:{subscription.host_id}:{due_date.isoformat()}:{advance_days}"
                when = "今日" if days == 0 else f"{days} 天后"
                title = f"【Fleetge】{host_names[subscription.host_id]} {when}{' / '.join(labels)}"[:40]
                content = (
                    f"{'、'.join(labels)}日期：{due_date.isoformat()}。"
                    + ("已开启自动续费，请确认扣款结果。" if subscription.auto_renew else "未开启自动续费，请及时续费并更新记录。")
                )
                self._enqueue(
                    host_id=subscription.host_id,
                    alert_type="billing_due",
                    alert_key=alert_key,
                    title=title,
                    content=content,
                )

    async def check_traffic_alerts(self) -> None:
        if not billing_alerts_enabled():
            return
        with Session(get_engine()) as session:
            subscriptions = session.exec(select(HostSubscription).where(
                HostSubscription.quota_enabled == True,  # noqa: E712
                HostSubscription.alerts_enabled == True,  # noqa: E712
            )).all()
            hosts = {
                host.host_id: host
                for host in session.exec(select(HostConfig)).all()
            }
        for subscription in subscriptions:
            host = hosts.get(subscription.host_id)
            if host is None:
                continue
            sync_result = await sync_host_traffic(host.host_id)
            quota = await calculate_quota(host, subscription, sync=False, sync_result=sync_result)
            if not quota["configured"] or quota["usagePercent"] is None:
                continue
            period_key = quota["periodStart"]
            for threshold in QUOTA_ALERT_THRESHOLDS:
                if quota["usedBytes"] * 100 < quota["quotaBytes"] * threshold:
                    continue
                alert_key = f"fleetge:traffic:{host.host_id}:{period_key}:{threshold}"
                estimated = "（估算值）" if quota["estimated"] else ""
                title = f"【Fleetge】流量达到 {threshold}%｜{host.display_name or host.host_id}"[:40]
                content = (
                    f"本周期已用 {quota['usedBytes'] / 1_000_000_000:.1f} / "
                    f"{quota['quotaBytes'] / 1_000_000_000:.1f} GB{estimated}。请关注用量，避免超额。"
                )
                self._enqueue(
                    host_id=host.host_id,
                    alert_type="traffic_quota",
                    alert_key=alert_key,
                    title=title,
                    content=content,
                    context={
                        "quotaBytes": quota["quotaBytes"],
                        "direction": subscription.traffic_direction,
                        "usedBytes": quota["usedBytes"],
                    },
                )

    def _alert_is_current(self, alert: HostBillingAlertState, subscription: HostSubscription, host: HostConfig, now: datetime) -> bool:
        """Recheck the event's date/cycle and threshold immediately before delivery."""
        local_now = now.astimezone(ZoneInfo(subscription.billing_timezone))
        try:
            if alert.alert_type == "billing_due":
                prefix = f"fleetge:billing:{host.host_id}:"
                if not alert.alert_key.startswith(prefix):
                    return False
                date_text, advance_days = alert.alert_key[len(prefix):].rsplit(":", 1)
                target_date = date.fromisoformat(date_text)
                return (
                    target_date in {subscription.next_payment_date, subscription.service_expiry_date}
                    and 0 <= (target_date - local_now.date()).days <= int(advance_days)
                )
            if alert.alert_type == "traffic_quota":
                prefix = f"fleetge:traffic:{host.host_id}:"
                if not alert.alert_key.startswith(prefix) or not subscription.quota_enabled:
                    return False
                period_text, threshold_text = alert.alert_key[len(prefix):].rsplit(":", 1)
                if _parse_timestamp(period_text) != _billing_cycle_start(local_now, host.traffic_billing_day).astimezone(timezone.utc):
                    return False
                threshold = int(threshold_text)
                if threshold not in QUOTA_ALERT_THRESHOLDS or subscription.traffic_quota_value is None:
                    return False
                quota_bytes = int(Decimal(str(subscription.traffic_quota_value)) * UNIT_BYTES[subscription.traffic_quota_unit])
                context = json.loads(alert.payload).get("_billing_context", {})
                if context:
                    return bool(
                        context.get("quotaBytes") == quota_bytes
                        and context.get("direction") == subscription.traffic_direction
                        and context.get("usedBytes", 0) * 100 >= quota_bytes * threshold
                    )
                # Older persisted events have no context; validate from the local ledger.
                report = build_traffic_report(
                    host.host_id, range_name="month", tz_name=subscription.billing_timezone,
                    billing_day=host.traffic_billing_day,
                )
                quota = quota_summary(host, subscription, report, now=now)
                return bool(
                    quota["configured"]
                    and threshold in QUOTA_ALERT_THRESHOLDS
                    and quota["usedBytes"] * 100 >= quota["quotaBytes"] * threshold
                )
        except (KeyError, TypeError, ValueError):
            return False
        return False

    async def dispatch_pending(self) -> None:
        if not billing_alerts_enabled():
            return
        config = notify_settings()
        now = datetime.now(timezone.utc)
        with Session(get_engine()) as session:
            alerts = session.exec(select(HostBillingAlertState).where(
                HostBillingAlertState.status == "pending",
                HostBillingAlertState.next_attempt_at <= now,
            ).order_by(HostBillingAlertState.id)).all()
        if not alerts:
            return

        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), follow_redirects=False) as client:
            for alert in alerts:
                expires_at = alert.expires_at
                expires_at = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at.astimezone(timezone.utc)
                if expires_at <= now:
                    self._finish_delivery(alert.id, "expired", "Notification expired before acceptance.")
                    continue
                with Session(get_engine()) as session:
                    subscription = session.exec(select(HostSubscription).where(
                        HostSubscription.host_id == alert.host_id,
                    )).first()
                    host = session.exec(select(HostConfig).where(HostConfig.host_id == alert.host_id)).first()
                if subscription is None or host is None or not self._alert_is_current(alert, subscription, host, now):
                    self._finish_delivery(alert.id, "cancelled", "The billing date, traffic cycle, or quota is no longer applicable.")
                    continue
                if not subscription.alerts_enabled:
                    continue
                if (
                    config.get("NOTIFYHUB_URL") != alert.notify_url
                    or config.get("NOTIFYHUB_RECIPIENT") != alert.notify_recipient
                    or not config.get("NOTIFYHUB_KEY")
                ):
                    self._finish_delivery(alert.id, "blocked", "Notify Hub configuration changed before delivery.")
                    continue
                try:
                    payload = json.loads(alert.payload)
                    context = payload.pop("_billing_context", None)
                    if "_host_icon" in payload:
                        payload["_host_icon"] = host.logo
                    api_key = decrypt_string(config["NOTIFYHUB_KEY"])
                    payload = await prepare_notification(client, alert.notify_url, api_key, payload)
                    with Session(get_engine()) as session:
                        row = session.get(HostBillingAlertState, alert.id)
                        stored = {**payload, "_billing_context": context} if context is not None else payload
                        row.payload = json.dumps(stored, ensure_ascii=False)
                        session.add(row)
                        session.commit()
                    response = await client.post(
                        alert.notify_url + "/api/v1/events",
                        json=payload,
                        headers={"X-API-Key": api_key},
                    )
                    if response.status_code == 202:
                        body = response.json()
                        data = body.get("data", {}) if isinstance(body, dict) else {}
                        if isinstance(data, dict) and data.get("status") in {"accepted", "duplicate"} and data.get("event_id"):
                            self._finish_delivery(alert.id, "sent", "", sent=True)
                            continue
                        self._retry_delivery(alert.id, "Notify Hub accepted no event id.")
                    elif response.status_code == 429 or response.status_code >= 500:
                        self._retry_delivery(alert.id, f"Notify Hub HTTP {response.status_code}.")
                    else:
                        self._finish_delivery(alert.id, "blocked", f"Notify Hub HTTP {response.status_code}.")
                except (httpx.HTTPError, ValueError) as exc:
                    self._retry_delivery(alert.id, f"Notify Hub request was not confirmed ({type(exc).__name__}).")
                except Exception as exc:
                    self._finish_delivery(alert.id, "blocked", f"Notify Hub configuration error ({type(exc).__name__}).")

    def _retry_delivery(self, alert_id: int, error: str) -> None:
        now = datetime.now(timezone.utc)
        with Session(get_engine()) as session:
            alert = session.get(HostBillingAlertState, alert_id)
            if alert is None or alert.status != "pending":
                return
            alert.attempts += 1
            alert.last_error = error
            if alert.attempts >= MAX_NOTIFY_ATTEMPTS:
                alert.status = "failed"
            else:
                delay = min(15 * 60, 60 * (2 ** (alert.attempts - 1)))
                alert.next_attempt_at = now + timedelta(seconds=delay)
            session.add(alert)
            session.commit()

    def _finish_delivery(self, alert_id: int, status: str, error: str, *, sent: bool = False) -> None:
        with Session(get_engine()) as session:
            alert = session.get(HostBillingAlertState, alert_id)
            if alert is None or alert.status != "pending":
                return
            alert.status = status
            alert.last_error = error
            if status not in {"cancelled", "expired"}:
                alert.attempts += 1
            if sent:
                alert.sent_at = datetime.now(timezone.utc)
            session.add(alert)
            session.commit()


billing_alert_manager = BillingAlertManager()
