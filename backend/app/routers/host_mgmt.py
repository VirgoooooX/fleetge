"""Host management API router — list, create, update, delete, test connections, and manage stack icons."""

import os
import re
import json
import logging
import time
import base64
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlmodel import Session, select, delete

from app.auth.handler import get_current_user
from app.database import get_session, engine
from app.models import HostConfig, AuditLog, ImageUpdateCache
from app.schemas import (
    HostConfigResponse,
    HostCreateRequest,
    HostUpdateRequest,
    ConnectionTestResponse,
    StackIconEntry,
    StackIconsUpdateRequest,
)
from app.services.crypto import (
    encrypt_credentials,
    encrypt_authorization_header,
    encrypt_string,
    decrypt_credentials,
    decrypt_authorization_header,
)
from app.services.host_writer import write_hosts_to_yaml
from app.services.snapshot import snapshot_manager
from app.config import get_settings
from app.services.agent_client import AgentClient
from app.services.docker_proxy import DockerProxyClient
from app.services.metrics_client import MetricsClient
from app.services.dockge_client import dockge_pool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["host-management"],
    dependencies=[Depends(get_current_user)],
)

# Resolve Stack Icons Directory
_HOST_CONFIG_PATH = Path(get_settings().HOST_CONFIG_PATH).expanduser()
if not _HOST_CONFIG_PATH.is_absolute():
    _HOST_CONFIG_PATH = Path.cwd() / _HOST_CONFIG_PATH
_STACK_ICONS_DIR = _HOST_CONFIG_PATH.parent / "stack_icons"
_STACK_ICONS_DIR.mkdir(parents=True, exist_ok=True)


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


async def _test_connection_logic(cfg: HostConfig, dockge_password_plain: str | None = None, docker_proxy_password_plain: str | None = None, metrics_password_plain: str | None = None, agent_token_plain: str | None = None) -> ConnectionTestResponse:
    start_time = time.monotonic()
    
    try:
        if cfg.agent_url:
            # Agent Mode
            if agent_token_plain is not None:
                temp_cfg = HostConfig(
                    host_id=cfg.host_id,
                    agent_url=cfg.agent_url,
                    agent_token_encrypted=encrypt_string(agent_token_plain) if agent_token_plain else None
                )
                client = AgentClient(temp_cfg)
            else:
                client = AgentClient(cfg)
                
            try:
                success = await client.ping()
                if not success:
                    await client.info()
                    success = True
            except Exception as e:
                duration = int((time.monotonic() - start_time) * 1000)
                return ConnectionTestResponse(
                    success=False,
                    response_time_ms=duration,
                    message=f"Agent connection failed: {str(e)}"
                )
            finally:
                await client.close()
                
            duration = int((time.monotonic() - start_time) * 1000)
            if success:
                return ConnectionTestResponse(success=True, response_time_ms=duration, message="Agent connection successful")
            else:
                return ConnectionTestResponse(success=False, response_time_ms=duration, message="Agent ping failed")
        else:
            # Legacy Mode
            legacy_checks = []
            
            # 1. Dockge Check
            if cfg.dockge_url:
                try:
                    if dockge_password_plain is not None:
                        pwd = dockge_password_plain
                    elif cfg.dockge_password_encrypted:
                        creds = decrypt_credentials(cfg.dockge_password_encrypted)
                        pwd = creds["password"]
                    else:
                        pwd = ""
                        
                    conn = await dockge_pool.get_or_create(cfg, pwd)
                    is_ok = await conn.is_connected()
                    if is_ok:
                        legacy_checks.append("Dockge OK")
                    else:
                        legacy_checks.append("Dockge ping failed")
                except Exception as e:
                    legacy_checks.append(f"Dockge failed: {str(e)}")
            
            # 2. Docker Proxy Check
            if cfg.docker_proxy_url:
                temp_cfg = HostConfig(
                    host_id=cfg.host_id,
                    docker_proxy_url=cfg.docker_proxy_url,
                )
                if docker_proxy_password_plain is not None:
                    if docker_proxy_password_plain:
                        # For testing connection, standard basic auth is Basic b64encode(username:password)
                        # We use a dummy username since it's empty in this case or if we just want raw Basic header
                        temp_cfg.docker_proxy_auth_encrypted = encrypt_authorization_header("", docker_proxy_password_plain)
                else:
                    temp_cfg.docker_proxy_auth_encrypted = cfg.docker_proxy_auth_encrypted
                    
                client = DockerProxyClient(temp_cfg)
                try:
                    success = await client.ping()
                    if success:
                        legacy_checks.append("Docker Proxy OK")
                    else:
                        legacy_checks.append("Docker Proxy ping failed")
                except Exception as e:
                    legacy_checks.append(f"Docker Proxy failed: {str(e)}")
                finally:
                    await client.close()

            # 3. Metrics Check
            if cfg.metrics_url:
                temp_cfg = HostConfig(
                    host_id=cfg.host_id,
                    metrics_url=cfg.metrics_url,
                )
                if metrics_password_plain is not None:
                    if metrics_password_plain:
                        temp_cfg.metrics_auth_encrypted = encrypt_authorization_header("", metrics_password_plain)
                else:
                    temp_cfg.metrics_auth_encrypted = cfg.metrics_auth_encrypted
                    
                client = MetricsClient(temp_cfg)
                try:
                    await client.fetch()
                    legacy_checks.append("Metrics Exporter OK")
                except Exception as e:
                    legacy_checks.append(f"Metrics Exporter failed: {str(e)}")
                finally:
                    await client.close()

            duration = int((time.monotonic() - start_time) * 1000)
            if not legacy_checks:
                return ConnectionTestResponse(success=False, response_time_ms=duration, message="No connection URLs configured")
                
            has_failures = any("failed" in check or "failed" in check.lower() or "Failed" in check for check in legacy_checks)
            message = " | ".join(legacy_checks)
            return ConnectionTestResponse(success=not has_failures, response_time_ms=duration, message=message)
            
    except Exception as e:
        duration = int((time.monotonic() - start_time) * 1000)
        return ConnectionTestResponse(success=False, response_time_ms=duration, message=f"Unexpected error: {str(e)}")


