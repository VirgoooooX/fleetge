"""Credential-free, SSRF-guarded peer reachability probe for multi-vantage verification."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import ssl
import time
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
_METADATA_HOSTS = frozenset({
    "169.254.169.254",
    "169.254.170.2",
    "100.100.100.200",
    "fd00:ec2::254",
    "metadata.google.internal",
    "metadata",
    "localhost",
    "localhost.localdomain",
})
_STATUS_LINE_RE = re.compile(rb"^HTTP/\d\.\d\s+(\d{3})\b")
_PROBE_SEMAPHORE = asyncio.Semaphore(4)


class PeerProbeRequest(BaseModel):
    host: str = Field(..., min_length=1, max_length=253)
    port: int = Field(default=443, ge=1, le=65535)
    scheme: Literal["https", "http"] = "https"
    timeout_seconds: float = Field(default=5.0, ge=1.0, le=8.0)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        cleaned = value.strip().rstrip(".").lower()
        if not cleaned or not _HOST_RE.fullmatch(cleaned):
            raise ValueError("Invalid target host")
        if cleaned in _METADATA_HOSTS:
            raise ValueError("Target host is not allowed")
        return cleaned


def is_public_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return bool(
        addr.is_global
        and not addr.is_private
        and not addr.is_loopback
        and not addr.is_link_local
        and not addr.is_multicast
        and not addr.is_reserved
        and not addr.is_unspecified
    )


async def _resolve_public_target(host: str, port: int, *, allow_private_for_tests: bool = False) -> list[str]:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if not allow_private_for_tests and not is_public_ip(ip.compressed):
            raise ValueError("Target IP must be a public address")
        return [ip.compressed]

    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        addr = str(sockaddr[0])
        if addr not in addresses:
            addresses.append(addr)

    if not addresses:
        raise OSError("DNS returned no addresses")

    if not allow_private_for_tests:
        for addr in addresses:
            if not is_public_ip(addr):
                raise ValueError("Target resolves to a non-public IP address")
    return addresses


async def _close_writer(writer: asyncio.StreamWriter | None) -> None:
    if writer is None:
        return
    try:
        writer.close()
        await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
    except Exception:
        pass


async def run_peer_probe(
    req: PeerProbeRequest,
    *,
    allow_private_for_tests: bool = False,
    ssl_context: ssl.SSLContext | None = None,
) -> dict[str, Any]:
    """Run a bounded TCP -> TLS -> HTTP HEAD / probe against a public host."""
    async with _PROBE_SEMAPHORE:
        started = time.monotonic()
        dns_ok = False
        tcp_ok = False
        tls_ok: bool | None = False if req.scheme == "https" else None
        http_ok = False
        http_status: int | None = None

        try:
            addresses = await asyncio.wait_for(
                _resolve_public_target(req.host, req.port, allow_private_for_tests=allow_private_for_tests),
                timeout=min(3.0, req.timeout_seconds),
            )
            dns_ok = True
        except ValueError:
            raise
        except Exception as exc:
            return {
                "reachable": False,
                "upstream_error": False,
                "dns_ok": False,
                "tcp_ok": False,
                "tls_ok": tls_ok,
                "http_ok": False,
                "http_status": None,
                "failed_stage": "dns",
                "error": f"{type(exc).__name__}: {exc}"[:200],
                "latency_ms": int((time.monotonic() - started) * 1000),
            }

        target_ip = addresses[0]
        deadline = started + req.timeout_seconds
        reader: asyncio.StreamReader | None = None
        writer: asyncio.StreamWriter | None = None

        def remaining(cap: float) -> float:
            return max(0.2, min(cap, deadline - time.monotonic()))

        try:
            # Stage 1: TCP connect to resolved public IP (prevents DNS rebinding)
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(target_ip, req.port),
                    timeout=remaining(4.0),
                )
                tcp_ok = True
            except Exception as exc:
                return {
                    "reachable": False,
                    "upstream_error": False,
                    "dns_ok": dns_ok,
                    "tcp_ok": False,
                    "tls_ok": tls_ok,
                    "http_ok": False,
                    "http_status": None,
                    "failed_stage": "tcp",
                    "error": f"{type(exc).__name__}: {exc}"[:200],
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }

            # Stage 2: TLS handshake with certificate & SNI verification
            if req.scheme == "https":
                try:
                    ctx = ssl_context or ssl.create_default_context()
                    await asyncio.wait_for(
                        writer.start_tls(ctx, server_hostname=req.host),
                        timeout=remaining(4.0),
                    )
                    tls_ok = True
                except Exception as exc:
                    return {
                        "reachable": False,
                        "upstream_error": False,
                        "dns_ok": dns_ok,
                        "tcp_ok": tcp_ok,
                        "tls_ok": False,
                        "http_ok": False,
                        "http_status": None,
                        "failed_stage": "tls",
                        "error": f"{type(exc).__name__}: {exc}"[:200],
                        "latency_ms": int((time.monotonic() - started) * 1000),
                    }

            # Stage 3: Minimal HTTP HEAD / request (no secrets, no path, no redirects)
            try:
                default_port = 443 if req.scheme == "https" else 80
                host_header = req.host if req.port == default_port else f"{req.host}:{req.port}"
                raw_req = (
                    f"HEAD / HTTP/1.1\r\n"
                    f"Host: {host_header}\r\n"
                    f"User-Agent: Fleetge-PeerProbe/1\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode("ascii")
                writer.write(raw_req)
                await asyncio.wait_for(writer.drain(), timeout=remaining(3.0))
                status_line = await asyncio.wait_for(reader.readline(), timeout=remaining(4.0))
                match = _STATUS_LINE_RE.match(status_line or b"")
                if not match:
                    raise ValueError("Invalid or empty HTTP status line")
                http_status = int(match.group(1))
                http_ok = True
            except Exception as exc:
                return {
                    "reachable": False,
                    "upstream_error": False,
                    "dns_ok": dns_ok,
                    "tcp_ok": tcp_ok,
                    "tls_ok": tls_ok,
                    "http_ok": False,
                    "http_status": None,
                    "failed_stage": "http",
                    "error": f"{type(exc).__name__}: {exc}"[:200],
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }

            return {
                "reachable": True,
                "upstream_error": http_status in (502, 503, 504),
                "dns_ok": dns_ok,
                "tcp_ok": tcp_ok,
                "tls_ok": tls_ok,
                "http_ok": http_ok,
                "http_status": http_status,
                "failed_stage": None,
                "error": None,
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
        finally:
            await _close_writer(writer)
