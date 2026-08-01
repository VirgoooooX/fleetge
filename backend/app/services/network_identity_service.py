"""Collect, classify, and reconcile Host public-network identity evidence."""

from __future__ import annotations

import asyncio
import ipaddress
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from app.database import engine
from app.models import HostConfig
from app.services.agent_client import AgentClient

IDENTITY_TTL = timedelta(hours=24)
_CDN_MARKERS = (
    "cloudflare", "cloudfront", "fastly", "akamai", "akamaiedge", "edgekey",
    "azureedge", "cdn77", "bunnycdn", "cachefly", "imperva", "incapsula",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _public_ip(value: object) -> str | None:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    return address.compressed if address.is_global else None


async def _dns_query(name: str, record_type: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5.0) as client:
            response = await client.get(
                "https://dns.google/resolve",
                params={"name": name, "type": record_type},
                headers={"Accept": "application/dns-json"},
            )
            response.raise_for_status()
            payload = response.json()
        return payload.get("Answer") or []
    except Exception:
        return []


async def _resolve_dns(hostname: str) -> dict:
    literal = _public_ip(hostname)
    if literal:
        return {"hostname": hostname, "addresses": [literal], "cnameChain": [], "metadata": []}

    current = hostname.rstrip(".").lower()
    cname_chain: list[str] = []
    addresses: list[str] = []
    for _ in range(5):
        cname_answers, a_answers, aaaa_answers = await asyncio.gather(
            _dns_query(current, "CNAME"),
            _dns_query(current, "A"),
            _dns_query(current, "AAAA"),
        )
        addresses.extend(
            address for answer in (*a_answers, *aaaa_answers)
            if (address := _public_ip(answer.get("data")))
        )
        cname = next((str(answer.get("data") or "").rstrip(".").lower() for answer in cname_answers), "")
        if not cname or cname == current:
            break
        cname_chain.append(cname)
        current = cname

    unique_addresses = list(dict.fromkeys(addresses))
    metadata = await asyncio.gather(*(_ip_connection_metadata(address) for address in unique_addresses))
    return {
        "hostname": hostname,
        "addresses": unique_addresses,
        "cnameChain": cname_chain,
        "metadata": metadata,
    }


async def _ip_connection_metadata(address: str) -> dict:
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5.0) as client:
            response = await client.get(
                f"https://ipwho.is/{address}",
                params={"fields": "success,connection"},
            )
            response.raise_for_status()
            connection = response.json().get("connection") or {}
        label = " ".join(str(connection.get(key) or "") for key in ("asn", "org", "isp", "domain"))
        is_cdn = any(marker in label.lower() for marker in _CDN_MARKERS)
        return {
            "address": address,
            "asn": connection.get("asn"),
            "organization": connection.get("org") or connection.get("isp"),
            "isProxyOrCdn": is_cdn,
        }
    except Exception:
        return {"address": address, "isProxyOrCdn": False, "metadataUnavailable": True}


def _agent_evidence(payload: dict | None, error: str | None) -> dict:
    if not payload:
        return {"status": "unavailable", "addresses": [], "eligible": False, "error": error}
    families = []
    addresses = []
    for key in ("ipv4", "ipv6"):
        family = payload.get(key) or {}
        address = _public_ip(family.get("address")) if family.get("trusted") else None
        if address:
            addresses.append(address)
        families.append(family)
    return {
        "status": "trusted" if addresses else "conflict",
        "addresses": addresses,
        "eligible": bool(addresses),
        "observedAt": payload.get("observedAt"),
        "proxyEnvironmentIgnored": bool(payload.get("proxyEnvironmentIgnored")),
        "families": families,
    }


def _callback_evidence(host: HostConfig) -> dict:
    address = _public_ip(host.enrollment_callback_ip)
    mode = host.enrollment_callback_mode or "unknown"
    eligible = bool(address and mode == "direct")
    reason = None
    if mode == "proxy_fallback":
        reason = "proxy_fallback"
    elif not address:
        reason = "not_public_or_unavailable"
    return {
        "status": "trusted" if eligible else "excluded",
        "addresses": [address] if address else [],
        "eligible": eligible,
        "mode": mode,
        "excludedReason": reason,
    }


def _dns_evidence(resolved: dict) -> dict:
    cname_cdn = any(marker in cname for cname in resolved.get("cnameChain") or [] for marker in _CDN_MARKERS)
    proxy_addresses = {
        item.get("address") for item in resolved.get("metadata") or [] if item.get("isProxyOrCdn")
    }
    eligible_addresses = [
        address for address in resolved.get("addresses") or []
        if not cname_cdn and address not in proxy_addresses
    ]
    reasons = []
    if cname_cdn:
        reasons.append("cdn_cname")
    if proxy_addresses:
        reasons.append("proxy_or_cdn_asn")
    return {
        **resolved,
        "status": "trusted" if eligible_addresses else "excluded",
        "eligible": bool(eligible_addresses),
        "eligibleAddresses": eligible_addresses,
        "excludedReasons": reasons,
    }


def _select_effective_ip(host: HostConfig, categories: dict) -> tuple[str | None, str | None, str]:
    override = _public_ip(host.public_ip_override)
    if override:
        return override, "fixed_override", "manual"
    votes: Counter[str] = Counter()
    sources: dict[str, list[str]] = {}
    for category, evidence in categories.items():
        if not evidence.get("eligible"):
            continue
        addresses = evidence.get("eligibleAddresses") or evidence.get("addresses") or []
        for address in set(addresses):
            votes[address] += 1
            sources.setdefault(address, []).append(category)
    candidates = [address for address, count in votes.items() if count >= 2]
    candidates.sort(key=lambda address: (ipaddress.ip_address(address).version != 4, -votes[address], address))
    if not candidates:
        return None, None, "conflict"
    selected = candidates[0]
    return selected, "+".join(sorted(sources[selected])), "high"


