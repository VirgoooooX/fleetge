"""Settings API router — view and update system configurations."""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.auth.handler import get_current_user
from app.database import get_session
from app.models import AuditLog
from app.schemas import SettingsResponse, SettingItem, SettingsUpdateRequest
from app.services.settings_service import (
    get_setting_value,
    update_setting_value,
    clear_cache,
    WRITABLE_KEYS,
)
from app.services.snapshot import snapshot_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)


def _write_audit_log(
    session: Session,
    user: str,
    action: str,
    host_id: str,
    result: str,
    detail: str | None = None,
    ip_address: str | None = None,
):
    log = AuditLog(
        user=user,
        action=action,
        host_id=host_id,
        result=result,
        detail=detail,
        ip_address=ip_address,
    )
    session.add(log)
    session.commit()


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
            "key": "ADMIN_PASSWORD_HASH",
            "type": "password",
            "description": "管理员密码哈希值（只读，通过环境变量修改，需重启）",
        },
    ]

    for cfg in readonly_configs:
        val = get_setting_value(cfg["key"])
        items.append(
            SettingItem(
                key=cfg["key"],
                value=str(val),
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
    username: str = Depends(get_current_user),
):
    """Bulk update system configurations. Restarts poll loops if intervals changed."""
    ip = request.client.host if request.client else None

    # 1. Validate keys and values
    for key, val in req.settings.items():
        if key not in WRITABLE_KEYS:
            _write_audit_log(
                session, username, "settings.update", "", "error",
                f"Setting '{key}' is read-only or invalid", ip
            )
            raise HTTPException(status_code=400, detail=f"Setting '{key}' is read-only or invalid")

        # Basic type validations
        if key in ["DOCKER_POLL_INTERVAL", "BACKGROUND_STRUCTURE_REFRESH_INTERVAL", "UPDATE_CHECK_INTERVAL", "JWT_EXPIRE_HOURS"]:
            try:
                int_val = int(val)
                if key == "DOCKER_POLL_INTERVAL" and not (5 <= int_val <= 300):
                    raise ValueError("DOCKER_POLL_INTERVAL must be between 5 and 300")
                if key == "BACKGROUND_STRUCTURE_REFRESH_INTERVAL" and not (60 <= int_val <= 86400):
                    raise ValueError("BACKGROUND_STRUCTURE_REFRESH_INTERVAL must be between 60 and 86400")
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

    # 2. Perform updates
    changes = []
    interval_changed = False

    for key, val in req.settings.items():
        old_val = get_setting_value(key)
        if str(old_val) != str(val):
            update_setting_value(session, key, val)
            changes.append(f"{key}: {old_val}→{val}")
            if key in ["DOCKER_POLL_INTERVAL", "METRICS_STREAM_INTERVAL", "BACKGROUND_STRUCTURE_REFRESH_INTERVAL", "UPDATE_CHECK_INTERVAL"]:
                interval_changed = True

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

    return await get_settings_list()
