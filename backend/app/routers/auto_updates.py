"""Automatic update preferences and optional Notify Hub configuration."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth.handler import get_current_user
from app.database import engine
from app.models import AuditLog, AutoUpdateRun
from app.services.agent_client import AgentClient
from app.services.auto_update import control_stack, notify_settings, save_notify_settings, set_policy, stack_policy
from app.services.snapshot import snapshot_manager

router = APIRouter(prefix="/api", tags=["auto_updates"], dependencies=[Depends(get_current_user)])


class AutoUpdateRequest(BaseModel):
    enabled: bool


class NotifyHubRequest(BaseModel):
    url: str = Field(default="", max_length=2048)
    recipient: str = Field(default="", max_length=128)
    api_key: str | None = Field(default=None, max_length=1024)


def require_stack(host_id: str, stack_name: str):
    snap = snapshot_manager.get_snapshot(host_id)
    if not snap or not snap.host_config:
        raise HTTPException(404, "Host not found")
    stack = next((s for s in snap.stacks if s.name == stack_name), None)
    if stack is None:
        raise HTTPException(404, "Stack not found")
    return snap, stack


async def unavailable_reason(snap, stack) -> str:
    if not stack.compose_file or stack.management_status == "unmanaged":
        return "该 Stack 没有可管理的 Compose 配置。"
    if not snap.host_config.agent_url:
        return "主机未配置 Agent。"
    conn = AgentClient(snap.host_config)
    try:
        info = await conn.get_self()
        if not info.get("stack_name"):
            return "无法确认 Agent 所属 Stack，暂不能开启自动更新。"
        if control_stack(snap, stack.name, info):
            return "Fleetge／Agent 自身所在的 Stack 暂不支持自动更新。"
    except Exception:
        return "无法连接 Agent 确认身份，暂不能开启自动更新。"
    finally:
        await conn.close()
    return ""


@router.get("/hosts/{host_id}/stacks/{stack_name}/auto-update")
async def get_auto_update(host_id: str, stack_name: str):
    snap, stack = require_stack(host_id, stack_name)
    policy = stack_policy(host_id, stack_name)
    with Session(engine) as session:
        run = session.exec(select(AutoUpdateRun).where(AutoUpdateRun.host_id == host_id, AutoUpdateRun.stack_name == stack_name).order_by(AutoUpdateRun.id.desc())).first()
    return {
        "enabled": policy.enabled, "reason": policy.reason,
        "unavailable_reason": await unavailable_reason(snap, stack),
        "last_run": None if not run else {
            "status": run.status, "attempts": run.attempts, "stage": run.stage,
            "detail": run.detail, "started_at": run.started_at, "finished_at": run.finished_at,
            "notify_status": run.notify_status, "notify_error": run.notify_error,
        },
    }


@router.put("/hosts/{host_id}/stacks/{stack_name}/auto-update")
async def update_auto_update(host_id: str, stack_name: str, payload: AutoUpdateRequest, request: Request, username: str = Depends(get_current_user)):
    snap, stack = require_stack(host_id, stack_name)
    if payload.enabled:
        reason = await unavailable_reason(snap, stack)
        if reason:
            raise HTTPException(409, reason)
    policy = set_policy(host_id, stack_name, payload.enabled)
    with Session(engine) as session:
        session.add(AuditLog(user=username, action="stack.auto_update.configure", host_id=host_id, stack_name=stack_name, result="success", detail=f"enabled={payload.enabled}", ip_address=request.client.host if request.client else None))
        session.commit()
    return {"enabled": policy.enabled, "reason": policy.reason}


@router.get("/admin/notifyhub")
async def get_notifyhub():
    config = notify_settings()
    return {"url": config.get("NOTIFYHUB_URL", ""), "recipient": config.get("NOTIFYHUB_RECIPIENT", ""), "key_configured": bool(config.get("NOTIFYHUB_KEY"))}


@router.put("/admin/notifyhub")
async def update_notifyhub(payload: NotifyHubRequest, username: str = Depends(get_current_user)):
    try:
        save_notify_settings(payload.url, payload.recipient, payload.api_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with Session(engine) as session:
        session.add(AuditLog(user=username, action="notifyhub.configure", result="success", detail="Notify Hub settings updated"))
        session.commit()
    return await get_notifyhub()
