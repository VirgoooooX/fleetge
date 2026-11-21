"""Shared network, client IP, and outbound URL validation helpers."""

from __future__ import annotations

import ipaddress
import re
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Request

from app.config import get_settings

_METADATA_HOSTS = frozenset({
    "169.254.169.254",
    "169.254.170.2",
    "100.100.100.200",
    "fd00:ec2::254",
    "metadata.google.internal",
    "metadata",
})

_HEADER_STRIP_RE = re.compile(r"[\r\n]")


def _parse_trusted_proxies() -> list[ipaddress._BaseNetwork]:
    networks: list[ipaddress._BaseNetwork] = []
    for raw in get_settings().TRUSTED_PROXY_CIDRS.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            networks.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            continue
    return networks


def is_trusted_proxy_peer(request: Request) -> bool:
    """Return True if the immediate socket peer is in TRUSTED_PROXY_CIDRS."""
    peer = request.client.host if request.client else None
    if not peer:
        return False
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(peer_ip in network for network in _parse_trusted_proxies())


def resolve_request_source_ip(request: Optional[Request]) -> Optional[str]:
    """Resolve client IP, honoring forwarded headers only from trusted proxies."""
    if request is None:
        return None
    peer = request.client.host if request.client else None
    if not peer:
        return None
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer

    trusted = _parse_trusted_proxies()
    if not any(peer_ip in network for network in trusted):
        return peer_ip.compressed

    candidates: list[str] = []
    forwarded = request.headers.get("forwarded", "")
    for group in forwarded.split(","):
        for token in group.split(";"):
            if token.strip().lower().startswith("for="):
                candidates.append(token.split("=", 1)[1].strip().strip('"'))
    candidates.extend(
        part.strip()
        for part in request.headers.get("x-forwarded-for", "").split(",")
        if part.strip()
    )

    parsed_chain: list[ipaddress._BaseAddress] = []
    for candidate in candidates:
        try:
            candidate = candidate.strip().strip('"')
            if candidate.startswith("[") and "]" in candidate:
                candidate = candidate[1:candidate.index("]")]
            elif candidate.count(":") == 1 and candidate.rsplit(":", 1)[1].isdigit():
                candidate = candidate.rsplit(":", 1)[0]
            parsed_chain.append(ipaddress.ip_address(candidate))
        except ValueError:
            continue

    for address in reversed([*parsed_chain, peer_ip]):
        if any(address in network for network in trusted):
            continue
        return address.compressed

    if peer_ip.is_global and request.headers.get("cf-connecting-ip"):
        try:
            return ipaddress.ip_address(request.headers["cf-connecting-ip"].strip()).compressed
        except ValueError:
            pass
    return peer_ip.compressed


def is_private_ip(ip: str) -> bool:
    """Return True for RFC1918/ULA/loopback/CGNAT private addresses (no test backdoors)."""
    try:
        cleaned = (ip or "").strip()
        if cleaned.lower() == "localhost":
            return True
        addr = ipaddress.ip_address(cleaned)
        return addr.is_private or addr.is_loopback
    except ValueError:
        return False


def is_public_ip(ip: str) -> bool:
    """Return True only if ip is a globally routable public IP address."""
    try:
        addr = ipaddress.ip_address((ip or "").strip())
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


def validate_outbound_http_url(
    url: str,
    *,
    allow_private: bool = False,
    require_https: bool = False,
) -> str:
    """Validate an outbound HTTP(S) URL and block cloud metadata / unsafe hosts."""
    raw = (url or "").strip()
    if not raw or _HEADER_STRIP_RE.search(raw):
        raise ValueError("Invalid URL")
    parsed = urlsplit(raw)
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    if parsed.scheme.lower() not in allowed_schemes or not parsed.hostname:
        raise ValueError("URL must use a valid http(s) scheme and hostname")
    if parsed.username or parsed.password:
        raise ValueError("URL credentials are not allowed")

    host = parsed.hostname.strip().rstrip(".").lower()
    if host in _METADATA_HOSTS:
        raise ValueError("Cloud metadata hosts are forbidden")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Hostname — still reject link-local / metadata / localhost when private disallowed
        if not allow_private and host in {"localhost", "localhost.localdomain"}:
            raise ValueError("Localhost URLs are not allowed")
        return raw

    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise ValueError("Link-local, multicast, or unspecified IP addresses are forbidden")
    if not allow_private and not is_public_ip(ip.compressed):
        raise ValueError("Private or loopback IP addresses are not allowed")
    return raw
