"""On-demand public network identity probing with environment proxies disabled."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import httpx

CACHE_SECONDS = 24 * 60 * 60
FORCE_MIN_INTERVAL_SECONDS = 60
MAX_RESPONSE_BYTES = 16 * 1024

_cache: dict[str, Any] | None = None
_cache_mono = 0.0
_last_force_mono = 0.0
_probe_lock = asyncio.Lock()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalize_public_ip(value: object, family: int) -> str | None:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    if address.version != family or not address.is_global:
        return None
    return address.compressed


def _parse_response(provider: str, body: str, family: int) -> str | None:
    if provider == "ipify":
        try:
            value = json.loads(body).get("ip")
        except Exception:
            return None
    elif provider == "cloudflare":
        value = next((line[3:] for line in body.splitlines() if line.startswith("ip=")), None)
    else:
        value = body.strip().splitlines()[0] if body.strip() else None
    return _normalize_public_ip(value, family)


async def _fetch_provider(provider: str, url: str, family: int) -> dict[str, Any]:
    local_address = "0.0.0.0" if family == 4 else "::"
    transport = httpx.AsyncHTTPTransport(local_address=local_address, retries=0)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(5.0, connect=3.0),
            headers={"Accept": "application/json,text/plain", "User-Agent": "Fleetge-Agent/1"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ValueError("response too large")
            address = _parse_response(provider, response.text, family)
            if not address:
                raise ValueError("provider returned no public address for requested family")
            return {"provider": provider, "status": "ok", "address": address}
    except Exception as exc:
        return {"provider": provider, "status": "error", "error": type(exc).__name__}


async def _probe_family(family: int) -> dict[str, Any]:
    if family == 4:
        providers = (
            ("ipify", "https://api.ipify.org?format=json"),
            ("icanhazip", "https://ipv4.icanhazip.com/"),
            ("cloudflare", "https://cloudflare.com/cdn-cgi/trace"),
        )
    else:
        providers = (
            ("ipify", "https://api6.ipify.org?format=json"),
            ("icanhazip", "https://ipv6.icanhazip.com/"),
            ("cloudflare", "https://cloudflare.com/cdn-cgi/trace"),
        )
    results = await asyncio.gather(*(_fetch_provider(name, url, family) for name, url in providers))
    addresses = [result["address"] for result in results if result.get("status") == "ok"]
    counts = Counter(addresses)
    agreed = next((address for address, count in counts.most_common() if count >= 2), None)
    return {
        "family": family,
        "address": agreed,
        "trusted": bool(agreed),
        "agreementCount": counts.get(agreed, 0) if agreed else 0,
        "providers": results,
    }


async def probe_network_identity(force: bool = False) -> dict[str, Any]:
    """Probe IPv4 and IPv6 independently; force is rate-limited to once/minute."""
    global _cache, _cache_mono, _last_force_mono
    now = time.monotonic()
    if _cache and not force and now - _cache_mono < CACHE_SECONDS:
        return {**_cache, "cached": True}
    if _cache and force and now - _last_force_mono < FORCE_MIN_INTERVAL_SECONDS:
        return {**_cache, "cached": True, "rateLimited": True}

    async with _probe_lock:
        now = time.monotonic()
        if _cache and not force and now - _cache_mono < CACHE_SECONDS:
            return {**_cache, "cached": True}
        if _cache and force and now - _last_force_mono < FORCE_MIN_INTERVAL_SECONDS:
            return {**_cache, "cached": True, "rateLimited": True}
        if force:
            _last_force_mono = now
        ipv4, ipv6 = await asyncio.gather(_probe_family(4), _probe_family(6))
        _cache = {
            "observedAt": _utc_iso(),
            "cached": False,
            "rateLimited": False,
            "proxyEnvironmentIgnored": True,
            "ipv4": ipv4,
            "ipv6": ipv6,
        }
        _cache_mono = time.monotonic()
        return dict(_cache)


def clear_network_identity_cache() -> None:
    global _cache, _cache_mono, _last_force_mono
    _cache = None
    _cache_mono = 0.0
    _last_force_mono = 0.0
