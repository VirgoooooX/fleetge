"""Stack router — list, start, stop, restart, update, logs."""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.auth.handler import get_current_user
from app.database import get_session, engine
from app.models import AuditLog
from app.schemas import (
    StackComposeDetail,
    StackComposeSaveRequest,
    StackOperationResponse,
    StackSummary,
)
from app.services.crypto import decrypt_credentials
from app.services.dockge_client import dockge_pool, DockgeClientError
from app.services.snapshot import snapshot_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["stacks"],
    dependencies=[Depends(get_current_user)],
)

# Whitelisted actions — these map to Dockge Socket.IO events
ALLOWED_ACTIONS: dict[str, str] = {
    "start": "startStack",
    "stop": "stopStack",
    "restart": "restartStack",
    "update": "updateStack",
}


def _sse_event(event: str, data: dict) -> str:
    """Format an SSE event frame with JSON-encoded data.

    JSON encoding ensures the payload does not contain ``\\n`` or ``\\n\\n``
    sequences that would corrupt the SSE protocol framing.
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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
    log = AuditLog(
        user=user,
        action=action,
        host_id=host_id,
        stack_name=stack_name,
        result=result,
        detail=detail,
        ip_address=ip_address,
    )
    session.add(log)
    session.commit()


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
        log = AuditLog(
            user=user,
            action=action,
            host_id=host_id,
            stack_name=stack_name,
            result=result,
            detail=detail,
            ip_address=ip_address,
        )
        session.add(log)
        session.commit()


@router.get("/hosts/{host_id}/stacks", response_model=list[StackSummary])
async def list_stacks(host_id: str):
    """Return all Dockge stacks for a host, merged with container states."""
    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")
    return snap.stacks


def _normalize_stack_detail(stack_name: str, result: Any) -> StackComposeDetail:
    """Normalize Dockge getStack ack into API shape.

    The error-first callback [err, data] pattern is already unwrapped
    by ``_agent_call()``, so ``result`` is the data dict directly (or
    a dict with a ``stack`` key).
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
        is_managed_by_dockge=bool(stack.get("isManagedByDockge")),
    )


