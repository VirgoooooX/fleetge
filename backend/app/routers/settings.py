"""Settings API router — view and update system configurations."""

import logging
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from app.auth.handler import require_admin
from app.database import get_session
from app.schemas import (
    HostMonitorAlertsUpdateRequest,
    SettingsResponse,
    SettingItem,
    SettingsUpdateRequest,
)
from app.services.audit_service import write_audit_log as _write_audit_log
from app.services.host_monitor import (
    host_monitor_alerts_enabled,
    host_monitor_manager,
    host_monitor_notify_clean_reboot,
    set_host_monitor_alert_settings,
)
from app.services.network_utils import resolve_request_source_ip
from app.services.settings_service import (
    get_setting_value,
    update_setting_value,
    clear_cache,
    WRITABLE_KEYS,
)
from app.services.snapshot import snapshot_manager
from app.services.agent_client import AgentClient

logger = logging.getLogger(__name__)


class GlobalEnvUpdateRequest(BaseModel):
    content: str = ""

router = APIRouter(
    prefix="/api/admin",
    tags=["settings"],
    dependencies=[Depends(require_admin)],
)


@router.get("/settings", response_model=SettingsResponse)
async def get_settings_list():
    """Return all writable and read-only settings with metadata."""
    items = []

    # 1. Writable settings
    writable_configs = [
        {
            "key": "DOCKER_POLL_INTERVAL",
            "type": "number",
            "description": "Docker 容器状态轮询间隔（秒）",
            "min_value": 5.0,
            "max_value": 300.0,
            "unit": "秒",
        },
        {
            "key": "METRICS_STREAM_INTERVAL",
            "type": "number",
            "description": "服务器 CPU/内存等指标推送间隔（秒）",
            "min_value": 0.5,
            "max_value": 10.0,
            "unit": "秒",
        },
        {
            "key": "BACKGROUND_STRUCTURE_REFRESH_INTERVAL",
            "type": "number",
            "description": "后台 Compose 目录结构深度扫描间隔（秒）",
            "min_value": 60.0,
            "max_value": 86400.0,
            "unit": "秒",
        },
        {
            "key": "HOST_MONITOR_INTERVAL",
            "type": "number",
            "description": "主机在线状态轻量探活间隔（秒）",
            "min_value": 60.0,
            "max_value": 3600.0,
            "unit": "秒",
        },
        {
            "key": "UPDATE_CHECK_INTERVAL",
            "type": "number",
            "description": "镜像更新后台自动检测间隔（秒）",
            "min_value": 3600.0,
            "max_value": 172800.0,
            "unit": "秒",
        },
        {
            "key": "ADMIN_USERNAME",
            "type": "string",
            "description": "管理员用户名",
        },
        {
            "key": "JWT_EXPIRE_HOURS",
            "type": "number",
            "description": "JWT 登录 Token 有效期（小时）",
            "min_value": 1.0,
            "max_value": 720.0,
            "unit": "小时",
        },
        {
            "key": "ENROLLMENT_AGENT_IMAGE",
            "type": "string",
            "description": "一键入网使用的 Agent 镜像",
        },
        {
            "key": "ENROLLMENT_PROXY_IMAGE",
            "type": "string",
            "description": "一键入网使用的 Caddy 反代镜像",
        },
    ]

    for cfg in writable_configs:
        val = get_setting_value(cfg["key"])
        items.append(
            SettingItem(
                key=cfg["key"],
                value=str(val),
                type=cfg["type"],
                is_writable=True,
                description=cfg["description"],
                min_value=cfg.get("min_value"),
                max_value=cfg.get("max_value"),
                unit=cfg.get("unit"),
            )
        )

    # 2. Read-only settings
    readonly_configs = [
        {
            "key": "JWT_SECRET",
            "type": "password",
            "description": "JWT 签名密钥（只读，通过环境变量修改，需重启）",
        },
        {
            "key": "CREDENTIALS_KEY",
            "type": "password",
            "description": "密码加密 Fernet Key（只读，通过环境变量修改，需重启）",
        },
        {
            "key": "ADMIN_PASSWORD",
            "type": "password",
            "description": "管理员密码明文（只读，通过环境变量修改，需重启）",
        },
    ]

    for cfg in readonly_configs:
        val = get_setting_value(cfg["key"])
        items.append(
            SettingItem(
                key=cfg["key"],
                value="••••••••" if val else "",
                type=cfg["type"],
                is_writable=False,
                description=cfg["description"],
            )
        )

    return SettingsResponse(settings=items)


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    req: SettingsUpdateRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(require_admin),
):
    """Bulk update system configurations. Restarts poll loops if intervals changed."""
    ip = resolve_request_source_ip(request)

    # 1. Validate keys and values
    for key, val in req.settings.items():
        if key not in WRITABLE_KEYS:
            _write_audit_log(
                session, username, "settings.update", "", "error",
                f"Setting '{key}' is read-only or invalid", ip
            )
            raise HTTPException(status_code=400, detail=f"Setting '{key}' is read-only or invalid")

        # Basic type validations
        if key in ["DOCKER_POLL_INTERVAL", "BACKGROUND_STRUCTURE_REFRESH_INTERVAL", "HOST_MONITOR_INTERVAL", "UPDATE_CHECK_INTERVAL", "JWT_EXPIRE_HOURS"]:
            try:
                int_val = int(val)
                if key == "DOCKER_POLL_INTERVAL" and not (5 <= int_val <= 300):
                    raise ValueError("DOCKER_POLL_INTERVAL must be between 5 and 300")
                if key == "BACKGROUND_STRUCTURE_REFRESH_INTERVAL" and not (60 <= int_val <= 86400):
                    raise ValueError("BACKGROUND_STRUCTURE_REFRESH_INTERVAL must be between 60 and 86400")
                if key == "HOST_MONITOR_INTERVAL" and not (60 <= int_val <= 3600):
                    raise ValueError("HOST_MONITOR_INTERVAL must be between 60 and 3600")
                if key == "UPDATE_CHECK_INTERVAL" and not (3600 <= int_val <= 172800):
                    raise ValueError("UPDATE_CHECK_INTERVAL must be between 3600 and 172800")
                if key == "JWT_EXPIRE_HOURS" and not (1 <= int_val <= 720):
                    raise ValueError("JWT_EXPIRE_HOURS must be between 1 and 720")
            except ValueError as e:
                _write_audit_log(
                    session, username, "settings.update", "", "error",
                    f"Validation failed for '{key}': {str(e)}", ip
                )
                raise HTTPException(status_code=400, detail=f"Validation failed for '{key}': {str(e)}")
        elif key == "METRICS_STREAM_INTERVAL":
            try:
                flt_val = float(val)
                if not (0.5 <= flt_val <= 10.0):
                    raise ValueError("METRICS_STREAM_INTERVAL must be between 0.5 and 10.0")
            except ValueError as e:
                _write_audit_log(
                    session, username, "settings.update", "", "error",
                    f"Validation failed for '{key}': {str(e)}", ip
                )
                raise HTTPException(status_code=400, detail=f"Validation failed for '{key}': {str(e)}")
        elif key == "ADMIN_USERNAME":
            if len(val.strip()) < 3:
                _write_audit_log(
                    session, username, "settings.update", "", "error",
                    "ADMIN_USERNAME must be at least 3 characters", ip
                )
                raise HTTPException(status_code=400, detail="ADMIN_USERNAME must be at least 3 characters")
        elif key in {"ENROLLMENT_AGENT_IMAGE", "ENROLLMENT_PROXY_IMAGE"}:
            image = str(val).strip()
            if not image or len(image) > 255 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:-]*", image):
                message = f"{key} must be a valid Docker image reference"
                _write_audit_log(
                    session, username, "settings.update", "", "error", message, ip
                )
                raise HTTPException(status_code=400, detail=message)

    # 2. Perform updates
    changes = []
    interval_changed = False
    monitor_interval_changed = False

    for key, val in req.settings.items():
        old_val = get_setting_value(key)
        if str(old_val) != str(val):
            update_setting_value(session, key, val)
            changes.append(f"{key}: {old_val}→{val}")
            if key in ["DOCKER_POLL_INTERVAL", "METRICS_STREAM_INTERVAL", "BACKGROUND_STRUCTURE_REFRESH_INTERVAL", "UPDATE_CHECK_INTERVAL"]:
                interval_changed = True
            elif key == "HOST_MONITOR_INTERVAL":
                monitor_interval_changed = True

    if changes:
        session.commit()
        clear_cache()

        detail_msg = ", ".join(changes)
        _write_audit_log(
            session, username, "settings.update", "", "success",
            detail_msg, ip
        )

        if interval_changed:
            await snapshot_manager.restart_poll_loops()
        if monitor_interval_changed:
            host_monitor_manager.wake()

    return await get_settings_list()


