"""Stack router — list, start, stop, restart, update, logs."""

import asyncio
import json
import logging
import re
import shlex
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.auth.handler import get_current_user
from app.database import get_session, engine
from app.models import AuditLog
from app.schemas import (
    ContainerSummary,
    StackComposeDetail,
    StackComposeSaveRequest,
    StackOperationResponse,
    StackSummary,
    UpdateCheckResult,
)
from app.services.agent_client import AgentClient
from app.services.snapshot import snapshot_manager
from app.services.update_check import FAILURE_STATUSES, run_update_check

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

_ANSI_RE = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _sse_event(event: str, data: dict) -> str:
    """Format an SSE event frame with JSON-encoded data.

    JSON encoding ensures the payload does not contain ``\\n`` or ``\\n\\n``
    sequences that would corrupt the SSE protocol framing.
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _clean_log_text(text: str) -> str:
    """Remove terminal color/control sequences before sending logs to the UI."""
    text = _ANSI_RE.sub("", text)
    return _CONTROL_RE.sub("", text)


def _convert_docker_run_to_compose(command: str) -> str:
    """Small v1 docker-run-to-compose converter for common flags."""
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid docker run command: {exc}")

    if len(tokens) >= 2 and tokens[0] == "docker" and tokens[1] == "run":
        tokens = tokens[2:]
    elif tokens and tokens[0] == "run":
        tokens = tokens[1:]
    else:
        raise HTTPException(status_code=400, detail="Command must start with 'docker run' or 'run'")

    service: dict[str, Any] = {}
    ports: list[str] = []
    volumes: list[str] = []
    env: list[str] = []
    image = ""
    cmd: list[str] = []

    flag_value = {
        "--name", "--restart", "--network", "--hostname", "--user", "--workdir",
        "-p", "--publish", "-v", "--volume", "-e", "--env",
    }
    bool_flags = {"-d", "--detach", "--rm", "--privileged"}

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if image:
            cmd.append(token)
            i += 1
            continue

        key = token
        value: str | None = None
        if token.startswith("--") and "=" in token:
            key, value = token.split("=", 1)
        elif token in flag_value:
            i += 1
            if i >= len(tokens):
                raise HTTPException(status_code=400, detail=f"Missing value for {token}")
            value = tokens[i]

        if key in ("--name",):
            service["container_name"] = value
        elif key in ("--restart",):
            service["restart"] = value
        elif key in ("--network",):
            service["network_mode"] = value
        elif key in ("--hostname",):
            service["hostname"] = value
        elif key in ("--user",):
            service["user"] = value
        elif key in ("--workdir",):
            service["working_dir"] = value
        elif key in ("-p", "--publish"):
            ports.append(value or "")
        elif key in ("-v", "--volume"):
            volumes.append(value or "")
        elif key in ("-e", "--env"):
            env.append(value or "")
        elif key in bool_flags:
            if key == "--privileged":
                service["privileged"] = True
            # -d and --rm do not map cleanly for persistent compose stacks.
        elif token.startswith("-"):
            raise HTTPException(status_code=400, detail=f"Unsupported docker run flag: {token}")
        else:
            image = token
        i += 1

    if not image:
        raise HTTPException(status_code=400, detail="Docker image is required")

    service["image"] = image
    if ports:
        service["ports"] = ports
    if volumes:
        service["volumes"] = volumes
    if env:
        service["environment"] = env
    if cmd:
        service["command"] = cmd

    service_name = service.get("container_name") or image.split("/")[-1].split(":")[0] or "app"
    service_name = "".join(ch if ch.isalnum() or ch in "_-" else "-" for ch in service_name.lower()).strip("-") or "app"

    try:
        import yaml
        return yaml.safe_dump(
            {"services": {service_name: service}},
            sort_keys=False,
            allow_unicode=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to render compose YAML: {exc}")


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
    """Return all stacks for a host, merged with container states."""
    snap = snapshot_manager.get_snapshot(host_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")
    return snap.stacks


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
        raise HTTPException(status_code=502, detail=str(exc))
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
            asyncio.create_task(snapshot_manager.refresh_host_docker_with_retry(host_id))

        return StackOperationResponse(
            success=True,
            message=f"Stack '{stack_name}' compose saved",
            detail=str(result),
        )
    except Exception as exc:
        _write_audit_log(
            session, username, "stack.compose.save",
            host_id, stack_name, "error", str(exc),
            request.client.host if request.client else None,
        )
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=str(exc))
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

    async def _stream() -> AsyncGenerator[str, None]:
        log_queue: asyncio.Queue = asyncio.Queue()
        task: Optional[asyncio.Task] = None
        if not snap.host_config.agent_url:
            yield _sse_event("error", {"message": "Host has no agent_url configured"})
            return

        conn = AgentClient(snap.host_config)
        try:
            task = asyncio.create_task(
                conn.save_stack(
                    stack_name, payload.compose_yaml, payload.compose_env,
                    compose_file_name=payload.compose_file_name,
                    deploy=True,
                    is_add=payload.is_add,
                    log_queue=log_queue,
                    cols=cols,
                    rows=rows,
                )
            )

            while True:
                chunk = await log_queue.get()
                if chunk is None:
                    break
                yield _sse_event("chunk", {"raw": chunk})

            result = await task
            task = None

            success = True
            msg = str(result)
            if isinstance(result, dict):
                ok_val = result.get("success", result.get("ok", True))
                success = bool(ok_val) if ok_val is not None else True
                msg = result.get("msg", result.get("message", str(result)))

            if success:
                try:
                    await snapshot_manager.refresh_host_docker(host_id)
                except Exception as refresh_exc:
                    logger.warning("Pre-complete refresh failed for deploy: %s", refresh_exc)

            yield _sse_event(
                "complete",
                {"status": "success" if success else "error", "message": msg},
            )

            asyncio.create_task(snapshot_manager.refresh_host_docker_with_retry(host_id))
            _write_audit_log_standalone(
                username, "stack.compose.deploy", host_id, stack_name,
                "success" if success else "error", msg, ip,
            )

        except HTTPException:
            raise
        except Exception as exc:
            if task and not task.done():
                task.cancel()
            yield _sse_event("error", {"message": str(exc)})
            _write_audit_log_standalone(
                username, "stack.compose.deploy", host_id, stack_name,
                "error", str(exc), ip,
            )
        finally:
            # Ensure background task is cleaned up even if client disconnects
            if task is not None and not task.done():
                task.cancel()
            if conn is not None:
                await conn.close()

    return StreamingResponse(_stream(), media_type="text/event-stream")


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
        _write_audit_log(
            session, username, "stack.delete",
            host_id, stack_name, "error", str(exc), ip,
        )
        raise HTTPException(status_code=502, detail=str(exc))
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

    async def _stream() -> AsyncGenerator[str, None]:
        log_queue: asyncio.Queue = asyncio.Queue()
        task: Optional[asyncio.Task] = None
        conn: Optional[AgentClient] = None
        try:
            conn = AgentClient(snap.host_config)
            task = asyncio.create_task(
                conn.prune_system(log_queue=log_queue)
            )

            while True:
                chunk = await log_queue.get()
                if chunk is None:
                    break
                yield _sse_event("chunk", {"raw": chunk})

            result = await task
            task = None

            success = True
            msg = str(result)
            if isinstance(result, dict):
                ok_val = result.get("success", True)
                success = bool(ok_val) if ok_val is not None else True
                msg = result.get("message", str(result))

            yield _sse_event(
                "complete",
                {"status": "success" if success else "error", "message": msg},
            )

            asyncio.create_task(snapshot_manager.refresh_all_structure_now())
            _write_audit_log_standalone(
                username, "docker.prune", host_id, None,
                "success" if success else "error", msg, ip,
            )

        except HTTPException:
            raise
        except Exception as exc:
            if task and not task.done():
                task.cancel()
            yield _sse_event("error", {"message": str(exc)})
            _write_audit_log_standalone(
                username, "docker.prune", host_id, None,
                "error", str(exc), ip,
            )
        finally:
            if task is not None and not task.done():
                task.cancel()
            if conn is not None:
                await conn.close()

    return StreamingResponse(_stream(), media_type="text/event-stream")


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

    def parse_compose_log_line(line: str) -> dict:
        clean = _clean_log_text(line).rstrip("\r")
        if " | " in clean:
            service, text = clean.split(" | ", 1)
            return {"text": text, "service": service.strip()}
        return {"text": clean, "service": ""}

    async def _stream() -> AsyncGenerator[str, None]:
        if not snap.host_config.agent_url:
            yield _sse_event(
                "complete",
                {"message": "Host has no agent_url configured"},
            )
            return

        proxy = AgentClient(snap.host_config)
        stack_containers = [
            c
            for c in snap.containers
            if c.stack_name == stack_name and c.state == "running"
        ]

        async def stream_container_fallback(container, queue: asyncio.Queue) -> None:
            service_label = container.service_name or container.name
            buffer = ""
            try:
                async for chunk in proxy.stream_container_logs(container.id, tail=tail):
                    buffer += _clean_log_text(chunk)
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
                    "mode": "compose",
                },
            )

            buffer = ""
            try:
                async for chunk in proxy.stream_stack_compose_logs(stack_name, tail=tail):
                    buffer += _clean_log_text(chunk)
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        yield _sse_event("line", parse_compose_log_line(line))
                if buffer:
                    yield _sse_event("line", parse_compose_log_line(buffer))
                yield _sse_event("complete", {"message": "Log stream ended."})
                return
            except Exception as exc:
                logger.debug(
                    "Compose log stream unavailable for %s/%s, falling back to container logs: %s",
                    host_id,
                    stack_name,
                    exc,
                )

            if not stack_containers:
                yield _sse_event(
                    "complete",
                    {"message": "No running containers found for this stack."},
                )
                return

            queue: asyncio.Queue = asyncio.Queue()
            tasks: list[asyncio.Task] = []
            done_task: Optional[asyncio.Task] = None

            tasks = [
                asyncio.create_task(stream_container_fallback(container, queue))
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
            if "tasks" in locals():
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            if "done_task" in locals() and done_task:
                if not done_task.done():
                    done_task.cancel()
                await asyncio.gather(done_task, return_exceptions=True)
            await proxy.close()

    return StreamingResponse(_stream(), media_type="text/event-stream")


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

    async def _stream() -> AsyncGenerator[str, None]:
        log_queue: asyncio.Queue = asyncio.Queue()
        task: Optional[asyncio.Task] = None
        if not snap.host_config.agent_url:
            yield _sse_event("error", {"message": "Host has no agent_url configured"})
            return

        conn = AgentClient(snap.host_config)
        try:
            task = asyncio.create_task(
                conn.stack_action(
                    stack_name,
                    socket_event,
                    log_queue=log_queue,
                    cols=cols,
                    rows=rows,
                    service=service_name,
                )
            )

            while True:
                chunk = await log_queue.get()
                if chunk is None:
                    break
                yield _sse_event("chunk", {"raw": chunk})

            result = await task
            task = None

            success = True
            msg = str(result)
            if isinstance(result, dict):
                ok_val = result.get("success", result.get("ok", True))
                success = bool(ok_val) if ok_val is not None else True
                msg = result.get("msg", result.get("message", str(result)))

            if success:
                try:
                    await snapshot_manager.refresh_host_docker(host_id)
                except Exception as refresh_exc:
                    logger.warning("Pre-complete refresh failed for service action: %s", refresh_exc)

            yield _sse_event(
                "complete",
                {"status": "success" if success else "error", "message": msg},
            )

            asyncio.create_task(snapshot_manager.refresh_host_docker_with_retry(host_id))
            _write_audit_log_standalone(
                username, f"stack.service.{action}", host_id, stack_name,
                "success" if success else "error", f"{service_name}: {msg}", ip,
            )

        except Exception as exc:
            if task and not task.done():
                task.cancel()
            yield _sse_event("error", {"message": str(exc)})
            _write_audit_log_standalone(
                username, f"stack.service.{action}", host_id, stack_name,
                "error", f"{service_name}: {exc}", ip,
            )
        finally:
            if task is not None and not task.done():
                task.cancel()
            await conn.close()

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _containers_by_service(snap: Any, stack_name: str) -> dict[str, ContainerSummary]:
    services: dict[str, ContainerSummary] = {}
    for container in snap.containers:
        if container.stack_name != stack_name or not container.service_name or not container.image:
            continue
        services.setdefault(container.service_name, container)
    return services


async def _fresh_check_fleetge_services(
    host_id: str,
    stack_name: str,
    snap: Any,
) -> tuple[dict[str, ContainerSummary], dict[str, UpdateCheckResult]]:
    service_containers = _containers_by_service(snap, stack_name)
    if not service_containers:
        raise HTTPException(
            status_code=409,
            detail="Cannot plan Fleetge update: no running compose service containers were found for this stack.",
        )

    image_refs = [
        (container.image, container.repo_digests)
        for container in service_containers.values()
    ]
    results = await run_update_check(host_id, image_refs, force=True)
    by_image = {result.image: result for result in results}
    return service_containers, by_image


async def _poll_agent_job_events(
    conn: AgentClient,
    job_id: str,
    timeout_seconds: float = 600.0,
) -> AsyncGenerator[str, None]:
    started = asyncio.get_running_loop().time()
    last_size = 0
    reconnect_notice_sent = False

    while True:
        if asyncio.get_running_loop().time() - started > timeout_seconds:
            yield _sse_event("complete", {
                "status": "error",
                "message": f"Fleetge update job {job_id} timed out.",
            })
            return

        try:
            logs = await conn.get_job_logs(job_id)
            content = logs.get("content", "")
            if len(content) > last_size:
                yield _sse_event("chunk", {"raw": content[last_size:]})
                last_size = len(content)

            job = await conn.get_job(job_id)
            status = job.get("status")
            if status in ("success", "error"):
                message = (
                    "Fleetge update completed successfully."
                    if status == "success"
                    else job.get("message") or f"Fleetge update job {job_id} failed."
                )
                yield _sse_event("complete", {
                    "status": "success" if status == "success" else "error",
                    "message": message,
                })
                return

            reconnect_notice_sent = False
        except Exception:
            if not reconnect_notice_sent:
                yield _sse_event("chunk", {"raw": "Waiting for Fleetge Agent to reconnect...\n"})
                reconnect_notice_sent = True

        await asyncio.sleep(2.0)


async def _stream_fleetge_update(
    host_id: str,
    stack_name: str,
    conn: AgentClient,
    self_info: dict,
    cols: int,
    rows: int,
) -> AsyncGenerator[str, None]:
    agent_service = self_info.get("service_name")
    if not agent_service:
        yield _sse_event("error", {"message": "Cannot plan Fleetge update: agent service name is unknown."})
        return

    yield _sse_event("chunk", {"raw": "Detected Fleetge control stack. Running fresh image check...\n"})
    await snapshot_manager.refresh_host_docker(host_id, trigger_initial_update_check=False)
    refreshed = snapshot_manager.get_snapshot(host_id)
    if refreshed is None:
        yield _sse_event("error", {"message": f"Host '{host_id}' not found after refresh."})
        return

    try:
        service_containers, results_by_image = await _fresh_check_fleetge_services(host_id, stack_name, refreshed)
    except HTTPException as exc:
        yield _sse_event("error", {"message": exc.detail})
        return
    except Exception as exc:
        yield _sse_event("error", {"message": f"Fresh image check failed: {exc}"})
        return

    failures: dict[str, str] = {}
    updatable_services: list[str] = []
    for service_name, container in service_containers.items():
        result = results_by_image.get(container.image)
        if result is None:
            failures[service_name] = "check_failed"
            continue
        yield _sse_event("chunk", {"raw": f"{service_name}: {container.image} -> {result.status}\n"})
        if result.status in FAILURE_STATUSES:
            failures[service_name] = result.status
        elif result.status == "updatable":
            updatable_services.append(service_name)

    if failures:
        detail = ", ".join(f"{svc}={status}" for svc, status in sorted(failures.items()))
        yield _sse_event("complete", {
            "status": "error",
            "message": f"Fleetge update requires a fresh image check, but some services could not be checked: {detail}",
        })
        return

    if not updatable_services:
        yield _sse_event("complete", {
            "status": "success",
            "message": "Fresh image check completed. Fleetge images are already up to date.",
        })
        return

    if agent_service in updatable_services:
        agent_action = "selfUpdate"
        yield _sse_event("chunk", {
            "raw": f"Agent service '{agent_service}' needs update. Handing off to temporary self-updater...\n"
        })
    else:
        agent_action = "updateServicesJob"
        yield _sse_event("chunk", {
            "raw": f"Updating Fleetge app services without touching agent: {', '.join(updatable_services)}\n"
        })

    log_queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(
        conn.stack_action(
            stack_name,
            agent_action,
            log_queue=log_queue,
            cols=cols,
            rows=rows,
            services=updatable_services,
        )
    )

    while True:
        chunk = await log_queue.get()
        if chunk is None:
            break
        yield _sse_event("chunk", {"raw": chunk})

    result = await task
    if not result.get("success", result.get("ok", True)):
        yield _sse_event("complete", {
            "status": "error",
            "message": result.get("message", "Failed to start Fleetge update job."),
        })
        return

    job_id = result.get("job_id")
    if not job_id:
        yield _sse_event("complete", {
            "status": "success",
            "message": result.get("message", "Fleetge update completed."),
        })
        return

    yield _sse_event("chunk", {"raw": f"Tracking Fleetge update job {job_id}...\n"})
    async for event in _poll_agent_job_events(conn, job_id):
        yield event


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

    socket_event = ALLOWED_ACTIONS[action]
    ip = request.client.host if request.client else None

    _write_audit_log(
        session, username, f"stack.{action}", host_id, stack_name,
        "running", "Operation started", ip,
    )

    async def _stream() -> AsyncGenerator[str, None]:
        log_queue: asyncio.Queue = asyncio.Queue()
        task: Optional[asyncio.Task] = None
        if not snap.host_config.agent_url:
            yield _sse_event("error", {"message": "Host has no agent_url configured"})
            return

        conn = AgentClient(snap.host_config)
        try:
            if action == "update":
                try:
                    self_info = await conn.get_self()
                except Exception as exc:
                    logger.debug("Agent self identity unavailable for %s/%s: %s", host_id, stack_name, exc)
                    self_info = {}

                if self_info.get("stack_name") == stack_name:
                    async for event in _stream_fleetge_update(
                        host_id,
                        stack_name,
                        conn,
                        self_info,
                        cols,
                        rows,
                    ):
                        yield event

                    asyncio.create_task(
                        snapshot_manager.refresh_host_docker_with_retry(host_id)
                    )
                    _write_audit_log_standalone(
                        username, f"stack.{action}", host_id, stack_name,
                        "success", "Fleetge planned update completed", ip,
                    )
                    return

            task = asyncio.create_task(
                conn.stack_action(
                    stack_name, socket_event, log_queue=log_queue, cols=cols, rows=rows
                )
            )

            while True:
                chunk = await log_queue.get()
                if chunk is None:  # EOF sentinel from _run_with_terminal
                    break
                yield _sse_event("chunk", {"raw": chunk})

            result = await task
            task = None

            success = True
            msg = str(result)
            if isinstance(result, dict):
                ok_val = result.get("success", result.get("ok", True))
                success = bool(ok_val) if ok_val is not None else True
                msg = result.get("msg", result.get("message", str(result)))

            if success:
                try:
                    await snapshot_manager.refresh_host_docker(host_id)
                except Exception as refresh_exc:
                    logger.warning("Pre-complete refresh failed for stack action: %s", refresh_exc)

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

        except HTTPException:
            raise
        except Exception as exc:
            if task and not task.done():
                task.cancel()
            yield _sse_event("error", {"message": str(exc)})
            _write_audit_log_standalone(
                username, f"stack.{action}", host_id, stack_name,
                "error", str(exc), ip,
            )
        finally:
            if task is not None and not task.done():
                task.cancel()
            if conn is not None:
                await conn.close()

    return StreamingResponse(_stream(), media_type="text/event-stream")