def _to_response_model(h: HostConfig) -> HostConfigResponse:
    stack_icons_parsed = None
    if h.stack_icons:
        try:
            stack_icons_parsed = json.loads(h.stack_icons)
        except Exception:
            pass
            
    return HostConfigResponse(
        host_id=h.host_id,
        display_name=h.display_name,
        enabled=h.enabled,
        sort_order=h.sort_order,
        agent_url=h.agent_url,
        has_agent_token=bool(h.agent_token_encrypted),
        dockge_url=h.dockge_url,
        dockge_username=h.dockge_username,
        has_dockge_password=bool(h.dockge_password_encrypted),
        docker_proxy_url=h.docker_proxy_url,
        has_docker_proxy_auth=bool(h.docker_proxy_auth_encrypted),
        metrics_url=h.metrics_url,
        has_metrics_auth=bool(h.metrics_auth_encrypted),
        stack_icons=stack_icons_parsed,
    )


@router.get("/hosts", response_model=list[HostConfigResponse])
async def list_hosts(session: Session = Depends(get_session)):
    """List all Host configurations, with secrets masked."""
    hosts = session.exec(select(HostConfig)).all()
    # Sort by sort_order, then ID
    sorted_hosts = sorted(hosts, key=lambda h: (h.sort_order, h.id or 0))
    return [_to_response_model(h) for h in sorted_hosts]


