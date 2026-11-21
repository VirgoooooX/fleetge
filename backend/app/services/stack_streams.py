"""Server-sent event generators for stack operations and logs."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING

import httpx
from fastapi import HTTPException

if TYPE_CHECKING:
    from app.models import HostConfig
    from app.schemas import ContainerSummary, StackComposeSaveRequest
    from app.services.agent_client import AgentClient
    from app.services.auto_update import AutoUpdateManager
    from app.services.snapshot import HostSnapshot, SnapshotManager

    AuditWriter = Callable[
        [str, str, str, str | None, str, str | None, str | None], None
    ]

logger = logging.getLogger(__name__)


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


def _safe_error_detail(exc: Exception, fallback: str = "Agent communication failed") -> str:
    """Return a client-safe error message without leaking internal agent URLs or secret paths."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            body = exc.response.json()
            if isinstance(body, dict) and body.get("detail"):
                return str(body["detail"])
        except Exception:
            pass
        return f"Agent returned HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.HTTPError):
        return f"{fallback} ({type(exc).__name__})"
    msg = re.sub(r"https?://[^\s'\"]+", "[redacted-url]", str(exc))
    return msg or fallback


async def stream_compose_deploy(
    host_config: HostConfig,
    host_id: str,
    stack_name: str,
    snap: HostSnapshot,
    payload: StackComposeSaveRequest,
    cols: int,
    rows: int,
    username: str,
    ip: str | None,
    *,
    agent_client: Callable[[HostConfig], AgentClient],
    snapshot_manager: SnapshotManager,
    audit_log: AuditWriter,
) -> AsyncGenerator[str, None]:
    log_queue: asyncio.Queue = asyncio.Queue()
    task: asyncio.Task | None = None
    if not host_config.agent_url:
        yield _sse_event("error", {"message": "Host has no agent_url configured"})
        return

    conn = agent_client(host_config)
    try:
        # Capture pre-deploy updatable targets so finalize can judge them.
        target_images = _capture_updatable_targets(snap, stack_name)

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

            if target_images:
                async for event in _run_finalize(snapshot_manager, host_id, stack_name, target_images):
                    yield event

        yield _sse_event(
            "complete",
            {"status": "success" if success else "error", "message": msg},
        )

        snapshot_manager.schedule_host_structure_refresh(host_id)
        audit_log(
            username, "stack.compose.deploy", host_id, stack_name,
            "success" if success else "error", msg, ip,
        )

    except HTTPException:
        raise
    except Exception as exc:
        if task and not task.done():
            task.cancel()
        logger.warning("Deploy compose stream failed for %s/%s: %s", host_id, stack_name, exc)
        yield _sse_event("error", {"message": _safe_error_detail(exc)})
        audit_log(
            username, "stack.compose.deploy", host_id, stack_name,
            "error", str(exc)[:500], ip,
        )
    finally:
        # Ensure background task is cleaned up even if client disconnects
        if task is not None and not task.done():
            task.cancel()
        if conn is not None:
            await conn.close()


async def stream_system_prune(
    host_config: HostConfig,
    host_id: str,
    username: str,
    ip: str | None,
    *,
    agent_client: Callable[[HostConfig], AgentClient],
    snapshot_manager: SnapshotManager,
    audit_log: AuditWriter,
) -> AsyncGenerator[str, None]:
    log_queue: asyncio.Queue = asyncio.Queue()
    task: asyncio.Task | None = None
    conn: AgentClient | None = None
    try:
        conn = agent_client(host_config)
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

        snapshot_manager.schedule_all_structure_refresh()
        audit_log(
            username, "docker.prune", host_id, None,
            "success" if success else "error", msg, ip,
        )

    except HTTPException:
        raise
    except Exception as exc:
        if task and not task.done():
            task.cancel()
        logger.warning("Prune stream failed for %s: %s", host_id, exc)
        yield _sse_event("error", {"message": _safe_error_detail(exc)})
        audit_log(
            username, "docker.prune", host_id, None,
            "error", str(exc)[:500], ip,
        )
    finally:
        if task is not None and not task.done():
            task.cancel()
        if conn is not None:
            await conn.close()


def _parse_compose_log_line(line: str) -> dict:
    clean = _clean_log_text(line).rstrip("\r")
    if " | " in clean:
        service, text = clean.split(" | ", 1)
        return {"text": text, "service": service.strip()}
    return {"text": clean, "service": ""}


async def stream_compose_logs(
    host_config: HostConfig,
    host_id: str,
    stack_name: str,
    containers: list[ContainerSummary],
    tail: int,
    *,
    agent_client: Callable[[HostConfig], AgentClient],
) -> AsyncGenerator[str, None]:
    if not host_config.agent_url:
        yield _sse_event(
            "complete",
            {"message": "Host has no agent_url configured"},
        )
        return

    proxy = agent_client(host_config)
    stack_containers = [
        c
        for c in containers
        if c.stack_name == stack_name and c.state == "running"
    ]

    async def stream_container_fallback(container: ContainerSummary, queue: asyncio.Queue) -> None:
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
                    yield _sse_event("line", _parse_compose_log_line(line))
            if buffer:
                yield _sse_event("line", _parse_compose_log_line(buffer))
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
        done_task: asyncio.Task | None = None

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


