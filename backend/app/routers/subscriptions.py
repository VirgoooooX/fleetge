"""Host subscription, billing, traffic-quota, and alert settings APIs."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from app.auth.handler import get_current_user
from app.database import engine
from app.models import AuditLog, HostConfig, HostSubscription
from app.schemas import (
    BillingAlertsUpdateRequest,
    HostSubscriptionResponse,
    HostSubscriptionUpdate,
    RenewalRequest,
)
from app.services.billing_service import (
    billing_alerts_enabled,
    billing_summary,
    calculate_quota,
    set_billing_alerts_enabled,
    subscription_payload,
)
from app.services.snapshot import snapshot_manager

router = APIRouter(prefix="/api", tags=["subscriptions"], dependencies=[Depends(get_current_user)])


def _host_and_subscription(host_id: str) -> tuple[HostConfig, HostSubscription | None]:
    with Session(engine) as session:
        host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
        if host is None:
            raise HTTPException(status_code=404, detail="Host not found")
        subscription = session.exec(select(HostSubscription).where(
            HostSubscription.host_id == host_id,
        )).first()
        return host, subscription


@router.get("/hosts/{host_id}/subscription", response_model=HostSubscriptionResponse)
async def get_subscription(host_id: str):
    _, subscription = _host_and_subscription(host_id)
    return subscription_payload(host_id, subscription)


@router.put("/hosts/{host_id}/subscription", response_model=HostSubscriptionResponse)
async def update_subscription(
    host_id: str,
    payload: HostSubscriptionUpdate,
    request: Request,
    username: str = Depends(get_current_user),
):
    with Session(engine) as session:
        host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
        if host is None:
            raise HTTPException(status_code=404, detail="Host not found")
        subscription = session.exec(select(HostSubscription).where(
            HostSubscription.host_id == host_id,
        )).first()
        if subscription is None:
            subscription = HostSubscription(host_id=host_id)
        values = payload.model_dump()
        for field, value in values.items():
            setattr(subscription, field, value)
        session.add(subscription)
        session.add(AuditLog(
            user=username,
            action="host.subscription.configure",
            host_id=host_id,
            result="success",
            detail="Subscription and traffic quota settings updated.",
            ip_address=request.client.host if request.client else None,
        ))
        session.commit()
        session.refresh(subscription)
        await snapshot_manager.refresh_hosts()
        return subscription_payload(host_id, subscription)


@router.get("/hosts/{host_id}/billing")
async def get_billing(host_id: str):
    _, subscription = _host_and_subscription(host_id)
    return billing_summary(host_id, subscription)


@router.get("/hosts/{host_id}/traffic/quota")
async def get_traffic_quota(host_id: str, sync: bool = Query(True)):
    host, subscription = _host_and_subscription(host_id)
    subscription = subscription or HostSubscription(host_id=host_id)
    return await calculate_quota(host, subscription, sync=sync)


@router.post("/hosts/{host_id}/renewal")
async def confirm_renewal(
    host_id: str,
    payload: RenewalRequest,
    request: Request,
    username: str = Depends(get_current_user),
):
    with Session(engine) as session:
        host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
        if host is None:
            raise HTTPException(status_code=404, detail="Host not found")
        subscription = session.exec(select(HostSubscription).where(
            HostSubscription.host_id == host_id,
        )).first()
        if subscription is None:
            subscription = HostSubscription(host_id=host_id)

        paid_on = payload.paid_on or datetime.now(ZoneInfo(subscription.billing_timezone)).date()
        if payload.service_expiry_date < paid_on:
            raise HTTPException(status_code=422, detail="service_expiry_date must be on or after paid_on")
        next_payment_date = payload.next_payment_date
        if subscription.payment_cycle == "once":
            next_payment_date = None
        if next_payment_date is not None and next_payment_date < paid_on:
            raise HTTPException(status_code=422, detail="next_payment_date must be on or after paid_on")

        subscription.next_payment_date = next_payment_date
        subscription.service_expiry_date = payload.service_expiry_date
        session.add(subscription)
        session.add(AuditLog(
            user=username,
            action="host.subscription.renewal",
            host_id=host_id,
            result="success",
            detail=(
                f"paid_on={paid_on.isoformat()}; "
                f"next_payment_date={next_payment_date.isoformat() if next_payment_date else ''}; "
                f"service_expiry_date={payload.service_expiry_date.isoformat()}"
            ),
            ip_address=request.client.host if request.client else None,
        ))
        session.commit()
        session.refresh(subscription)
        await snapshot_manager.refresh_hosts()
        return billing_summary(host_id, subscription)


@router.get("/admin/billing-alerts")
async def get_billing_alert_settings():
    return {"enabled": billing_alerts_enabled()}


@router.put("/admin/billing-alerts")
async def update_billing_alert_settings(
    payload: BillingAlertsUpdateRequest,
    request: Request,
    username: str = Depends(get_current_user),
):
    set_billing_alerts_enabled(payload.enabled)
    with Session(engine) as session:
        session.add(AuditLog(
            user=username,
            action="host.billing_alerts.configure",
            result="success",
            detail=f"enabled={payload.enabled}",
            ip_address=request.client.host if request.client else None,
        ))
        session.commit()
    return {"enabled": payload.enabled}
