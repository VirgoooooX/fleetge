"""Stack router — list, start, stop, restart, update, logs."""

import asyncio
import logging
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.auth.handler import get_current_user
from app.database import get_session, engine
from app.schemas import (
    StackComposeDetail,
    StackComposeSaveRequest,
    StackOperationResponse,
    StackSummary,
)
from app.services.audit_service import write_audit_log
from app.services.agent_client import AgentClient
from app.services.auto_update import UpdateRunError, auto_update_manager
from app.services.compose_converter import convert_docker_run_to_compose as _convert_docker_run_to_compose
from app.services.snapshot import snapshot_manager
from app.services.stack_streams import (
    _clean_log_text as _clean_log_text,
    _safe_error_detail,
    _sse_event as _sse_event,
    stream_compose_deploy,
    stream_compose_logs,
    stream_service_action,
    stream_stack_action,
    stream_system_prune,
    stream_update_run,
)

logger = logging.getLogger(__name__)


class DockerRunConvertRequest(BaseModel):
    command: str

router = APIRouter(
    prefix="/api",
    tags=["stacks"],
    dependencies=[Depends(get_current_user)],
)

# Whitelisted actions — these map to Agent stack events
ALLOWED_ACTIONS: dict[str, str] = {
    "start": "startStack",
    "stop": "stopStack",
    "down": "downStack",
    "restart": "restartStack",
    "update": "updateStack",
    "delete": "deleteStack",
}

SERVICE_ACTIONS: dict[str, str] = {
    "start": "startService",
    "stop": "stopService",
    "restart": "restartService",
}

def _write_audit_log(
    session: Session,
    user: str,
    action: str,
    host_id: str,
    stack_name: str | None,
    result: str,
    detail: str | None = None,
    ip_address: str | None = None,
):
    write_audit_log(session, user, action, host_id, result, detail, ip_address, stack_name=stack_name)


def _write_audit_log_standalone(
    user: str,
    action: str,
    host_id: str,
    stack_name: str | None,
    result: str,
    detail: str | None = None,
    ip_address: str | None = None,
):
    """Write an audit log entry using an ad-hoc session.

    Use this inside streaming-response generators where ``Depends`` is
    not available.
    """
    from app.database import Session as DbSession

    with DbSession(engine) as session:
        _write_audit_log(session, user, action, host_id, stack_name, result, detail, ip_address)


@router.get("/hosts/{host_id}/stacks", response_model=list[StackSummary])
async def list_stacks(host_id: str):
    """Return all stacks for a host, merged with container states."""
    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")
    from app.services.auto_update import stack_summaries
    return stack_summaries(snap)


@router.post("/compose/convert-docker-run")
async def convert_docker_run(payload: DockerRunConvertRequest):
    """Convert a docker run command into a compose.yaml draft."""
    return {"compose_yaml": _convert_docker_run_to_compose(payload.command)}


def _normalize_stack_detail(stack_name: str, result: Any) -> StackComposeDetail:
    """Normalize Agent getStack response into API shape.

    ``result`` is the data dict directly (or a dict with a ``stack`` key).
    """
    raw = result
    if isinstance(raw, dict):
        stack = raw.get("stack", raw) if isinstance(raw, dict) else {}
    else:
        stack = {}

    if not isinstance(stack, dict):
        stack = {}

    return StackComposeDetail(
        name=stack.get("name") or stack_name,
        compose_yaml=stack.get("composeYAML") or stack.get("compose_yaml") or "",
        compose_env=stack.get("composeENV") or stack.get("compose_env") or "",
        compose_file_name=stack.get("composeFileName") or "compose.yaml",
        is_managed_by_agent=True,
    )


