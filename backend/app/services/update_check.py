"""Image update detection — registry digest comparison.

Extracts image references from containers and compose files,
queries the remote registry for the current manifest digest,
and compares with the local image digest.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Optional

import httpx

from app.config import get_settings
from app.schemas import UpdateCheckResult

logger = logging.getLogger(__name__)

# Simple in-memory cache: {image_key: {status, digest, timestamp}}
_update_cache: dict[str, dict] = {}
_cache_lock = asyncio.Lock()
FAILURE_STATUSES = {"needs_auth", "check_failed"}
INDEX_MEDIA_TYPES = {
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
}
MANIFEST_ACCEPT = (
    "application/vnd.docker.distribution.manifest.v2+json,"
    "application/vnd.oci.image.manifest.v1+json"
)
REGISTRY_ACCEPT = (
    "application/vnd.docker.distribution.manifest.v2+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.oci.image.index.v1+json"
)


def _parse_bearer_challenge(header: str) -> tuple[str, dict[str, str]] | None:
    """Parse a Docker Registry Bearer challenge.

    Public registries such as GHCR can still return a 401 challenge and require
    an anonymous Bearer token before serving manifests.
    """
    if not header or not header.lower().startswith("bearer "):
        return None

    params = {
        match.group(1).lower(): match.group(2)
        for match in re.finditer(r'([A-Za-z_][A-Za-z0-9_-]*)="([^"]*)"', header)
    }
    realm = params.get("realm")
    if not realm:
        return None

    token_params: dict[str, str] = {}
    for key in ("service", "scope"):
        if params.get(key):
            token_params[key] = params[key]
    return realm, token_params


async def _get_bearer_token_from_challenge(
    client: httpx.AsyncClient,
    header: str,
) -> tuple[Optional[str], Optional[str]]:
    challenge = _parse_bearer_challenge(header)
    if not challenge:
        return None, "needs_auth"

    realm, params = challenge
    try:
        tr = await client.get(realm, params=params, timeout=10)
        if tr.status_code in (401, 403):
            return None, "needs_auth"
        tr.raise_for_status()
        token = tr.json().get("token") or tr.json().get("access_token")
        if not token:
            return None, "check_failed"
        return token, None
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            return None, "needs_auth"
        return None, "check_failed"
    except Exception:
        return None, "check_failed"


def _parse_image_ref(image: str) -> dict:
    """Parse a Docker image reference into components.

    Returns:
        {"registry": str, "repository": str, "tag": str, "digest": str|None}
    """
    registry = ""
    repository = ""
    tag = "latest"
    digest = None

    # Check for digest reference (image@sha256:...)
    if "@" in image:
        image_part, digest = image.rsplit("@", 1)

    # Split registry/repository/tag
    remaining = image.split("@")[0] if "@" in image else image
    parts = remaining.split("/")

    if len(parts) == 1:
        repository = parts[0]
    elif len(parts) == 2:
        # Could be registry/repo or plain repo/tag
        if "." in parts[0] or ":" in parts[0] or parts[0] == "localhost":
            registry = parts[0]
            repository = parts[1]
        else:
            registry = "docker.io"
            repository = "/".join(parts)
    else:
        # Three+ parts
        if "." in parts[0] or ":" in parts[0] or parts[0] == "localhost":
            registry = parts[0]
            repository = "/".join(parts[1:])
        else:
            registry = "docker.io"
            repository = "/".join(parts)

    # Default Docker Hub
    if not registry:
        registry = "docker.io"

    # Split off tag from the last part if present
    if ":" in repository:
        repo_parts = repository.rsplit(":", 1)
        repository = repo_parts[0]
        tag = repo_parts[1]

    # Docker Hub: library/ prefix for official images
    if registry == "docker.io" and "/" not in repository:
        repository = f"library/{repository}"

    return {
        "registry": registry,
        "repository": repository,
        "tag": tag,
        "digest": digest,
    }


def _normalize_digest(value: str | None) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    return value.lower()


def _parse_platform(platform: str | None) -> dict[str, str]:
    if not platform:
        return {"os": "linux", "architecture": "amd64"}
    parts = platform.split("/")
    parsed: dict[str, str] = {}
    if len(parts) >= 1 and parts[0]:
        parsed["os"] = parts[0].lower()
    if len(parts) >= 2 and parts[1]:
        parsed["architecture"] = parts[1].lower()
    if len(parts) >= 3 and parts[2]:
        parsed["variant"] = parts[2].lower()
    parsed.setdefault("os", "linux")
    parsed.setdefault("architecture", "amd64")
    return parsed


def _platform_matches(candidate: dict | None, requested: dict[str, str]) -> bool:
    candidate = candidate or {}
    if (candidate.get("os") or "").lower() != requested.get("os"):
        return False
    if (candidate.get("architecture") or "").lower() != requested.get("architecture"):
        return False
    requested_variant = requested.get("variant")
    if requested_variant:
        return (candidate.get("variant") or "").lower() == requested_variant
    return True


async def _resolve_registry_digest_from_response(
    client: httpx.AsyncClient,
    manifest_url: str,
    response: httpx.Response,
    headers: dict[str, str],
    platform: str | None,
) -> Optional[str]:
    content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip()
    header_digest = response.headers.get("Docker-Content-Digest")
    try:
        payload = response.json()
    except Exception:
        payload = {}

    media_type = payload.get("mediaType") or content_type
    if media_type in INDEX_MEDIA_TYPES:
        requested_platform = _parse_platform(platform)
        manifests = payload.get("manifests") or []
        selected = next(
            (
                item for item in manifests
                if _platform_matches(item.get("platform"), requested_platform)
            ),
            None,
        )
        if selected is None:
            selected = next(
                (
                    item for item in manifests
                    if _platform_matches(item.get("platform"), {"os": "linux", "architecture": "amd64"})
                ),
                None,
            )
        if selected is None:
            selected = next(
                (
                    item for item in manifests
                    if (item.get("platform") or {}).get("os") != "unknown"
                ),
                None,
            )
        child_digest = selected.get("digest") if selected else None
        if not child_digest:
            return header_digest

        child_response = await client.get(
            manifest_url.rsplit("/", 1)[0] + f"/{child_digest}",
            headers={**headers, "Accept": MANIFEST_ACCEPT},
            timeout=15,
        )
        child_response.raise_for_status()
        try:
            child_payload = child_response.json()
        except Exception:
            child_payload = {}
        config_digest = (child_payload.get("config") or {}).get("digest")
        return config_digest or child_response.headers.get("Docker-Content-Digest") or child_digest

    config_digest = (payload.get("config") or {}).get("digest")
    return config_digest or header_digest


async def _get_manifest_digest(
    registry: str, repository: str, tag: str, platform: str | None = None
) -> tuple[Optional[str], Optional[str]]:
    """Query registry for the manifest digest.

    Returns (digest, error_status).
    digest is None on error; error_status is one of "needs_auth" | "check_failed".
    """
    # Determine the manifest URL and auth scope
    if registry == "docker.io":
        # Docker Hub requires a token
        manifest_url = f"https://registry-1.docker.io/v2/{repository}/manifests/{tag}"
        token_url = (
            f"https://auth.docker.io/token"
            f"?service=registry.docker.io"
            f"&scope=repository:{repository}:pull"
        )
        try:
            async with httpx.AsyncClient() as client:
                # First get a token
                tr = await client.get(token_url, timeout=10)
                if tr.status_code == 401:
                    return None, "needs_auth"
                tr.raise_for_status()
                token = tr.json().get("token", "")

                # Then request manifest
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": REGISTRY_ACCEPT,
                }
                mr = await client.get(manifest_url, headers=headers, timeout=15)
                if mr.status_code == 401:
                    return None, "needs_auth"
                mr.raise_for_status()
                digest = await _resolve_registry_digest_from_response(
                    client, manifest_url, mr, headers, platform
                )
                return digest, None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return None, "needs_auth"
            return None, "check_failed"
        except Exception:
            return None, "check_failed"

    elif registry == "ghcr.io":
        # GHCR public packages can still require an anonymous Bearer token.
        manifest_url = (
            f"https://ghcr.io/v2/{repository}/manifests/{tag}"
        )
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "Accept": REGISTRY_ACCEPT,
                }
                r = await client.get(manifest_url, headers=headers, timeout=15)
                if r.status_code == 401:
                    token, error_status = await _get_bearer_token_from_challenge(
                        client,
                        r.headers.get("WWW-Authenticate", ""),
                    )
                    if error_status:
                        return None, error_status
                    headers = {**headers, "Authorization": f"Bearer {token}"}
                    r = await client.get(
                        manifest_url,
                        headers=headers,
                        timeout=15,
                    )
                if r.status_code in (401, 403):
                    return None, "needs_auth"
                r.raise_for_status()
                digest = await _resolve_registry_digest_from_response(
                    client, manifest_url, r, headers, platform
                )
                return digest, None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                return None, "needs_auth"
            return None, "check_failed"
        except Exception:
            return None, "check_failed"

    else:
        # Generic registry (assume OCI-compatible)
        manifest_url = (
            f"https://{registry}/v2/{repository}/manifests/{tag}"
        )
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "Accept": REGISTRY_ACCEPT,
                }
                r = await client.get(manifest_url, headers=headers, timeout=10)
                if r.status_code == 401:
                    return None, "needs_auth"
                # 403 might mean the registry is accessible but view denied
                if r.status_code in (401, 403):
                    return None, "needs_auth"
                r.raise_for_status()
                digest = await _resolve_registry_digest_from_response(
                    client, manifest_url, r, headers, platform
                )
                return digest, None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                return None, "needs_auth"
            return None, "check_failed"
        except Exception:
            return None, "check_failed"


def _extract_local_digest(repo_digests: list[str]) -> Optional[str]:
    """Extract the local image digest from RepoDigests.

    Only RepoDigests provides a meaningful digest for comparison with registry.
    ImageID (content hash) must never be compared with registry manifest digest.
    Returns None if no valid RepoDigest is available — caller should mark unknown.
    """
    for d in repo_digests:
        if "@" in d:
            return d.split("@")[1]
    return None


async def check_image(
    host_id: str,
    image_ref: str,
    repo_digests: list[str] | None = None,
    local_image_id: str | None = None,
    platform: str | None = None,
    force: bool = False,
) -> UpdateCheckResult:
    """Check if a single image has an update available.

    Uses RepoDigests for local digest comparison. Never uses ImageID
    (content hash) — that is not comparable with registry manifest digest.

    Args:
        host_id: For identifying the source host.
        image_ref: Full image reference (e.g., "nginx:latest", "ghcr.io/org/repo:v1").
        repo_digests: List of RepoDigests from image inspect.

    Returns:
        UpdateCheckResult.
    """
    repo_digests = repo_digests or []
    # Check cache first
    cache_key = f"{host_id}:{image_ref}"
    if not force:
        async with _cache_lock:
            cached = _update_cache.get(cache_key)
            cache_ttl = get_settings().UPDATE_CHECK_INTERVAL
            if (
                cached
                and cached.get("status") not in FAILURE_STATUSES
                and (time.monotonic() - cached.get("ts", 0)) < cache_ttl
            ):
                return UpdateCheckResult(
                    host_id=host_id,
                    image=image_ref,
                    current_digest=cached["local"],
                    registry_digest=cached["registry"],
                    status=cached["status"],
                )

    # Parse image reference
    parsed = _parse_image_ref(image_ref)

    # Prefer Docker image ID because it is the local config digest. Registry
    # manifest/index responses are resolved to config.digest for the selected
    # platform, which avoids comparing a multi-arch index digest with a local
    # platform digest. RepoDigest remains a fallback for older snapshots.
    local_image_id = _normalize_digest(local_image_id)
    effective_local = local_image_id or _extract_local_digest(repo_digests)

    # Check registry
    registry_digest, error_status = await _get_manifest_digest(
        parsed["registry"], parsed["repository"], parsed["tag"], platform=platform
    )
    registry_digest = _normalize_digest(registry_digest)

    # Determine status
    if error_status:
        status = error_status  # "needs_auth" | "check_failed"
        registry_digest = None
    elif registry_digest and effective_local:
        status = "up_to_date" if registry_digest == effective_local else "updatable"
    elif registry_digest and not effective_local:
        # Can't compare — remote digest known but no local digest
        status = "check_failed"
    else:
        status = "check_failed"

    # Update in-memory cache only for conclusive results. Failed checks should
    # be retried by the caller instead of being hidden behind a long TTL.
    if status not in FAILURE_STATUSES:
        async with _cache_lock:
            _update_cache[cache_key] = {
                "local": effective_local,
                "registry": registry_digest,
                "status": status,
                "ts": time.monotonic(),
            }

    return UpdateCheckResult(
        host_id=host_id,
        image=image_ref,
        current_digest=effective_local,
        registry_digest=registry_digest,
        status=status,
    )


async def run_update_check(
    host_id: str, image_refs: list[tuple], force: bool = False
) -> list[UpdateCheckResult]:
    """Run update checks for multiple images on a host.

    Deduplicates by image_ref — if the same image appears multiple times
    (e.g. used by several containers), repo_digests are merged and only
    one check is performed. Non-empty digests take priority over empty ones.

    Args:
        host_id: Host identifier.
        image_refs: List of (image_ref, repo_digests) tuples.

    Returns:
        List of UpdateCheckResult (one per unique image).
    """
    # Deduplicate: merge repo_digests for the same image_ref. Keep one local
    # image ID/platform as the primary comparable identity.
    merged: dict[str, dict] = {}
    for item in image_refs:
        image_ref = item[0]
        repo_digests = item[1] if len(item) > 1 else []
        local_image_id = item[2] if len(item) > 2 else None
        platform = item[3] if len(item) > 3 else None
        existing = merged.setdefault(
            image_ref,
            {"repo_digests": [], "local_image_id": None, "platform": None},
        )
        for digest in repo_digests or []:
            if digest and digest not in existing["repo_digests"]:
                existing["repo_digests"].append(digest)
        if local_image_id and not existing["local_image_id"]:
            existing["local_image_id"] = local_image_id
        if platform and not existing["platform"]:
            existing["platform"] = platform

    semaphore = asyncio.Semaphore(8)

    async def check_one(image_ref: str, info: dict) -> UpdateCheckResult:
        async with semaphore:
            delays = [0.0, 2.0, 8.0]
            last_result: UpdateCheckResult | None = None
            for delay in delays:
                if delay:
                    await asyncio.sleep(delay)
                last_result = await check_image(
                    host_id,
                    image_ref,
                    info["repo_digests"],
                    local_image_id=info.get("local_image_id"),
                    platform=info.get("platform"),
                    force=force,
                )
                if last_result.status not in FAILURE_STATUSES:
                    return last_result
            return last_result

    return await asyncio.gather(
        *(check_one(image_ref, info) for image_ref, info in merged.items())
    )


def clear_cache() -> None:
    """Clear the update check cache (forces re-fetch on next check)."""
    global _update_cache
    _update_cache = {}