@router.post("/hosts", response_model=HostConfigResponse)
async def create_host(
    req: HostCreateRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Create a new Host configuration, write to hosts.yaml and update poller."""
    ip = request.client.host if request.client else None

    # Validate host_id pattern
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", req.host_id):
        _write_audit_log(session, username, "host.create", req.host_id, "error", "Invalid host_id pattern", ip)
        raise HTTPException(
            status_code=400,
            detail="host_id must start with lowercase letter/number and contain only lowercase letters, numbers, and hyphens"
        )

    # Check for duplicates
    existing = session.exec(select(HostConfig).where(HostConfig.host_id == req.host_id)).first()
    if existing:
        _write_audit_log(session, username, "host.create", req.host_id, "error", "Duplicate host_id", ip)
        raise HTTPException(status_code=400, detail=f"Host ID '{req.host_id}' already exists")

    # Validate URL structures
    for name, url in [("agent_url", req.agent_url), ("dockge_url", req.dockge_url), ("docker_proxy_url", req.docker_proxy_url), ("metrics_url", req.metrics_url)]:
        if url and not re.match(r"^https?://", url):
            _write_audit_log(session, username, "host.create", req.host_id, "error", f"Invalid URL for {name}", ip)
            raise HTTPException(status_code=400, detail=f"{name} must start with http:// or https://")

    # Encrypt credentials
    dockge_password_encrypted = ""
    if req.dockge_password:
        if req.dockge_password != "[ENCRYPTED]":
            dockge_password_encrypted = encrypt_credentials(req.dockge_username or "", req.dockge_password)

    dp_auth = None
    if req.docker_proxy_password:
        if req.docker_proxy_password != "[ENCRYPTED]":
            dp_auth = encrypt_authorization_header(req.docker_proxy_username or "", req.docker_proxy_password)

    m_auth = None
    if req.metrics_password:
        if req.metrics_password != "[ENCRYPTED]":
            m_auth = encrypt_authorization_header(req.metrics_username or "", req.metrics_password)

    agent_token_encrypted = None
    if req.agent_token:
        if req.agent_token != "[ENCRYPTED]":
            agent_token_encrypted = encrypt_string(req.agent_token)

    # Create model
    host = HostConfig(
        host_id=req.host_id,
        display_name=req.display_name,
        enabled=req.enabled,
        sort_order=req.sort_order,
        dockge_url=req.dockge_url or "",
        dockge_username=req.dockge_username or "",
        dockge_password_encrypted=dockge_password_encrypted,
        docker_proxy_url=req.docker_proxy_url or "",
        docker_proxy_auth_encrypted=dp_auth,
        metrics_url=req.metrics_url or "",
        metrics_auth_encrypted=m_auth,
        agent_url=req.agent_url,
        agent_token_encrypted=agent_token_encrypted,
    )

    session.add(host)
    session.commit()
    session.refresh(host)

    # Sync back to hosts.yaml and update runtime
    write_hosts_to_yaml()
    await snapshot_manager.refresh_hosts()

    _write_audit_log(session, username, "host.create", req.host_id, "success", f"host_id={req.host_id}", ip)
    return _to_response_model(host)


@router.put("/hosts/{host_id}", response_model=HostConfigResponse)
async def update_host(
    host_id: str,
    req: HostUpdateRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Update a Host configuration, write to hosts.yaml and update poller."""
    ip = request.client.host if request.client else None

    # Fetch existing
    existing = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
    if not existing:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    # Validate URLs
    for name, url in [("agent_url", req.agent_url), ("dockge_url", req.dockge_url), ("docker_proxy_url", req.docker_proxy_url), ("metrics_url", req.metrics_url)]:
        if url and not re.match(r"^https?://", url):
            _write_audit_log(session, username, "host.update", host_id, "error", f"Invalid URL for {name}", ip)
            raise HTTPException(status_code=400, detail=f"{name} must start with http:// or https://")

    # Keep track of fields updated
    fields_updated = []
    
    if existing.display_name != req.display_name:
        existing.display_name = req.display_name
        fields_updated.append("display_name")
        
    if existing.enabled != req.enabled:
        existing.enabled = req.enabled
        fields_updated.append("enabled")
        
    if existing.sort_order != req.sort_order:
        existing.sort_order = req.sort_order
        fields_updated.append("sort_order")
        
    if existing.dockge_url != (req.dockge_url or ""):
        existing.dockge_url = req.dockge_url or ""
        fields_updated.append("dockge_url")
        
    if existing.dockge_username != (req.dockge_username or ""):
        existing.dockge_username = req.dockge_username or ""
        fields_updated.append("dockge_username")
        
    if existing.docker_proxy_url != (req.docker_proxy_url or ""):
        existing.docker_proxy_url = req.docker_proxy_url or ""
        fields_updated.append("docker_proxy_url")
        
    if existing.metrics_url != (req.metrics_url or ""):
        existing.metrics_url = req.metrics_url or ""
        fields_updated.append("metrics_url")
        
    if existing.agent_url != req.agent_url:
        existing.agent_url = req.agent_url
        fields_updated.append("agent_url")

    # Update passwords/tokens safely
    # Dockge password
    if req.dockge_password is None:
        if existing.dockge_password_encrypted and req.dockge_username != existing.dockge_username:
            try:
                decrypted = decrypt_credentials(existing.dockge_password_encrypted)
                existing.dockge_password_encrypted = encrypt_credentials(
                    req.dockge_username or "",
                    decrypted.get("password", "")
                )
                fields_updated.append("dockge_password (re-encrypted for new username)")
            except Exception as e:
                logger.error("Failed to decrypt/re-encrypt dockge credentials during update: %s", e)
    elif req.dockge_password == "":
        existing.dockge_password_encrypted = ""
        fields_updated.append("dockge_password (cleared)")
    else:
        existing.dockge_password_encrypted = encrypt_credentials(req.dockge_username or "", req.dockge_password)
        fields_updated.append("dockge_password (updated)")

    # docker-proxy auth
    if req.docker_proxy_password is None:
        if existing.docker_proxy_auth_encrypted and req.docker_proxy_username != "":
            # Reconstruct basic auth header with updated username if required
            try:
                header_val = decrypt_authorization_header(existing.docker_proxy_auth_encrypted)
                if header_val.startswith("Basic "):
                    encoded = header_val[len("Basic "):]
                    raw = base64.b64decode(encoded.encode("utf-8")).decode("utf-8")
                    parts = raw.split(":", 1)
                    pwd = parts[1] if len(parts) > 1 else ""
                    existing.docker_proxy_auth_encrypted = encrypt_authorization_header(
                        req.docker_proxy_username or "", pwd
                    )
                    fields_updated.append("docker_proxy_auth (re-encrypted for new username)")
            except Exception as e:
                logger.error("Failed to decrypt/re-encrypt docker-proxy auth during update: %s", e)
    elif req.docker_proxy_password == "":
        existing.docker_proxy_auth_encrypted = None
        fields_updated.append("docker_proxy_auth (cleared)")
    else:
        existing.docker_proxy_auth_encrypted = encrypt_authorization_header(
            req.docker_proxy_username or "", req.docker_proxy_password
        )
        fields_updated.append("docker_proxy_auth (updated)")

    # metrics auth
    if req.metrics_password is None:
        if existing.metrics_auth_encrypted and req.metrics_username != "":
            try:
                header_val = decrypt_authorization_header(existing.metrics_auth_encrypted)
                if header_val.startswith("Basic "):
                    encoded = header_val[len("Basic "):]
                    raw = base64.b64decode(encoded.encode("utf-8")).decode("utf-8")
                    parts = raw.split(":", 1)
                    pwd = parts[1] if len(parts) > 1 else ""
                    existing.metrics_auth_encrypted = encrypt_authorization_header(
                        req.metrics_username or "", pwd
                    )
                    fields_updated.append("metrics_auth (re-encrypted for new username)")
            except Exception as e:
                logger.error("Failed to decrypt/re-encrypt metrics auth during update: %s", e)
    elif req.metrics_password == "":
        existing.metrics_auth_encrypted = None
        fields_updated.append("metrics_auth (cleared)")
    else:
        existing.metrics_auth_encrypted = encrypt_authorization_header(
            req.metrics_username or "", req.metrics_password
        )
        fields_updated.append("metrics_auth (updated)")

    # agent token
    if req.agent_token is None:
        pass
    elif req.agent_token == "":
        existing.agent_token_encrypted = None
        fields_updated.append("agent_token (cleared)")
    else:
        existing.agent_token_encrypted = encrypt_string(req.agent_token)
        fields_updated.append("agent_token (updated)")

    if fields_updated:
        session.commit()
        session.refresh(existing)
        write_hosts_to_yaml()
        await snapshot_manager.refresh_hosts()
        _write_audit_log(session, username, "host.update", host_id, "success", f"fields updated: {', '.join(fields_updated)}", ip)
    else:
        _write_audit_log(session, username, "host.update", host_id, "success", "no changes detected", ip)

    return _to_response_model(existing)


@router.delete("/hosts/{host_id}")
async def delete_host(
    host_id: str,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Delete a Host configuration, purge its caches, write to hosts.yaml and update runtime."""
    ip = request.client.host if request.client else None

    host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
    if not host:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    # Cascade deletes: delete ImageUpdateCache records for this host
    session.exec(delete(ImageUpdateCache).where(ImageUpdateCache.host_id == host_id))
    
    # Delete the HostConfig record
    session.delete(host)
    session.commit()

    # Sync to hosts.yaml and rebuild poller state
    write_hosts_to_yaml()
    await snapshot_manager.refresh_hosts()

    _write_audit_log(session, username, "host.delete", host_id, "success", f"host_id={host_id}", ip)
    return {"success": True, "message": f"Host '{host_id}' deleted successfully"}


@router.post("/hosts/{host_id}/test-connection", response_model=ConnectionTestResponse)
async def test_existing_host_connection(
    host_id: str,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Test connection for an existing host configuration in database."""
    ip = request.client.host if request.client else None

    host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
    if not host:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    res = await _test_connection_logic(host)
    _write_audit_log(session, username, "host.test_connection", host_id, "success" if res.success else "error", res.message, ip)
    return res


@router.post("/hosts/test-connection", response_model=ConnectionTestResponse)
async def test_new_host_connection(
    req: HostCreateRequest,
    request: Request,
    username: str = Depends(get_current_user),
):
    """Test connection with unsaved parameters before creating a host."""
    # Construct a temp HostConfig block
    temp_cfg = HostConfig(
        host_id=req.host_id,
        agent_url=req.agent_url,
        dockge_url=req.dockge_url or "",
        dockge_username=req.dockge_username or "",
        docker_proxy_url=req.docker_proxy_url or "",
        metrics_url=req.metrics_url or "",
    )

    res = await _test_connection_logic(
        temp_cfg,
        dockge_password_plain=req.dockge_password,
        docker_proxy_password_plain=req.docker_proxy_password,
        metrics_password_plain=req.metrics_password,
        agent_token_plain=req.agent_token,
    )
    return res


# ── Stack Icons Management Endpoints ────────────────────────────────────

@router.get("/hosts/{host_id}/stack-icons")
async def get_stack_icons(
    host_id: str,
    session: Session = Depends(get_session),
):
    """Get stack icons mapping for a host and list available local files."""
    host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
    if not host:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    # Parse JSON
    icons_list = []
    if host.stack_icons:
        try:
            data = json.loads(host.stack_icons)
            if isinstance(data, dict):
                for k, v in data.items():
                    icons_list.append(StackIconEntry(stack_pattern=k, icon_value=v))
        except Exception:
            pass

    # Read available local files in stack_icons folder
    available_files = []
    if _STACK_ICONS_DIR.exists() and _STACK_ICONS_DIR.is_dir():
        for entry in os.scandir(_STACK_ICONS_DIR):
            if entry.is_file() and entry.name.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")):
                available_files.append(entry.name)
    available_files.sort()

    return {
        "icons": icons_list,
        "available_files": available_files,
    }


@router.put("/hosts/{host_id}/stack-icons")
async def update_stack_icons(
    host_id: str,
    req: StackIconsUpdateRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Update stack icons mapping JSON block for a host, write to hosts.yaml and update runtime."""
    ip = request.client.host if request.client else None

    host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
    if not host:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    # Convert mapping back to dict
    icons_dict = {}
    for entry in req.icons:
        if entry.stack_pattern.strip() and entry.icon_value.strip():
            icons_dict[entry.stack_pattern.strip()] = entry.icon_value.strip()

    # Save to db
    host.stack_icons = json.dumps(icons_dict, ensure_ascii=False) if icons_dict else None
    session.add(host)
    session.commit()

    # Sync
    write_hosts_to_yaml()
    await snapshot_manager.refresh_hosts()

    _write_audit_log(
        session, username, "host.stack_icons.update", host_id, "success",
        f"updated {len(icons_dict)} stack icons", ip
    )
    return {"success": True, "message": f"Updated stack icons mapping for host '{host_id}'"}


@router.post("/hosts/{host_id}/stack-icons/upload")
async def upload_stack_icon_file(
    host_id: str,
    file: UploadFile = File(...),
    username: str = Depends(get_current_user),
):
    """Upload a local image file for stack icons (Max size: 2MB)."""
    # 1. Size check
    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (maximum size is 2MB)")

    # 2. Extension check
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Only PNG, JPG, JPEG, SVG, WEBP, and GIF are allowed"
        )

    # 3. Sanitize filename
    sanitized_name = re.sub(r"[^\w\-_.]", "_", file.filename)
    if not sanitized_name:
        sanitized_name = f"uploaded_icon_{int(time.time())}{ext}"

    # Write file to target folder
    target_path = _STACK_ICONS_DIR / sanitized_name
    try:
        with open(target_path, "wb") as f:
            f.write(contents)
        logger.info("Saved stack icon file: %s", target_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(exc)}")

    return {"filename": sanitized_name}