@router.get(
    "/hosts/{host_id}/stacks/{stack_name}/compose",
    response_model=StackComposeDetail,
)
async def get_stack_compose(host_id: str, stack_name: str):
    """Return compose.yaml and .env for a stack.

    Unlike earlier versions, this endpoint does NOT return 409 purely based on
    the managed flag. If the Agent returns compose content, the result is
    returned regardless of the managed flag.
    A 409/404 is only returned when no compose file was returned.
    """
    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    if not snap.host_config.agent_url:
        raise HTTPException(status_code=400, detail="Host has no agent_url configured")

    conn = AgentClient(snap.host_config)
    try:
        result = await conn.get_stack(stack_name)
        detail = _normalize_stack_detail(stack_name, result or {})
        if not detail.compose_yaml.strip():
            raise HTTPException(
                status_code=409,
                detail="Agent did not return a compose file for this stack.",
            )
        return detail
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to get compose detail for %s/%s: %s", host_id, stack_name, exc)
        raise HTTPException(status_code=502, detail=_safe_error_detail(exc))
    finally:
        await conn.close()


async def _save_stack_compose(
    host_id: str,
    stack_name: str,
    payload: StackComposeSaveRequest,
    request: Request,
    session: Session,
    username: str,
) -> StackOperationResponse:
    """Save compose.yaml/.env (non-deploy, fast — no streaming needed)."""
    if not payload.compose_yaml.strip():
        raise HTTPException(status_code=400, detail="compose_yaml cannot be empty")

    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        _write_audit_log(
            session, username, "stack.compose.save",
            host_id, stack_name, "error",
            f"Host '{host_id}' not found",
            request.client.host if request.client else None,
        )
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    if not snap.host_config.agent_url:
        raise HTTPException(status_code=400, detail="Host has no agent_url configured")

    conn = AgentClient(snap.host_config)
    try:
        result = await conn.save_stack(
            stack_name,
            payload.compose_yaml,
            payload.compose_env,
            compose_file_name=payload.compose_file_name,
            deploy=False,
            is_add=payload.is_add,
        )

        _write_audit_log(
            session, username, "stack.compose.save",
            host_id, stack_name, "success", str(result),
            request.client.host if request.client else None,
        )

        if payload.is_add:
            snapshot_manager.schedule_host_structure_refresh(host_id)

        return StackOperationResponse(
            success=True,
            message=f"Stack '{stack_name}' compose saved",
            detail=str(result),
        )
    except Exception as exc:
        logger.warning("Failed to save compose for %s/%s: %s", host_id, stack_name, exc)
        _write_audit_log(
            session, username, "stack.compose.save",
            host_id, stack_name, "error", str(exc)[:500],
            request.client.host if request.client else None,
        )
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=_safe_error_detail(exc))
    finally:
        await conn.close()


