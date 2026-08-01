"""One-command Agent enrollment API."""

from __future__ import annotations

import asyncio
import json
import re
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from sqlmodel import Session, select

from app.auth.handler import get_current_user
from app.config import get_settings
from app.database import get_session
from app.models import AuditLog, EnrollmentInvite
from app.schemas import (
    EnrollmentClaimResponse,
    EnrollmentInviteCreateRequest,
    EnrollmentInviteResponse,
    EnrollmentRetryRequest,
)
from app.services.crypto import decrypt_string
from app.services.enrollment_service import (
    build_install_command,
    create_invite,
    decode_install_token,
    expire_invite_if_needed,
    normalize_geolocation,
    resolve_request_source_ip,
    normalize_public_host,
    normalize_url,
    render_install_script,
    token_hash,
    utc_now,
    enrollment_monitor,
)

admin_router = APIRouter(
    prefix="/api/admin/enrollment-invites",
    tags=["enrollment"],
    dependencies=[Depends(get_current_user)],
)
public_router = APIRouter(prefix="/api/enroll", tags=["enrollment"])

_claim_lock = asyncio.Lock()
_rate_window: dict[str, list[float]] = {}
_progress_rate_window: dict[str, list[float]] = {}
_RATE_LIMIT = 12
_RATE_SECONDS = 300
_PROGRESS_RATE_LIMIT = 180


def _admin(username: str) -> str:
    if username != get_settings().ADMIN_USERNAME:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return username


def _audit(session: Session, user: str, action: str, result: str, detail: str, request: Request) -> None:
    session.add(
        AuditLog(
            user=user,
            action=action,
            host_id="",
            result=result,
            detail=detail[:500],
            ip_address=request.client.host if request.client else None,
        )
    )
    session.commit()