async def _geo_provider(provider: str, address: str) -> dict | None:
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=8.0) as client:
            if provider == "ipwho.is":
                response = await client.get(
                    f"https://ipwho.is/{address}",
                    params={"fields": "success,city,region,country,country_code,latitude,longitude"},
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("success") is False:
                    return None
                return {
                    "provider": provider, "city": payload.get("city"), "region": payload.get("region"),
                    "country": payload.get("country"), "country_code": payload.get("country_code"),
                    "latitude": payload.get("latitude"), "longitude": payload.get("longitude"),
                }
            response = await client.get(f"https://ipapi.co/{address}/json/")
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                return None
            return {
                "provider": provider, "city": payload.get("city"), "region": payload.get("region"),
                "country": payload.get("country_name"), "country_code": payload.get("country_code"),
                "latitude": payload.get("latitude"), "longitude": payload.get("longitude"),
            }
    except Exception:
        return None


async def geolocate_consensus(address: str) -> dict | None:
    results = [item for item in await asyncio.gather(
        _geo_provider("ipwho.is", address), _geo_provider("ipapi.co", address)
    ) if item]
    if len(results) != 2:
        return None
    codes = [str(item.get("country_code") or "").upper() for item in results]
    if not codes[0] or codes[0] != codes[1]:
        return None
    latitudes = [float(item["latitude"]) for item in results if item.get("latitude") is not None]
    longitudes = [float(item["longitude"]) for item in results if item.get("longitude") is not None]
    if len(latitudes) != 2 or len(longitudes) != 2:
        return None
    cities = [str(item.get("city") or "").strip() for item in results]
    regions = [str(item.get("region") or "").strip() for item in results]
    city_agrees = bool(cities[0] and cities[0].casefold() == cities[1].casefold())
    region_agrees = bool(regions[0] and regions[0].casefold() == regions[1].casefold())
    return {
        "city": cities[0] if city_agrees else None,
        "region": regions[0] if region_agrees else None,
        "country": results[0].get("country") or results[1].get("country"),
        "country_code": codes[0],
        "latitude": sum(latitudes) / 2,
        "longitude": sum(longitudes) / 2,
        "source": "ip-consensus",
        "confidence": "city" if city_agrees else ("region" if region_agrees else "country"),
        "confirmed": False,
        "providers": [item["provider"] for item in results],
    }


async def refresh_host_network_identity(host_id: str, *, force: bool = False) -> dict:
    with Session(engine) as session:
        host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
        if host is None:
            raise LookupError("Host not found")
        if (
            not force and host.network_identity_checked_at
            and _utc_now() - (host.network_identity_checked_at.replace(tzinfo=timezone.utc) if host.network_identity_checked_at.tzinfo is None else host.network_identity_checked_at) < IDENTITY_TTL
            and host.network_identity_evidence
        ):
            return json.loads(host.network_identity_evidence)

    parsed = urlparse(host.agent_url or "")
    hostname = parsed.hostname or ""
    agent_payload = None
    agent_error = None
    if host.agent_url:
        client = AgentClient(host)
        try:
            agent_payload = await client.get_network_identity(refresh=force)
        except httpx.HTTPStatusError as exc:
            agent_error = "unsupported" if exc.response.status_code == 404 else f"http_{exc.response.status_code}"
        except Exception as exc:
            agent_error = type(exc).__name__
        finally:
            await client.close()
    resolved = await _resolve_dns(hostname) if hostname else {"hostname": None, "addresses": [], "cnameChain": [], "metadata": []}
    categories = {
        "agent": _agent_evidence(agent_payload, agent_error),
        "callback": _callback_evidence(host),
        "dns": _dns_evidence(resolved),
    }
    effective, source, confidence = _select_effective_ip(host, categories)
    old_effective = host.public_ip_effective
    evidence = {
        "hostId": host_id,
        "observedAt": _utc_now().isoformat(),
        "categories": categories,
        "effectiveIp": effective,
        "effectiveSource": source,
        "confidence": confidence,
        "conflict": effective is None,
        "locationDrift": bool(old_effective and effective and old_effective != effective),
        "fixedOverride": host.public_ip_override,
    }
    suggestion = await geolocate_consensus(effective) if effective else None
    evidence["locationSuggestion"] = suggestion

    with Session(engine) as session:
        current = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
        if current is None:
            raise LookupError("Host not found")
        current.public_ip_effective = effective
        current.public_ip_source = source
        current.network_identity_evidence = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
        current.network_identity_checked_at = _utc_now()
        if suggestion and not current.location_confirmed:
            current.location_latitude = suggestion["latitude"]
            current.location_longitude = suggestion["longitude"]
            current.location_city = suggestion.get("city")
            current.location_region = suggestion.get("region")
            current.location_country = suggestion.get("country")
            current.location_country_code = suggestion.get("country_code")
            current.location_source = suggestion["source"]
            current.location_confidence = suggestion["confidence"]
        session.add(current)
        session.commit()
    return evidence


def get_stored_network_identity(host: HostConfig) -> dict | None:
    if not host.network_identity_evidence:
        return None
    try:
        evidence = json.loads(host.network_identity_evidence)
        evidence["fixedOverride"] = host.public_ip_override
        return evidence
    except Exception:
        return None
