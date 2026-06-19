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


async def _get_manifest_digest(
    registry: str, repository: str, tag: str
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
                    "Accept": (
                        "application/vnd.docker.distribution.manifest.v2+json,"
                        "application/vnd.docker.distribution.manifest.list.v2+json,"
                        "application/vnd.oci.image.manifest.v1+json,"
                        "application/vnd.oci.image.index.v1+json"
                    ),
                }
                mr = await client.get(manifest_url, headers=headers, timeout=15)
                if mr.status_code == 401:
                    return None, "needs_auth"
                mr.raise_for_status()
                digest = mr.headers.get("Docker-Content-Digest")
                return digest, None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return None, "needs_auth"
            return None, "check_failed"
        except Exception:
            return None, "check_failed"

    elif registry == "ghcr.io":
        # GHCR — no token needed for public images
        manifest_url = (
            f"https://ghcr.io/v2/{repository}/manifests/{tag}"
        )
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "Accept": (
                        "application/vnd.docker.distribution.manifest.v2+json,"
                        "application/vnd.docker.distribution.manifest.list.v2+json,"
                        "application/vnd.oci.image.manifest.v1+json,"
                        "application/vnd.oci.image.index.v1+json"
                    ),
                }
                r = await client.get(manifest_url, headers=headers, timeout=15)
                if r.status_code == 401:
                    return None, "needs_auth"
                r.raise_for_status()
                digest = r.headers.get("Docker-Content-Digest")
                return digest, None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
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
                    "Accept": (
                        "application/vnd.docker.distribution.manifest.v2+json,"
                        "application/vnd.docker.distribution.manifest.list.v2+json,"
                        "application/vnd.oci.image.manifest.v1+json,"
                        "application/vnd.oci.image.index.v1+json"
                    ),
                }
                r = await client.get(manifest_url, headers=headers, timeout=10)
                if r.status_code == 401:
                    return None, "needs_auth"
                # 403 might mean the registry is accessible but view denied
                if r.status_code in (401, 403):
                    return None, "needs_auth"
                r.raise_for_status()
                digest = r.headers.get("Docker-Content-Digest")
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

    # Extract local digest from RepoDigest only (never ImageID)
    effective_local = _extract_local_digest(repo_digests)

    # Check registry
    registry_digest, error_status = await _get_manifest_digest(
        parsed["registry"], parsed["repository"], parsed["tag"]
    )

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
    host_id: str, image_refs: list[tuple[str, list[str]]], force: bool = False
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
    # Deduplicate: merge repo_digests for the same image_ref
    merged: dict[str, list[str]] = {}
    for image_ref, repo_digests in image_refs:
        existing = merged.setdefault(image_ref, [])
        for digest in repo_digests or []:
            if digest and digest not in existing:
                existing.append(digest)

    semaphore = asyncio.Semaphore(8)

    async def check_one(image_ref: str, repo_digests: list[str]) -> UpdateCheckResult:
        async with semaphore:
            delays = [0.0, 2.0, 8.0]
            last_result: UpdateCheckResult | None = None
            for delay in delays:
                if delay:
                    await asyncio.sleep(delay)
                last_result = await check_image(host_id, image_ref, repo_digests, force=force)
                if last_result.status not in FAILURE_STATUSES:
                    return last_result
            return last_result

    return await asyncio.gather(
        *(check_one(image_ref, repo_digests) for image_ref, repo_digests in merged.items())
    )


def clear_cache() -> None:
    """Clear the update check cache (forces re-fetch on next check)."""
    global _update_cache
    _update_cache = {}