def _base_url(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{forwarded_proto}://{forwarded_host}".rstrip("/")


def _response(invite, command: str | None = None) -> EnrollmentInviteResponse:
    return EnrollmentInviteResponse(
        invite_id=invite.invite_id,
        status=invite.status,
        expires_at=invite.expires_at,
        downloaded_at=invite.downloaded_at,
        completed_at=invite.completed_at,
        host_id=invite.host_id,
        agent_instance_id=invite.agent_instance_id,
        agent_port=invite.agent_port,
        stack_root=invite.stack_root,
        agent_image=invite.agent_image,
        agent_public_host=invite.agent_public_host,
        agent_public_url=f"https://{invite.agent_public_host}" if invite.agent_public_host else "",
        failure_reason=invite.failure_reason,
        install_command=command,
    )


def _rate_limited(request: Request) -> bool:
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    valid = [stamp for stamp in _rate_window.get(key, []) if stamp > now - _RATE_SECONDS]
    valid.append(now)
    _rate_window[key] = valid
    return len(valid) > _RATE_LIMIT


def _progress_rate_limited(request: Request) -> bool:
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    valid = [stamp for stamp in _progress_rate_window.get(key, []) if stamp > now - _RATE_SECONDS]
    valid.append(now)
    _progress_rate_window[key] = valid
    return len(valid) > _PROGRESS_RATE_LIMIT


@admin_router.post("", response_model=EnrollmentInviteResponse)
async def create_enrollment_invite(
    req: EnrollmentInviteCreateRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    username = _admin(username)
    if not 1 <= req.agent_port <= 65535:
        raise HTTPException(status_code=400, detail="agent_port must be between 1 and 65535")
    if not re.fullmatch(r"/[A-Za-z0-9._~+/@:-]*", req.stack_root):
        raise HTTPException(status_code=400, detail="stack_root must be an absolute Linux path")
    agent_image = (req.agent_image or get_settings().ENROLLMENT_AGENT_IMAGE).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:-]*", agent_image):
        raise HTTPException(status_code=400, detail="Invalid agent image")
    dashboard_url = normalize_url(req.dashboard_url or _base_url(request))
    if not dashboard_url or any(char in dashboard_url for char in "'\"\\\r\n"):
        raise HTTPException(status_code=400, detail="dashboard_url must be http(s)")
    agent_public_host = normalize_public_host(req.agent_public_host)
    if not agent_public_host:
        raise HTTPException(status_code=400, detail="agent_public_host must be a concrete public hostname")
    duplicate_host = session.exec(
        select(EnrollmentInvite).where(
            EnrollmentInvite.agent_public_host == agent_public_host,
            EnrollmentInvite.status.in_(["issued", "downloaded", "verifying"]),  # type: ignore[attr-defined]
        )
    ).first()
    if duplicate_host:
        raise HTTPException(status_code=409, detail="This Agent hostname already has an active invitation")
    invite, install_token = create_invite(
        session, username, dashboard_url, agent_public_host, req.stack_root.rstrip("/") or "/", req.agent_port, agent_image
    )
    _audit(session, username, "enrollment.invite.create", "success", f"invite_id={invite.invite_id}", request)
    return _response(invite, build_install_command(dashboard_url, install_token))


@admin_router.get("", response_model=list[EnrollmentInviteResponse])
async def list_enrollment_invites(
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    _admin(username)
    invites = session.exec(select(EnrollmentInvite).order_by(EnrollmentInvite.created_at.desc())).all()
    changed = False
    for invite in invites:
        if expire_invite_if_needed(invite):
            changed = True
    if changed:
        session.commit()
    return [_response(invite) for invite in invites]


@admin_router.delete("/{invite_id}", response_model=EnrollmentInviteResponse)
async def revoke_enrollment_invite(
    invite_id: str,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    username = _admin(username)
    invite = session.exec(select(EnrollmentInvite).where(EnrollmentInvite.invite_id == invite_id)).first()
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invite.status not in {"active", "expired"}:
        invite.status = "revoked"
        invite.agent_token_encrypted = None
        invite.secret_path = None
        invite.failure_reason = "Revoked by administrator"
        session.commit()
    _audit(session, username, "enrollment.invite.revoke", "success", f"invite_id={invite_id}", request)
    return _response(invite)


@admin_router.post("/{invite_id}/retry", response_model=EnrollmentClaimResponse)
async def retry_enrollment(
    invite_id: str,
    req: EnrollmentRetryRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    username = _admin(username)
    invite = session.exec(select(EnrollmentInvite).where(EnrollmentInvite.invite_id == invite_id)).first()
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if expire_invite_if_needed(invite) or invite.status in {"revoked", "expired", "active"}:
        session.commit()
        raise HTTPException(status_code=409, detail=f"Invitation is {invite.status}")
    if invite.agent_token_encrypted is None or invite.secret_path is None:
        raise HTTPException(status_code=409, detail="Invitation credentials are no longer available")
    invite.status = "verifying"
    invite.failure_reason = None
    session.commit()
    enrollment_monitor.wake()
    _audit(session, username, "enrollment.invite.retry", "success", f"invite_id={invite_id}", request)
    return EnrollmentClaimResponse(
        status="verifying",
        agent_public_url=f"https://{invite.agent_public_host}",
        message="主控已重新开始验证",
    )


@public_router.get("/install/{install_token}", response_class=PlainTextResponse)
async def download_install_script(install_token: str, request: Request, session: Session = Depends(get_session)):
    if _rate_limited(request):
        raise HTTPException(status_code=429, detail="Too many enrollment requests")
    decoded = decode_install_token(install_token)
    if decoded is None:
        raise HTTPException(status_code=404, detail="Invalid enrollment token")
    invite_id, claim_token = decoded
    invite = session.exec(select(EnrollmentInvite).where(EnrollmentInvite.invite_id == invite_id)).first()
    if invite is None or token_hash(install_token) != invite.install_token_hash:
        raise HTTPException(status_code=404, detail="Invalid enrollment token")
    if expire_invite_if_needed(invite):
        session.commit()
        raise HTTPException(status_code=410, detail="Enrollment invitation expired")
    if invite.status not in {"issued"}:
        raise HTTPException(status_code=409, detail="Enrollment invitation already used")
    invite.status = "downloaded"
    invite.downloaded_at = utc_now()
    session.commit()
    agent_token = decrypt_string(invite.agent_token_encrypted or "")
    script = render_install_script(invite, claim_token, agent_token, invite.dashboard_url)
    return PlainTextResponse(script, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@public_router.post("/claim", response_model=EnrollmentClaimResponse)
async def claim_enrollment(
    request: Request,
    response: Response,
    claim_token: str = Form(...),
    hostname: str = Form(...),
    instance_id: str = Form(...),
    agent_public_host: str = Form(...),
    geolocation: str = Form(""),
    callback_mode: str = Form("unknown"),
    session: Session = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    if _rate_limited(request):
        raise HTTPException(status_code=429, detail="Too many enrollment requests")
    location = None
    if geolocation:
        try:
            location = normalize_geolocation(json.loads(geolocation))
        except (ValueError, TypeError):
            location = None
    if location:
        location["source"] = "legacy_untrusted"
    async with _claim_lock:
        invite = session.exec(select(EnrollmentInvite).where(EnrollmentInvite.claim_token_hash == token_hash(claim_token))).first()
        if invite is None:
            raise HTTPException(status_code=404, detail="Invalid claim token")
        if expire_invite_if_needed(invite):
            session.commit()
            raise HTTPException(status_code=410, detail="Enrollment invitation expired")
        if invite.status not in {"downloaded", "verifying", "needs_url", "failed"}:
            raise HTTPException(status_code=409, detail=f"Enrollment invitation is {invite.status}")
        if normalize_public_host(agent_public_host) != invite.agent_public_host:
            raise HTTPException(status_code=400, detail="Agent hostname does not match invitation")
        if not re.fullmatch(r"[A-Za-z0-9._-]{8,128}", instance_id.strip()):
            raise HTTPException(status_code=400, detail="Invalid Agent instance ID")
        invite.status = "verifying"
        invite.hostname = hostname.strip()[:120]
        invite.agent_instance_id = instance_id.strip()
        invite.failure_reason = None
        invite.location_payload = json.dumps(location, ensure_ascii=False) if location else None
        invite.callback_ip = resolve_request_source_ip(request)
        invite.callback_mode = callback_mode if callback_mode in {"direct", "proxy_fallback"} else "unknown"
        session.commit()
    enrollment_monitor.wake()
    return EnrollmentClaimResponse(
        status="verifying",
        agent_public_url=f"https://{invite.agent_public_host}",
        location=location,
        message="主控正在验证 DNS、HTTPS 和 Agent 身份",
    )


@public_router.post("/status", response_model=EnrollmentClaimResponse)
async def enrollment_status(
    request: Request,
    response: Response,
    claim_token: str = Form(...),
    session: Session = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    if _progress_rate_limited(request):
        raise HTTPException(status_code=429, detail="Too many enrollment requests")
    invite = session.exec(
        select(EnrollmentInvite).where(EnrollmentInvite.claim_token_hash == token_hash(claim_token))
    ).first()
    if invite is None:
        raise HTTPException(status_code=404, detail="Invalid claim token")
    if expire_invite_if_needed(invite):
        session.commit()
    return EnrollmentClaimResponse(
        status=invite.status,
        host_id=invite.host_id,
        agent_public_url=f"https://{invite.agent_public_host}" if invite.agent_public_host else None,
        message=invite.failure_reason or ("Host 已自动启用" if invite.status == "active" else "主控正在验证 DNS、HTTPS 和 Agent 身份"),
    )
