import re
from typing import AsyncIterator
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import StreamingResponse
import httpx

DOCKER_SOCKET_PATH = "/var/run/docker.sock"

# Router prefix matches Fleetge Backend forwarding expectations
router = APIRouter()

# Regular expressions for read-only Docker API path whitelist
ALLOWED_PATTERNS = [
    re.compile(r"^/_ping$"),
    re.compile(r"^/version$"),
    re.compile(r"^/info$"),
    re.compile(r"^/system/df$"),
    re.compile(r"^/containers/json$"),
    re.compile(r"^/images/json$"),
    re.compile(r"^/containers/[a-zA-Z0-9_-]+/json$"),
    re.compile(r"^/images/[a-zA-Z0-9_%\-\.:/]+/json$"), # matches URL-encoded image names
    re.compile(r"^/containers/[a-zA-Z0-9_-]+/stats$"),
    re.compile(r"^/containers/[a-zA-Z0-9_-]+/logs$"),
]

# regexes for ANSI escape sequences and control characters
_ANSI_RE = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


class _DockerLogDemuxer:
    """Decode Docker's non-TTY multiplexed raw-stream log framing.
    
    Docker multiplexes stdout/stderr into frames of:
    1 byte stream id, 3 zero bytes, 4 byte big-endian payload length, payload.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._multiplexed: bool | None = None

    @staticmethod
    def _valid_header(buffer: bytearray) -> bool:
        if len(buffer) < 8:
            return False
        if buffer[0] not in (1, 2):
            return False
        if buffer[1:4] != b"\x00\x00\x00":
            return False
        size = int.from_bytes(buffer[4:8], "big")
        return 0 <= size <= 16 * 1024 * 1024

    def feed(self, chunk: bytes) -> list[bytes]:
        if not chunk:
            return []

        if self._multiplexed is False:
            return [chunk]

        self._buffer.extend(chunk)
        out: list[bytes] = []

        while self._buffer:
            if self._multiplexed is None:
                if len(self._buffer) < 8:
                    break
                self._multiplexed = self._valid_header(self._buffer)
                if not self._multiplexed:
                    out.append(bytes(self._buffer))
                    self._buffer.clear()
                    break

            if len(self._buffer) < 8:
                break

            if not self._valid_header(self._buffer):
                out.append(bytes(self._buffer))
                self._buffer.clear()
                break

            size = int.from_bytes(self._buffer[4:8], "big")
            frame_len = 8 + size
            if len(self._buffer) < frame_len:
                break

            payload = bytes(self._buffer[8:frame_len])
            del self._buffer[:frame_len]
            if payload:
                out.append(payload)

        return out

    def flush(self) -> bytes:
        if not self._buffer:
            return b""
        remaining = bytes(self._buffer)
        self._buffer.clear()
        return remaining


def _clean_container_log_text(text: str) -> str:
    """Remove terminal ANSI escapes and invalid control characters."""
    text = _ANSI_RE.sub("", text)
    return _CONTROL_RE.sub("", text)


import os
import sys

DOCKER_HOST = os.environ.get("DOCKER_HOST", "")

if DOCKER_HOST:
    if DOCKER_HOST.startswith("tcp://"):
        docker_client = httpx.AsyncClient(base_url=DOCKER_HOST.replace("tcp://", "http://"))
    elif DOCKER_HOST.startswith("unix://"):
        uds_path = DOCKER_HOST.replace("unix://", "")
        transport = httpx.AsyncHTTPTransport(uds=uds_path)
        docker_client = httpx.AsyncClient(transport=transport, base_url="http://localhost")
    else:
        # Fallback to direct HTTP URL if supplied
        docker_client = httpx.AsyncClient(base_url=DOCKER_HOST)
else:
    if sys.platform == "win32":
        # Default to TCP loopback on Windows (requires exposing daemon on port 2375 in Docker Desktop settings)
        docker_client = httpx.AsyncClient(base_url="http://127.0.0.1:2375")
    else:
        # Default to Unix domain socket on Unix platforms
        transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
        docker_client = httpx.AsyncClient(transport=transport, base_url="http://localhost")


async def close_docker_client():
    """Close the module-level httpx client (called from app lifespan)."""
    await docker_client.aclose()


@router.get("/docker/{docker_path:path}")
async def proxy_docker(docker_path: str, request: Request):
    """Enforce read-only GET whitelist on all proxied Docker socket requests."""
    # Ensure it's GET
    if request.method != "GET":
        raise HTTPException(
            status_code=403,
            detail=f"Method {request.method} is forbidden on Docker Proxy."
        )

    path_with_slash = "/" + docker_path

    # Check path pattern
    matched = False
    for pattern in ALLOWED_PATTERNS:
        if pattern.match(path_with_slash):
            matched = True
            break

    if not matched:
        raise HTTPException(
            status_code=403,
            detail="Forbidden. Docker endpoint is not in the read-only whitelist."
        )

    params = dict(request.query_params)

    # 1. Custom handling for log endpoint
    if "logs" in path_with_slash:
        follow = params.get("follow") in ("1", "true")
        
        if follow:
            async def log_stream_generator() -> AsyncIterator[str]:
                demuxer = _DockerLogDemuxer()
                try:
                    async with docker_client.stream(
                        "GET",
                        path_with_slash,
                        params=params,
                        timeout=None
                    ) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes():
                            for payload in demuxer.feed(chunk):
                                text = payload.decode("utf-8", errors="replace")
                                cleaned = _clean_container_log_text(text)
                                if cleaned:
                                    yield cleaned
                        flushed = demuxer.flush()
                        if flushed:
                            cleaned = _clean_container_log_text(
                                flushed.decode("utf-8", errors="replace")
                            )
                            if cleaned:
                                yield cleaned
                except Exception as exc:
                    yield f"[Agent log stream error: {exc}]"
            return StreamingResponse(log_stream_generator(), media_type="text/plain")
        else:
            try:
                response = await docker_client.get(
                    path_with_slash, params=params, timeout=15.0
                )
                response.raise_for_status()
                demuxer = _DockerLogDemuxer()
                chunks = demuxer.feed(response.content)
                flushed = demuxer.flush()
                if flushed:
                    chunks.append(flushed)
                text = b"".join(chunks).decode("utf-8", errors="replace")
                cleaned = _clean_container_log_text(text)
                return Response(content=cleaned, media_type="text/plain")
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Docker logs proxy error: {exc}")

    # 2. General proxying for other endpoints
    try:
        response = await docker_client.get(
            path_with_slash, params=params, timeout=15.0
        )
        # Transmit status, content, and headers (like content-type)
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers={"Content-Type": response.headers.get("Content-Type", "application/json")}
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Docker proxy error: {exc}")