@router.get("/host-monitor-alerts")
async def get_host_monitor_alert_settings():
    """Return host status notification toggle settings."""
    return {
        "enabled": host_monitor_alerts_enabled(),
        "notify_clean_reboot": host_monitor_notify_clean_reboot(),
    }


@router.put("/host-monitor-alerts")
async def update_host_monitor_alert_settings(
    payload: HostMonitorAlertsUpdateRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(require_admin),
):
    """Update host status notification switches."""
    result = set_host_monitor_alert_settings(
        enabled=payload.enabled,
        notify_clean_reboot=payload.notify_clean_reboot,
    )
    _write_audit_log(
        session,
        username,
        "host.monitor_alerts.configure",
        "",
        "success",
        f"enabled={payload.enabled}, notify_clean_reboot={payload.notify_clean_reboot}",
        resolve_request_source_ip(request),
    )
    session.commit()
    return result


@router.post("/hosts/{host_id}/probe")
async def probe_host_now(host_id: str):
    """Run an immediate liveness and fault-attribution probe for one host."""
    summary = await host_monitor_manager.probe_host(host_id, skip_retry_delay=True)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found or has no agent_url")
    return summary.model_dump()


@router.get("/hosts/{host_id}/global-env")
async def get_host_global_env(host_id: str):
    """Read a host Agent's STACKS_BASE_DIR/global.env."""
    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")
    if not snap.host_config.agent_url:
        raise HTTPException(status_code=400, detail="Host has no agent_url configured")

    conn = AgentClient(snap.host_config)
    try:
        return {"content": await conn.get_global_env()}
    except Exception as exc:
        logger.warning("Failed to fetch global.env from host %s: %s", host_id, exc)
        raise HTTPException(status_code=502, detail="Failed to fetch global.env from Agent")
    finally:
        await conn.close()


@router.put("/hosts/{host_id}/global-env")
async def save_host_global_env(
    host_id: str,
    payload: GlobalEnvUpdateRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(require_admin),
):
    """Write a host Agent's STACKS_BASE_DIR/global.env."""
    snap = snapshot_manager.get_snapshot(host_id)
    ip = resolve_request_source_ip(request)
    if snap is None or snap.host_config is None:
        _write_audit_log(session, username, "host.global_env.update", host_id, "error", "Host not found", ip)
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")
    if not snap.host_config.agent_url:
        _write_audit_log(session, username, "host.global_env.update", host_id, "error", "Host has no agent_url configured", ip)
        raise HTTPException(status_code=400, detail="Host has no agent_url configured")

    conn = AgentClient(snap.host_config)
    try:
        result = await conn.save_global_env(payload.content)
        _write_audit_log(session, username, "host.global_env.update", host_id, "success", str(result), ip)
        return result
    except Exception as exc:
        logger.warning("Failed to save global.env on host %s: %s", host_id, exc)
        _write_audit_log(session, username, "host.global_env.update", host_id, "error", str(exc)[:500], ip)
        raise HTTPException(status_code=502, detail="Failed to save global.env to Agent")
    finally:
        await conn.close()
