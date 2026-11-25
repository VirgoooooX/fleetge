"""Build the API host summary from the current in-memory snapshot."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.schemas import HostSubscriptionSummary, HostSummary
from app.services.billing_service import _date_status, subscription_is_configured, traffic_quota_bytes
from app.services.host_monitor import host_monitor_manager

if TYPE_CHECKING:
    from app.services.snapshot import HostSnapshot


def build_host_summary(snap: "HostSnapshot") -> HostSummary:
    """Build a HostSummary from a snapshot, for the /api/hosts response."""
    cfg = snap.host_config
    info = snap.docker_info
    disk = snap.docker_disk
    containers = snap.containers

    if info is None and snap.status == "degraded":
        effective_status = "degraded"
    elif snap.metrics is None and snap.status == "online":
        effective_status = "degraded"
    else:
        effective_status = snap.status

    sub_summary = None
    sub = snap.subscription
    if sub and subscription_is_configured(sub):
        try:
            tz = ZoneInfo(sub.billing_timezone)
        except (ValueError, ZoneInfoNotFoundError):
            tz = timezone.utc
        local_today = datetime.now(tz).date()
        _, expiry_days = _date_status(sub.service_expiry_date, local_today)
        _, payment_days = _date_status(sub.next_payment_date, local_today)
        quota_bytes = traffic_quota_bytes(sub)

        sub_summary = HostSubscriptionSummary(
            configured=True,
            provider=sub.provider,
            plan_name=sub.plan_name,
            payment_amount=float(sub.payment_amount) if sub.payment_amount is not None else None,
            currency=sub.currency or "CNY",
            payment_cycle=sub.payment_cycle,
            next_payment_date=sub.next_payment_date.isoformat() if sub.next_payment_date else None,
            payment_days_remaining=payment_days,
            service_expiry_date=sub.service_expiry_date.isoformat() if sub.service_expiry_date else None,
            service_days_remaining=expiry_days,
            auto_renew=sub.auto_renew,
            alerts_enabled=sub.alerts_enabled,
            quota_enabled=sub.quota_enabled,
            traffic_direction=sub.traffic_direction or "both",
            traffic_quota_value=float(sub.traffic_quota_value) if sub.traffic_quota_value is not None else None,
            traffic_quota_unit=sub.traffic_quota_unit,
            traffic_quota_bytes=quota_bytes,
            management_url=sub.management_url,
        )

    return HostSummary(
        host_id=cfg.host_id,
        display_name=cfg.display_name or cfg.host_id,
        status=effective_status,
        traffic_billing_day=cfg.traffic_billing_day,
        logo=cfg.logo,
        metrics=snap.metrics,
        docker_version=info.version if info else None,
        api_version=info.api_version if info else None,
        os_info=info.operating_system if info else None,
        architecture=info.architecture if info else None,
        docker_root_dir=info.docker_root_dir if info else None,
        container_running=sum(1 for c in containers if c.state == "running"),
        container_stopped=sum(1 for c in containers if c.state != "running"),
        container_total=len(containers),
        image_count=snap.image_count,
        docker_disk_images=disk.images_size if disk else None,
        docker_disk_containers=disk.containers_size if disk else None,
        docker_disk_volumes=disk.volumes_size if disk else None,
        docker_disk_build_cache=disk.build_cache_size if disk else None,
        update_count=snap.update_count,  # From update_check background task
        error_message=snap.error_message,  # From snapshot error state
        subscription=sub_summary,
        monitor=host_monitor_manager.get_summary(cfg.host_id),
    )