@router.get(
    "/hosts/{host_id}/stacks/{stack_name}/compose",
    response_model=StackComposeDetail,
)
async def get_stack_compose(host_id: str, stack_name: str):
    """Return compose.yaml and .env for a stack.

    Unlike earlier versions, this endpoint does NOT return 409 purely based on
    ``isManagedByDockge``. If Dockge's ``getStack`` succeeds and returns
    compose content, the result is returned regardless of the managed flag.
    A 409/404 is only returned when Dockge did not return a compose file.
    """
    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    try:
        creds = decrypt_credentials(snap.host_config.dockge_password_encrypted)
        conn = await dockge_pool.get_or_create(snap.host_config, creds["password"])
        result = await conn.get_stack(stack_name)
        detail = _normalize_stack_detail(stack_name, result or {})
        if not detail.compose_yaml.strip():
            raise HTTPException(
                status_code=409,
                detail="Dockge did not return a compose file for this stack.",
            )
        return detail
    except HTTPException:
        raise
    except DockgeClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


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

    try:
        creds = decrypt_credentials(snap.host_config.dockge_password_encrypted)
        conn = await dockge_pool.get_or_create(snap.host_config, creds["password"])
        result = await conn.save_stack(
            stack_name,
            payload.compose_yaml,
            payload.compose_env,
            deploy=False,
            is_add=payload.is_add,
        )

        _write_audit_log(
            session, username, "stack.compose.save",
            host_id, stack_name, "success", str(result),
            request.client.host if request.client else None,
        )

        if payload.is_add:
            asyncio.create_task(snapshot_manager.refresh_host_docker_with_retry(host_id))

        return StackOperationResponse(
            success=True,
            message=f"Stack '{stack_name}' compose saved",
            detail=str(result),
        )
    except DockgeClientError as exc:
        _write_audit_log(
            session, username, "stack.compose.save",
            host_id, stack_name, "error", str(exc),
            request.client.host if request.client else None,
        )
        raise HTTPException(status_code=502, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        _write_audit_log(
            session, username, "stack.compose.save",
            host_id, stack_name, "error", f"Unexpected: {exc}",
            request.client.host if request.client else None,
        )
        raise HTTPException(status_code=500, detail=f"保存异常: {exc}")


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

    async def _stream() -> AsyncGenerator[str, None]:
        log_queue: asyncio.Queue = asyncio.Queue()
        task: Optional[asyncio.Task] = None
        try:
            creds = decrypt_credentials(snap.host_config.dockge_password_encrypted)
            conn = await dockge_pool.get_or_create(snap.host_config, creds["password"])
            task = asyncio.create_task(
                conn.save_stack(
                    stack_name, payload.compose_yaml, payload.compose_env,
                    deploy=True,
                    is_add=payload.is_add,
                    log_queue=log_queue,
                )
            )

            while True:
                line = await log_queue.get()
                if line is None:
                    break
                yield _sse_event("line", {"text": line})

            result = await task
            task = None

            success = True
            msg = str(result)
            if isinstance(result, dict):
                ok_val = result.get("success", result.get("ok", True))
                success = bool(ok_val) if ok_val is not None else True
                msg = result.get("msg", result.get("message", str(result)))

            yield _sse_event(
                "complete",
                {"status": "success" if success else "error", "message": msg},
            )

            asyncio.create_task(snapshot_manager.refresh_host_docker_with_retry(host_id))
            _write_audit_log_standalone(
                username, "stack.compose.deploy", host_id, stack_name,
                "success" if success else "error", msg, ip,
            )

        except DockgeClientError as exc:
            if task and not task.done():
                task.cancel()
            yield _sse_event("error", {"message": str(exc)})
            _write_audit_log_standalone(
                username, "stack.compose.deploy", host_id, stack_name,
                "error", str(exc), ip,
            )
        except Exception as exc:
            if task and not task.done():
                task.cancel()
            logger.exception("Deploy stream failed for %s/%s", host_id, stack_name)
            yield _sse_event("error", {"message": f"Unexpected error: {exc}"})
            _write_audit_log_standalone(
                username, "stack.compose.deploy", host_id, stack_name,
                "error", f"Unexpected: {exc}", ip,
            )
        finally:
            # Ensure background task is cleaned up even if client disconnects
            if task is not None and not task.done():
                task.cancel()

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/hosts/{host_id}/stacks/{stack_name}/logs")
async def get_stack_logs(
    host_id: str,
    stack_name: str,
    tail: int = 200,
):
    """Fetch logs for all containers belonging to a stack.

    Uses docker-socket-proxy ``/containers/{id}/logs`` for each container
    associated with the stack, then aggregates them in reverse-chronological
    order.

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

    # Create a proxy client for this host and fetch logs per container
    from app.services.docker_proxy import DockerProxyClient

    proxy = DockerProxyClient(snap.host_config)
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
    """Stream live logs for all running containers in a stack."""
    if tail < 1:
        tail = 200
    if tail > 5000:
        tail = 5000

    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None or snap.host_config is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    stack_containers = [
        c
        for c in snap.containers
        if c.stack_name == stack_name and c.state == "running"
    ]

    async def _stream() -> AsyncGenerator[str, None]:
        if not stack_containers:
            yield _sse_event(
                "complete",
                {"message": "No running containers found for this stack."},
            )
            return

        from app.services.docker_proxy import DockerProxyClient

        proxy = DockerProxyClient(snap.host_config)
        queue: asyncio.Queue = asyncio.Queue()
        tasks: list[asyncio.Task] = []
        done_task: Optional[asyncio.Task] = None

        async def stream_one(container) -> None:
            service_label = container.service_name or container.name
            buffer = ""
            try:
                async for chunk in proxy.stream_container_logs(container.id, tail=tail):
                    buffer += chunk.replace("\x00", "")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        await queue.put(
                            (
                                "line",
                                {
                                    "text": line.rstrip("\r"),
                                    "container": container.id,
                                    "service": service_label,
                                },
                            )
                        )
                if buffer:
                    await queue.put(
                        (
                            "line",
                            {
                                "text": buffer.rstrip("\r"),
                                "container": container.id,
                                "service": service_label,
                            },
                        )
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await queue.put(
                    (
                        "error",
                        {
                            "message": str(exc),
                            "container": container.id,
                            "service": service_label,
                        },
                    )
                )

        async def wait_for_tasks() -> None:
            await asyncio.gather(*tasks, return_exceptions=True)
            await queue.put(None)

        try:
            yield _sse_event(
                "ready",
                {
                    "message": "Log stream connected.",
                    "containers": len(stack_containers),
                },
            )
            tasks = [
                asyncio.create_task(stream_one(container))
                for container in stack_containers
            ]
            done_task = asyncio.create_task(wait_for_tasks())

            while True:
                item = await queue.get()
                if item is None:
                    break
                event, payload = item
                yield _sse_event(event, payload)
        except asyncio.CancelledError:
            raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if done_task and not done_task.done():
                done_task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if done_task:
                await asyncio.gather(done_task, return_exceptions=True)
            await proxy.close()

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post(
    "/hosts/{host_id}/stacks/{stack_name}/{action}",
)
async def stack_action(
    host_id: str,
    stack_name: str,
    action: str,
    request: Request,
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

    socket_event = ALLOWED_ACTIONS[action]
    ip = request.client.host if request.client else None

    _write_audit_log(
        session, username, f"stack.{action}", host_id, stack_name,
        "running", "Operation started", ip,
    )

    async def _stream() -> AsyncGenerator[str, None]:
        log_queue: asyncio.Queue = asyncio.Queue()
        task: Optional[asyncio.Task] = None
        try:
            creds = decrypt_credentials(snap.host_config.dockge_password_encrypted)
            conn = await dockge_pool.get_or_create(snap.host_config, creds["password"])
            task = asyncio.create_task(
                conn.stack_action(stack_name, socket_event, log_queue=log_queue)
            )

            while True:
                line = await log_queue.get()
                if line is None:  # EOF sentinel from _run_with_terminal
                    break
                yield _sse_event("line", {"text": line})

            result = await task
            task = None

            success = True
            msg = str(result)
            if isinstance(result, dict):
                ok_val = result.get("success", result.get("ok", True))
                success = bool(ok_val) if ok_val is not None else True
                msg = result.get("msg", result.get("message", str(result)))

            yield _sse_event(
                "complete",
                {"status": "success" if success else "error", "message": msg},
            )

            asyncio.create_task(
                snapshot_manager.refresh_host_docker_with_retry(host_id)
            )
            _write_audit_log_standalone(
                username, f"stack.{action}", host_id, stack_name,
                "success" if success else "error", msg, ip,
            )

        except DockgeClientError as exc:
            if task and not task.done():
                task.cancel()
            yield _sse_event("error", {"message": str(exc)})
            _write_audit_log_standalone(
                username, f"stack.{action}", host_id, stack_name,
                "error", str(exc), ip,
            )
        except Exception as exc:
            if task and not task.done():
                task.cancel()
            logger.exception("Stack action stream failed for %s/%s", host_id, stack_name)
            yield _sse_event("error", {"message": f"Unexpected error: {exc}"})
            _write_audit_log_standalone(
                username, f"stack.{action}", host_id, stack_name,
                "error", f"Unexpected: {exc}", ip,
            )
        finally:
            if task is not None and not task.done():
                task.cancel()

    return StreamingResponse(_stream(), media_type="text/event-stream")
