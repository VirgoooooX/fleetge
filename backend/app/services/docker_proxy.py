"""docker-socket-proxy HTTP client.

Communicates with a remote docker-socket-proxy instance over HTTP/HTTPS.
Every request is read-only — the proxy must have POST=0.
"""

import asyncio
import logging
import re
from typing import AsyncIterator, Optional

import httpx

from app.models import HostConfig
from app.services.crypto import decrypt_authorization_header

logger = logging.getLogger(__name__)

_ANSI_RE = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


class _DockerLogDemuxer:
    """Decode Docker's non-TTY raw-stream log framing.

    Docker logs for non-TTY containers may be multiplexed as:
    1 byte stream id, 3 zero bytes, 4 byte big-endian payload length, payload.
    Passing those bytes through as UTF-8 produces the visible box characters
    seen before log lines.
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
                # Unexpected mixed/plain bytes after a multiplexed stream.
                # Emit what remains rather than dropping user logs.
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
    """Remove terminal-only escapes/control bytes for the plain log panel."""
    text = _ANSI_RE.sub("", text)
    return _CONTROL_RE.sub("", text)


class DockerProxyClient:
    """Read-only HTTP client for one docker-socket-proxy instance."""

    def __init__(self, config: HostConfig):
        self._host_id = config.host_id
        self._base_url = config.docker_proxy_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

        # Decrypt stored auth header
        if config.docker_proxy_auth_encrypted:
            try:
                self._auth_header = decrypt_authorization_header(
                    config.docker_proxy_auth_encrypted
                )
            except ValueError:
                logger.error(
                    "Failed to decrypt docker-proxy auth for %s", config.host_id
                )
                self._auth_header = None
        else:
            self._auth_header = None

    def _headers(self) -> dict:
        return (
            {"Authorization": self._auth_header} if self._auth_header else {}
        )

    async def ping(self) -> bool:
        """Simple health check — GET /_ping."""
        try:
            r = await self._client.get("/_ping", headers=self._headers())
            return r.status_code == 200
        except Exception:
            return False

    async def version(self) -> dict:
        """GET /version returns Docker version info."""
        r = await self._client.get("/version", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def info(self) -> dict:
        """GET /info returns Docker engine/system info."""
        r = await self._client.get("/info", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def disk_usage(self) -> dict:
        """GET /system/df returns Docker disk usage."""
        r = await self._client.get("/system/df", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def list_containers(self, all: bool = True) -> list[dict]:
        """GET /containers/json returns container list."""
        params = {"all": "1" if all else "0"}
        r = await self._client.get(
            "/containers/json", params=params, headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    async def container_inspect(self, container_id: str) -> dict:
        """GET /containers/{id}/json returns container details.

        Includes RepoDigests in the Image field's metadata.
        """
        r = await self._client.get(
            f"/containers/{container_id}/json", headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    async def image_inspect(self, image_name: str) -> dict:
        """GET /images/{name}/json returns image details, including RepoDigests."""
        # URL-encode the image name (e.g. "library/nginx:latest")
        import urllib.parse
        encoded = urllib.parse.quote(image_name, safe="")
        r = await self._client.get(
            f"/images/{encoded}/json", headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    async def container_stats(self, container_id: str) -> Optional[dict]:
        """GET /containers/{id}/stats?stream=false returns one-shot stats.

        Returns None on any error (e.g., container not running).
        """
        try:
            r = await self._client.get(
                f"/containers/{container_id}/stats",
                params={"stream": "false"},
                headers=self._headers(),
                timeout=10.0,
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.debug("Stats fetch failed for %s/%s: %s", self._host_id, container_id, exc)
            return None

    async def list_images(self) -> list[dict]:
        """GET /images/json returns image list."""
        r = await self._client.get("/images/json", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def container_logs(self, container_id: str, tail: int = 200) -> str:
        """GET /containers/{id}/logs returns container logs (stdout + stderr).

        Args:
            container_id: Container ID or name.
            tail: Number of recent lines (max 5000).
        """
        try:
            r = await self._client.get(
                f"/containers/{container_id}/logs",
                params={
                    "stdout": "1",
                    "stderr": "1",
                    "tail": str(min(tail, 5000)),
                },
                headers=self._headers(),
                timeout=15.0,
            )
            r.raise_for_status()
            demuxer = _DockerLogDemuxer()
            chunks = demuxer.feed(r.content)
            flushed = demuxer.flush()
            if flushed:
                chunks.append(flushed)
            text = b"".join(chunks).decode("utf-8", errors="replace")
            return _clean_container_log_text(text)
        except Exception as exc:
            logger.debug(
                "Container logs failed for %s/%s: %s",
                self._host_id, container_id, exc,
            )
            return f"[Error fetching container logs: {exc}]"

    async def stream_container_logs(
        self, container_id: str, tail: int = 200
    ) -> AsyncIterator[str]:
        """Stream /containers/{id}/logs?follow=1 as decoded text chunks."""
        async with self._client.stream(
            "GET",
            f"/containers/{container_id}/logs",
            params={
                "stdout": "1",
                "stderr": "1",
                "follow": "1",
                "tail": str(min(tail, 5000)),
            },
            headers=self._headers(),
            timeout=None,
        ) as response:
            response.raise_for_status()
            demuxer = _DockerLogDemuxer()
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

    async def close(self) -> None:
        await self._client.aclose()