async def stream_service_action(
    host_config: HostConfig,
    host_id: str,
    stack_name: str,
    service_name: str,
    socket_event: str,
    action: str,
    cols: int,
    rows: int,
    username: str,
    ip: str | None,
    *,
    agent_client: Callable[[HostConfig], AgentClient],
    snapshot_manager: SnapshotManager,
    audit_log: AuditWriter,
) -> AsyncGenerator[str, None]:
    log_queue: asyncio.Queue = asyncio.Queue()
    task: asyncio.Task | None = None
    if not host_config.agent_url:
        yield _sse_event("error", {"message": "Host has no agent_url configured"})
        return

    conn = agent_client(host_config)
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

        snapshot_manager.schedule_host_structure_refresh(host_id)
        audit_log(
            username, f"stack.service.{action}", host_id, stack_name,
            "success" if success else "error", f"{service_name}: {msg}", ip,
        )

    except Exception as exc:
        if task and not task.done():
            task.cancel()
        logger.warning("Service action stream failed for %s/%s: %s", host_id, stack_name, exc)
        yield _sse_event("error", {"message": _safe_error_detail(exc)})
        audit_log(
            username, f"stack.service.{action}", host_id, stack_name,
            "error", f"{service_name}: {exc}"[:500], ip,
        )
    finally:
        if task is not None and not task.done():
            task.cancel()
        await conn.close()


def _capture_updatable_targets(snap: HostSnapshot, stack_name: str) -> list[str]:
    """Snapshot the images marked updatable for this stack BEFORE the update.

    ``finalize_stack_update`` only needs to judge these images — an image that
    was already up_to_date has nothing to clear. Capturing pre-update avoids
    racing with the refresh that runs after ``compose up``.
    """
    targets: list[str] = []
    seen: set[str] = set()
    for container in getattr(snap, "containers", []):
        if container.stack_name != stack_name or not container.image:
            continue
        if container.image in seen:
            continue
        result = getattr(snap, "update_results", {}).get(container.image)
        if result == "updatable":
            targets.append(container.image)
            seen.add(container.image)
    return targets


async def _run_finalize(
    snapshot_manager: SnapshotManager,
    host_id: str,
    stack_name: str,
    target_images: list[str],
    wait_timeout: float = 45.0,
) -> AsyncGenerator[str, None]:
    """Run finalize_stack_update and stream a per-image verdict block.

    Emits ``chunk`` SSE events containing the verdict lines. Intended to be
    emitted right before the ``complete`` event on a successful update, so the
    user sees *why* each tag was cleared or kept.
    """
    if not target_images:
        yield _sse_event("chunk", {"raw": "No images were marked updatable; nothing to clear.\n"})
        return

    yield _sse_event("chunk", {"raw": "\n--- update verification ---\n"})
    try:
        summaries = await snapshot_manager.finalize_stack_update(
            host_id, stack_name, target_images, wait_timeout=wait_timeout
        )
    except Exception as exc:
        logger.warning("finalize_stack_update failed for %s/%s: %s", host_id, stack_name, exc)
        yield _sse_event("chunk", {
            "raw": f"Update verification skipped (internal error: {exc}). Tag state unchanged.\n"
        })
        return

    if not summaries:
        yield _sse_event("chunk", {"raw": "No updatable tags found to verify.\n"})
        return

    for s in summaries:
        marker = "✓" if s.cleared else "·"
        yield _sse_event("chunk", {"raw": f"{marker} {s.verdict}\n"})


async def stream_update_run(
    manager: AutoUpdateManager,
    host_id: str,
    request_id: str,
    stack_name: str,
    after: int = 0,
) -> AsyncGenerator[str, None]:
    replayed_tail = False
    last_stage = ""
    while True:
        batch = manager.get_batch(host_id, request_id)
        if batch is None:
            yield _sse_event("error", {"message": "Update run could not be found."})
            return
        run = next((item for item in batch["items"] if item["stack_name"] == stack_name), None)
        if run is None:
            yield _sse_event("error", {"message": "Update run does not include this Stack."})
            return
        chunks = manager.read_run_output(run["id"], after)
        if chunks is None and not replayed_tail and run.get("log_tail"):
            yield _sse_event("chunk", {"raw": run["log_tail"]})
            replayed_tail = True
        for sequence, text in chunks or []:
            yield _sse_event("chunk", {"raw": text, "cursor": sequence})
            after = sequence
        if run["stage"] != last_stage:
            yield _sse_event("stage", {"stage": run["stage"], "status": run["status"]})
            last_stage = run["stage"]
        if run["status"] in {"success", "partial", "failed", "uncertain", "skipped"}:
            yield _sse_event("complete", {
                "status": "success" if run["status"] == "success" else "error",
                "outcome": run["status"],
                "message": run.get("detail") or run["status"],
            })
            return
        await asyncio.sleep(0.2)


async def stream_stack_action(
    host_config: HostConfig,
    host_id: str,
    stack_name: str,
    socket_event: str,
    action: str,
    cols: int,
    rows: int,
    username: str,
    ip: str | None,
    *,
    agent_client: Callable[[HostConfig], AgentClient],
    snapshot_manager: SnapshotManager,
    audit_log: AuditWriter,
) -> AsyncGenerator[str, None]:
    log_queue: asyncio.Queue = asyncio.Queue()
    task: asyncio.Task | None = None
    if not host_config.agent_url:
        yield _sse_event("error", {"message": "Host has no agent_url configured"})
        return

    conn = agent_client(host_config)
    try:
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

        snapshot_manager.schedule_host_structure_refresh(host_id)
        audit_log(
            username, f"stack.{action}", host_id, stack_name,
            "success" if success else "error", msg, ip,
        )

    except HTTPException:
        raise
    except Exception as exc:
        if task and not task.done():
            task.cancel()
        logger.warning("Stack action stream failed for %s/%s: %s", host_id, stack_name, exc)
        yield _sse_event("error", {"message": _safe_error_detail(exc)})
        audit_log(
            username, f"stack.{action}", host_id, stack_name,
            "error", str(exc)[:500], ip,
        )
    finally:
        if task is not None and not task.done():
            task.cancel()
        if conn is not None:
            await conn.close()
