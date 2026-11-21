"""Execute existing Docker CLI commands and own their process lifetime."""

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from compose_common import redact_sensitive_text

COMMAND_TIMEOUT = 600.0


async def spawn_docker(args: list[str], *, cwd: str | None = None, stderr=asyncio.subprocess.PIPE):
    options = {"start_new_session": True} if os.name == "posix" else {}
    return await asyncio.create_subprocess_exec(
        "docker", *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=stderr, **options
    )


async def _kill_and_drain(proc: asyncio.subprocess.Process) -> None:
    with suppress(ProcessLookupError):
        if os.name == "posix":
            # Compose may be a child process holding the captured pipe open.
            os.killpg(proc.pid, signal.SIGKILL)
        elif proc.returncode is None:
            proc.kill()
    await proc.communicate()


async def capture_docker(
    args: list[str], *, timeout: float, cwd: str | None = None, stderr=asyncio.subprocess.PIPE
) -> tuple[int, bytes, bytes | None]:
    proc = await spawn_docker(args, cwd=cwd, stderr=stderr)
    try:
        async with asyncio.timeout(timeout):
            stdout, errors = await proc.communicate()
    except (TimeoutError, asyncio.CancelledError):
        await _kill_and_drain(proc)
        raise
    return proc.returncode or 0, stdout, errors


async def stream_output(proc: asyncio.subprocess.Process, emit: Callable[[str], Awaitable[None]]) -> int:
    assert proc.stdout is not None
    try:
        while chunk := await proc.stdout.read(4096):
            await emit(chunk.decode("utf-8", errors="replace"))
        return await proc.wait()
    except BaseException:
        await _kill_and_drain(proc)
        raise


async def _stream_until_disconnect(websocket: WebSocket, stream: Coroutine[Any, Any, int]) -> int:
    # A quiet command may never write again after the client leaves.
    async def wait_for_disconnect() -> None:
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass

    reader = asyncio.create_task(stream)
    disconnect = asyncio.create_task(wait_for_disconnect())
    try:
        done, _ = await asyncio.wait({reader, disconnect}, return_when=asyncio.FIRST_COMPLETED)
        if reader in done:
            return await reader
        await disconnect
        raise WebSocketDisconnect()
    finally:
        for task in (reader, disconnect):
            if not task.done():
                task.cancel()
        await asyncio.gather(reader, disconnect, return_exceptions=True)


async def stream_with_subprocess(websocket: WebSocket, cwd: str, args: list[str]) -> int:
    try:
        proc = await spawn_docker(args, cwd=cwd, stderr=asyncio.subprocess.STDOUT)
    except OSError as exc:
        await websocket.send_json({"type": "error", "message": f"Failed to start docker command: {exc}"})
        return 1

    async def emit(chunk: str) -> None:
        await websocket.send_json({"type": "stdout", "chunk": redact_sensitive_text(chunk)})

    try:
        return await _stream_until_disconnect(websocket, stream_output(proc, emit))
    finally:
        if proc.returncode is None:
            await _kill_and_drain(proc)


async def stream_in_pty(
    websocket: WebSocket,
    cwd: str,
    args: list[str],
    cols: int,
    rows: int,
    fallback: Callable[[WebSocket, str, list[str]], Awaitable[int]],
) -> int:
    try:
        from ptyprocess import PtyProcessUnicode

        proc = PtyProcessUnicode.spawn(["docker", *args], cwd=cwd, dimensions=(rows, cols))
    except (ImportError, OSError):
        return await fallback(websocket, cwd, args)

    async def stream() -> int:
        while True:
            try:
                chunk = await asyncio.to_thread(proc.read, 4096)
            except EOFError:
                break
            if not chunk:
                break
            await websocket.send_json({"type": "stdout", "chunk": redact_sensitive_text(chunk)})
        if proc.isalive():
            await asyncio.to_thread(proc.wait)
        return proc.exitstatus if proc.exitstatus is not None else 0

    try:
        return await _stream_until_disconnect(websocket, stream())
    except BaseException:
        # forkpty starts the child in its own process group. Stop any Compose
        # child holding the PTY so a pending background read can finish.
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        raise
    finally:
        await asyncio.to_thread(proc.close, force=True)