@router.put(
    "/hosts/{host_id}/stacks/{stack_name}/compose",
    response_model=StackOperationResponse,
)
async def save_stack_compose(
    host_id: str,
    stack_name: str,
    payload: StackComposeSaveRequest,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Save compose.yaml/.env without deploying (fast, synchronous response)."""
    return await _save_stack_compose(
        host_id, stack_name, payload, request, session, username,
    )


@router.post(
    "/hosts/{host_id}/stacks/{stack_name}/compose/deploy",
)
async def deploy_stack_compose(
    host_id: str,
    stack_name: str,
    payload: StackComposeSaveRequest,
    request: Request,
    cols: int = 160,
    rows: int = 24,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Save compose.yaml/.env and deploy the stack with real-time streaming.

    Returns a ``text/event-stream`` SSE response.  Events:
      - ``event: line\ndata: <log line>``
      - ``event: complete\ndata: {"status":"success|error","message":"..."}``
      - ``event: error\ndata: {"message":"..."}``
    """
    if not payload.compose_yaml.strip():
        raise HTTPException(status_code=400, detail="compose_yaml cannot be empty")

    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        _write_audit_log(
            session, username, "stack.compose.deploy",
            host_id, stack_name, "error",
            f"Host '{host_id}' not found",
            request.client.host if request.client else None,
        )
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    ip = request.client.host if request.client else None
    _write_audit_log(
        session, username, "stack.compose.deploy",
        host_id, stack_name, "running", "Deploy started", ip,
    )

    return StreamingResponse(
        stream_compose_deploy(
            snap.host_config, host_id, stack_name, snap, payload, cols, rows, username, ip,
            agent_client=AgentClient,
            snapshot_manager=snapshot_manager,
            audit_log=_write_audit_log_standalone,
        ),
        media_type="text/event-stream",
    )


@router.delete(
    "/hosts/{host_id}/stacks/{stack_name}",
    response_model=StackOperationResponse,
)
async def delete_stack(
    host_id: str,
    stack_name: str,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Delete a stack directory permanently.

    This removes the compose file, .env, and any other contents of the
    stack directory via the Agent API.
    """
    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    ip = request.client.host if request.client else None
    _write_audit_log(
        session, username, "stack.delete",
        host_id, stack_name, "running", "Delete started", ip,
    )

    if not snap.host_config.agent_url:
        raise HTTPException(status_code=400, detail="Host has no agent_url configured")

    conn = AgentClient(snap.host_config)
    try:
        result = await conn.delete_stack(stack_name)

        _write_audit_log(
            session, username, "stack.delete",
            host_id, stack_name, "success", str(result), ip,
        )

        asyncio.create_task(
            snapshot_manager.refresh_host_docker_with_retry(host_id)
        )

        return StackOperationResponse(
            success=True,
            message=f"Stack '{stack_name}' deleted successfully.",
            detail=str(result),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Delete stack failed for %s/%s: %s", host_id, stack_name, exc)
        _write_audit_log(
            session, username, "stack.delete",
            host_id, stack_name, "error", str(exc)[:500], ip,
        )
        raise HTTPException(status_code=502, detail=_safe_error_detail(exc))
    finally:
        await conn.close()


@router.post("/hosts/{host_id}/prune")
async def prune_docker_system(
    host_id: str,
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Run ``docker system prune -a -f`` on the host and stream output.

    Only supported for hosts that have an Agent configured.
    Returns a ``text/event-stream`` SSE response.
    """
    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    if not snap.host_config.agent_url:
        raise HTTPException(
            status_code=400,
            detail="Docker system prune is only supported for hosts with a Fleetge Agent.",
        )

    ip = request.client.host if request.client else None
    _write_audit_log(
        session, username, "docker.prune",
        host_id, None, "running", "Prune started", ip,
    )

    return StreamingResponse(
        stream_system_prune(
            snap.host_config, host_id, username, ip,
            agent_client=AgentClient,
            snapshot_manager=snapshot_manager,
            audit_log=_write_audit_log_standalone,
        ),
        media_type="text/event-stream",
    )


@router.get("/hosts/{host_id}/stacks/{stack_name}/logs")
async def get_stack_logs(
    host_id: str,
    stack_name: str,
    tail: int = 200,
):
    """Fetch logs for all containers belonging to a stack.

    Uses the Agent API for each container associated with the stack,
    then aggregates them in reverse-chronological order.

    Args:
        tail: Number of recent lines per container (default 200, max 5000).
    """
    if tail < 1:
        tail = 200
    if tail > 5000:
        tail = 5000

    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    # Find containers belonging to this stack
    stack_containers = [
        c
        for c in snap.containers
        if c.stack_name == stack_name and c.state == "running"
    ]
    if not stack_containers:
        return {"logs": "", "host_id": host_id, "stack": stack_name}

    if not snap.host_config.agent_url:
        raise HTTPException(status_code=400, detail="Host has no agent_url configured")

    # Create a proxy client for this host and fetch logs per container
    proxy = AgentClient(snap.host_config)
    try:
        logs_parts: list[str] = []
        for c in stack_containers:
            service_label = c.service_name or c.name
            container_logs = await proxy.container_logs(c.id, tail=tail)
            if container_logs:
                logs_parts.append(
                    f"===== {service_label} ({c.id}) =====\n{container_logs}"
                )

        return {
            "logs": "\n\n".join(logs_parts),
            "host_id": host_id,
            "stack": stack_name,
        }
    finally:
        await proxy.close()


@router.get("/hosts/{host_id}/stacks/{stack_name}/logs/stream")
async def stream_stack_logs(
    host_id: str,
    stack_name: str,
    tail: int = 200,
):
    """Stream live logs for a stack.

    Prefer the agent's compose-level log stream (`docker compose logs -f`) so
    the UI follows the compose project through container recreation, matching
    Dockge's combined terminal behavior. Container-ID streaming is kept only as
    a compatibility fallback for older agents.
    """
    if tail < 1:
        tail = 200
    if tail > 5000:
        tail = 5000

    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    return StreamingResponse(
        stream_compose_logs(
            snap.host_config, host_id, stack_name, snap.containers, tail,
            agent_client=AgentClient,
        ),
        media_type="text/event-stream",
    )


@router.post(
    "/hosts/{host_id}/stacks/{stack_name}/services/{service_name}/{action}",
)
async def stack_service_action(
    host_id: str,
    stack_name: str,
    service_name: str,
    action: str,
    request: Request,
    cols: int = 160,
    rows: int = 24,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Execute a Docker Compose service-level operation with streaming output."""
    if action not in SERVICE_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown service action '{action}'. Allowed: {', '.join(SERVICE_ACTIONS.keys())}",
        )

    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        _write_audit_log(
            session, username, f"stack.service.{action}", host_id, stack_name,
            "error", f"Host '{host_id}' not found",
            request.client.host if request.client else None,
        )
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    socket_event = SERVICE_ACTIONS[action]
    ip = request.client.host if request.client else None

    _write_audit_log(
        session, username, f"stack.service.{action}", host_id, stack_name,
        "running", f"Service operation started: {service_name}", ip,
    )

    return StreamingResponse(
        stream_service_action(
            snap.host_config, host_id, stack_name, service_name, socket_event, action,
            cols, rows, username, ip,
            agent_client=AgentClient,
            snapshot_manager=snapshot_manager,
            audit_log=_write_audit_log_standalone,
        ),
        media_type="text/event-stream",
    )


@router.get("/hosts/{host_id}/stacks/{stack_name}/update-runs/{request_id}/stream")
async def stream_existing_update_run(host_id: str, stack_name: str, request_id: str, after: int = 0):
    batch = auto_update_manager.get_batch(host_id, request_id)
    if not batch or not any(item["stack_name"] == stack_name for item in batch["items"]):
        raise HTTPException(404, "Update run not found")
    return StreamingResponse(
        _stream_update_run(host_id, request_id, stack_name, after=max(0, after)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _stream_update_run(
    host_id: str, request_id: str, stack_name: str, after: int = 0,
) -> AsyncGenerator[str, None]:
    return stream_update_run(auto_update_manager, host_id, request_id, stack_name, after=after)


@router.post(
    "/hosts/{host_id}/stacks/{stack_name}/{action}",
)
async def stack_action(
    host_id: str,
    stack_name: str,
    action: str,
    request: Request,
    cols: int = 160,
    rows: int = 24,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Execute a stack operation with real-time streaming output.

    Returns a ``text/event-stream`` SSE response.  Events:
      - ``event: line\ndata: <log line>`` — one per terminal output line
      - ``event: complete\ndata: {"status":"success|error","message":"..."}``
      - ``event: error\ndata: {"message":"..."}`` — fatal error before the
        operation could start

    Only whitelisted actions are accepted.
    """
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{action}'. Allowed: {', '.join(ALLOWED_ACTIONS.keys())}",
        )

    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        _write_audit_log(
            session, username, f"stack.{action}", host_id, stack_name,
            "error", f"Host '{host_id}' not found",
            request.client.host if request.client else None,
        )
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    if action == "update":
        request_id = str(uuid.uuid4())
        try:
            await auto_update_manager.submit(host_id, request_id, "manual", [stack_name], username)
        except UpdateRunError as exc:
            detail = {"message": exc.detail}
            if exc.existing_id is not None:
                detail["existing_run_id"] = exc.existing_id
            raise HTTPException(exc.status_code, detail=detail) from exc
        return StreamingResponse(
            _stream_update_run(host_id, request_id, stack_name),
            media_type="text/event-stream",
        )

    socket_event = ALLOWED_ACTIONS[action]
    ip = request.client.host if request.client else None

    _write_audit_log(
        session, username, f"stack.{action}", host_id, stack_name,
        "running", "Operation started", ip,
    )

    return StreamingResponse(
        stream_stack_action(
            snap.host_config, host_id, stack_name, socket_event, action, cols, rows, username, ip,
            agent_client=AgentClient,
            snapshot_manager=snapshot_manager,
            audit_log=_write_audit_log_standalone,
        ),
        media_type="text/event-stream",
    )
