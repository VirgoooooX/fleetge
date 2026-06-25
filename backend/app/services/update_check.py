"""Image update detection — registry digest comparison.

Extracts image references from containers and compose files,
queries the remote registry for the current manifest digest,
and compares with the local image digest.
"""

import asyncio
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.schemas import UpdateCheckResult

logger = logging.getLogger(__name__)

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


# Statuses that mean "we know there is no update info right now, retry later".
# These are surfaced (not silently dropped) so operators can see how many
# images failed and why. rate_limited is distinct from check_failed: it carries
# Retry-After semantics and should trigger registry-level backoff (see P0-b).
FAILURE_STATUSES = {"needs_auth", "check_failed", "rate_limited"}
FAILURE_RETRY_DELAYS = (0.0, 2.0, 8.0)
REGISTRY_FREEZE_SECONDS = 900

_registry_client: httpx.AsyncClient | None = None
_docker_token_cache: dict[str, dict[str, float | str]] = {}
_registry_frozen_until: dict[str, float] = {}


@dataclass
class RegistryDigests:
    repo_digests: list[str]
    config_digest: Optional[str] = None
    resolved_platform: Optional[str] = None


@dataclass
class RegistryLookupResult:
    digests: RegistryDigests
    error_status: Optional[str] = None
    http_status: Optional[int] = None
    retry_after: Optional[int] = None


def _classify_http_status(status_code: int) -> Optional[str]:
    """Map a registry HTTP status to an error_status, or None for non-errors.

    401/403 -> needs_auth    (anonymous/pull denied; auth would help)
    429/503 -> rate_limited  (registry overloaded or throttling us; Retry-After applies)
    other 4xx/5xx -> None    (caller falls through to check_failed)
    """
    if status_code in (401, 403):
        return "needs_auth"
    if status_code in (429, 503):
        return "rate_limited"
    return None


def _format_platform(platform: dict | None) -> Optional[str]:
    platform = platform or {}
    parts = [
        (platform.get("os") or "").strip().lower(),
        (platform.get("architecture") or "").strip().lower(),
        (platform.get("variant") or "").strip().lower(),
    ]
    parts = [part for part in parts if part]
    return "/".join(parts) if parts else None


def _parse_retry_after(value: str | None) -> Optional[int]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return max(1, int(value))
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delay = int((parsed - datetime.now(timezone.utc)).total_seconds())
        return max(1, delay)
    except Exception:
        return None


async def _get_registry_client() -> httpx.AsyncClient:
    global _registry_client
    if _registry_client is None:
        _registry_client = httpx.AsyncClient()
    return _registry_client


def _get_registry_retry_after(registry: str) -> Optional[int]:
    frozen_until = _registry_frozen_until.get(registry, 0.0)
    remaining = int(round(frozen_until - time.monotonic()))
    return remaining if remaining > 0 else None


def _freeze_registry(registry: str, retry_after: Optional[int]) -> int:
    effective_retry_after = max(1, retry_after or REGISTRY_FREEZE_SECONDS)
    _registry_frozen_until[registry] = max(
        _registry_frozen_until.get(registry, 0.0),
        time.monotonic() + effective_retry_after,
    )
    return effective_retry_after


def _build_error_result(
    registry: str,
    status_code: int,
    *,
    retry_after: Optional[int] = None,
) -> RegistryLookupResult:
    error_status = _classify_http_status(status_code) or "check_failed"
    if error_status == "rate_limited":
        retry_after = _freeze_registry(registry, retry_after)
    return RegistryLookupResult(
        digests=RegistryDigests(repo_digests=[]),
        error_status=error_status,
        http_status=status_code,
        retry_after=retry_after,
    )


def _error_from_response(registry: str, response: httpx.Response) -> Optional[RegistryLookupResult]:
    if response.status_code < 400:
        return None
    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
    return _build_error_result(
        registry,
        response.status_code,
        retry_after=retry_after,
    )


def _docker_token_cache_get(repository: str) -> Optional[str]:
    cached = _docker_token_cache.get(repository)
    if not cached:
        return None
    expires_at = float(cached.get("expires_at", 0.0))
    if expires_at <= time.monotonic():
        _docker_token_cache.pop(repository, None)
        return None
    token = cached.get("token")
    return str(token) if token else None


def _docker_token_cache_set(repository: str, token: str, expires_in: int) -> None:
    ttl = max(30, expires_in - 15)
    _docker_token_cache[repository] = {
        "token": token,
        "expires_at": time.monotonic() + ttl,
    }


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
    registry: str,
    header: str,
) -> tuple[Optional[str], Optional[RegistryLookupResult]]:
    challenge = _parse_bearer_challenge(header)
    if not challenge:
        return None, RegistryLookupResult(
            digests=RegistryDigests(repo_digests=[]),
            error_status="needs_auth",
            http_status=401,
        )

    realm, params = challenge
    try:
        tr = await client.get(realm, params=params, timeout=10)
        error = _error_from_response(registry, tr)
        if error is not None:
            return None, error
        tr.raise_for_status()
        token = tr.json().get("token") or tr.json().get("access_token")
        if not token:
            return None, RegistryLookupResult(
                digests=RegistryDigests(repo_digests=[]),
                error_status="check_failed",
            )
        return token, None
    except httpx.HTTPStatusError as exc:
        return None, _build_error_result(
            registry,
            exc.response.status_code,
            retry_after=_parse_retry_after(exc.response.headers.get("Retry-After")),
        )
    except Exception:
        return None, RegistryLookupResult(
            digests=RegistryDigests(repo_digests=[]),
            error_status="check_failed",
        )


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


def _append_digest(values: list[str], value: str | None) -> None:
    digest = _normalize_digest(value)
    if digest and digest not in values:
        values.append(digest)


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


def _platform_matches(candidate: dict | None, requested: dict[str, str], exact_variant: bool = True) -> bool:
    candidate = candidate or {}
    if (candidate.get("os") or "").lower() != requested.get("os"):
        return False
    if (candidate.get("architecture") or "").lower() != requested.get("architecture"):
        return False
    requested_variant = requested.get("variant")
    if exact_variant and requested_variant:
        return (candidate.get("variant") or "").lower() == requested_variant
    return True


async def _resolve_registry_digests_from_response(
    client: httpx.AsyncClient,
    manifest_url: str,
    response: httpx.Response,
    headers: dict[str, str],
    platform: str | None,
) -> RegistryDigests:
    content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip()
    header_digest = response.headers.get("Docker-Content-Digest")
    repo_digests: list[str] = []
    _append_digest(repo_digests, header_digest)
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
                if _platform_matches(item.get("platform"), requested_platform, exact_variant=True)
            ),
            None,
        )
        if selected is None and requested_platform.get("variant"):
            # Fallback: match architecture without exact variant (e.g. arm64/v8 matches arm64)
            selected = next(
                (
                    item for item in manifests
                    if _platform_matches(item.get("platform"), requested_platform, exact_variant=False)
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
            return RegistryDigests(
                repo_digests=repo_digests,
                resolved_platform=_format_platform(selected.get("platform") if selected else None),
            )
        _append_digest(repo_digests, child_digest)

        child_response = await client.get(
            manifest_url.rsplit("/", 1)[0] + f"/{child_digest}",
            headers={**headers, "Accept": MANIFEST_ACCEPT},
            timeout=15,
        )
        child_response.raise_for_status()
        _append_digest(repo_digests, child_response.headers.get("Docker-Content-Digest"))
        try:
            child_payload = child_response.json()
        except Exception:
            child_payload = {}
        config_digest = (child_payload.get("config") or {}).get("digest")
        return RegistryDigests(
            repo_digests=repo_digests,
            config_digest=_normalize_digest(config_digest),
            resolved_platform=_format_platform(selected.get("platform") if selected else None),
        )

    config_digest = (payload.get("config") or {}).get("digest")
    return RegistryDigests(
        repo_digests=repo_digests,
        config_digest=_normalize_digest(config_digest),
    )


async def _resolve_registry_digest_from_response(
    client: httpx.AsyncClient,
    manifest_url: str,
    response: httpx.Response,
    headers: dict[str, str],
    platform: str | None,
) -> Optional[str]:
    digests = await _resolve_registry_digests_from_response(
        client, manifest_url, response, headers, platform
    )
    return digests.config_digest or (digests.repo_digests[-1] if digests.repo_digests else None)


async def _lookup_registry_identity(
    registry: str,
    repository: str,
    reference: str,
    platform: str | None = None,
) -> RegistryLookupResult:
    frozen_retry_after = _get_registry_retry_after(registry)
    if frozen_retry_after is not None:
        return RegistryLookupResult(
            digests=RegistryDigests(repo_digests=[]),
            error_status="rate_limited",
            http_status=429,
            retry_after=frozen_retry_after,
        )

    client = await _get_registry_client()
    manifest_url = f"https://{registry}/v2/{repository}/manifests/{reference}"
    headers = {"Accept": REGISTRY_ACCEPT}

    try:
        if registry == "docker.io":
            manifest_url = f"https://registry-1.docker.io/v2/{repository}/manifests/{reference}"
            token = _docker_token_cache_get(repository)
            if token is None:
                token_url = (
                    "https://auth.docker.io/token"
                    f"?service=registry.docker.io&scope=repository:{repository}:pull"
                )
                token_response = await client.get(token_url, timeout=10)
                token_error = _error_from_response("docker.io", token_response)
                if token_error is not None:
                    return token_error
                token_response.raise_for_status()
                token_payload = token_response.json()
                token = token_payload.get("token", "")
                if not token:
                    return RegistryLookupResult(
                        digests=RegistryDigests(repo_digests=[]),
                        error_status="check_failed",
                    )
                _docker_token_cache_set(
                    repository,
                    token,
                    int(token_payload.get("expires_in") or 300),
                )
            headers["Authorization"] = f"Bearer {token}"
        elif registry == "ghcr.io":
            manifest_url = f"https://ghcr.io/v2/{repository}/manifests/{reference}"

        response = await client.get(manifest_url, headers=headers, timeout=15)
        if registry == "ghcr.io" and response.status_code == 401:
            token, token_error = await _get_bearer_token_from_challenge(
                client,
                registry,
                response.headers.get("WWW-Authenticate", ""),
            )
            if token_error is not None:
                return token_error
            headers = {**headers, "Authorization": f"Bearer {token}"}
            response = await client.get(manifest_url, headers=headers, timeout=15)

        error = _error_from_response(registry, response)
        if error is not None:
            return error

        response.raise_for_status()
        digests = await _resolve_registry_digests_from_response(
            client, manifest_url, response, headers, platform
        )
        return RegistryLookupResult(digests=digests)
    except httpx.HTTPStatusError as exc:
        return _build_error_result(
            registry,
            exc.response.status_code,
            retry_after=_parse_retry_after(exc.response.headers.get("Retry-After")),
        )
    except Exception:
        return RegistryLookupResult(
            digests=RegistryDigests(repo_digests=[]),
            error_status="check_failed",
        )


async def _get_manifest_digest_candidates(
    registry: str, repository: str, tag: str, platform: str | None = None
) -> tuple[list[str], Optional[str]]:
    lookup = await _lookup_registry_identity(registry, repository, tag, platform)
    candidates = list(lookup.digests.repo_digests)
    _append_digest(candidates, lookup.digests.config_digest)
    return candidates, lookup.error_status


async def _get_manifest_digest(
    registry: str, repository: str, tag: str, platform: str | None = None
) -> tuple[Optional[str], Optional[str]]:
    """Query registry for the manifest digest.

    Returns (digest, error_status).
    digest is None on error; error_status is one of
    "needs_auth" | "check_failed" | "rate_limited".
    """
    candidates, error_status = await _get_manifest_digest_candidates(
        registry, repository, tag, platform
    )
    return (candidates[-1] if candidates else None), error_status


def _extract_local_digest(repo_digests: list[str]) -> Optional[str]:
    """Extract the local image digest from RepoDigests.

    Only RepoDigests provides a meaningful digest for comparison with registry.
    ImageID (content hash) must never be compared with registry manifest digest.
    Returns None if no valid RepoDigest is available — caller should mark unknown.
    """
    for d in repo_digests:
        if "@" in d:
            return _normalize_digest(d.split("@")[1])
    return None


def _local_repo_digests(repo_digests: list[str] | None) -> list[str]:
    candidates: list[str] = []
    for digest in repo_digests or []:
        if "@" in digest:
            _append_digest(candidates, digest.split("@", 1)[1])
    return candidates


async def check_image(
    host_id: str,
    image_ref: str,
    repo_digests: list[str] | None = None,
    local_image_id: str | None = None,
    platform: str | None = None,
    force: bool = False,
) -> UpdateCheckResult:
    """Check if a single image has an update available.

    Uses typed digest comparison:
    - RepoDigests are compared with remote manifest/index digests.
    - image inspect Id is compared only with remote config.digest.
    Digest-pinned refs (repo@sha256:...) are treated as immutable and do not
    trigger a registry lookup.

    Args:
        host_id: For identifying the source host.
        image_ref: Full image reference (e.g., "nginx:latest", "ghcr.io/org/repo:v1").
        repo_digests: List of RepoDigests from image inspect.

    Returns:
        UpdateCheckResult.
    """
    repo_digests = repo_digests or []
    parsed = _parse_image_ref(image_ref)
    local_image_id = _normalize_digest(local_image_id)
    local_repo_candidates = _local_repo_digests(repo_digests)

    if parsed["digest"]:
        pinned_digest = _normalize_digest(parsed["digest"])
        matched_pinned = pinned_digest if pinned_digest in local_repo_candidates else None
        return UpdateCheckResult(
            host_id=host_id,
            image=image_ref,
            current_digest=matched_pinned or (local_repo_candidates[0] if local_repo_candidates else local_image_id),
            registry_digest=pinned_digest,
            registry=parsed["registry"],
            platform=platform,
            matched_field="pinned_digest",
            status="up_to_date",
        )

    lookup = await _lookup_registry_identity(
        parsed["registry"],
        parsed["repository"],
        parsed["tag"],
        platform=platform,
    )

    matched_field: Optional[str] = None
    matched_local: Optional[str] = None
    matched_registry: Optional[str] = None

    if local_repo_candidates:
        matched_registry = next(
            (digest for digest in lookup.digests.repo_digests if digest in local_repo_candidates),
            None,
        )
        if matched_registry:
            matched_field = "repo_digest"
            matched_local = matched_registry

    if matched_field is None and local_image_id and lookup.digests.config_digest:
        if local_image_id == lookup.digests.config_digest:
            matched_field = "config_digest"
            matched_local = local_image_id
            matched_registry = lookup.digests.config_digest

    effective_local = (
        matched_local
        or (local_repo_candidates[0] if local_repo_candidates else local_image_id)
    )
    registry_digest = (
        matched_registry
        or (lookup.digests.repo_digests[0] if lookup.digests.repo_digests else lookup.digests.config_digest)
    )

    if lookup.error_status:
        status = lookup.error_status
        registry_digest = None
    elif registry_digest and effective_local:
        status = "up_to_date" if matched_field else "updatable"
    else:
        status = "check_failed"

    return UpdateCheckResult(
        host_id=host_id,
        image=image_ref,
        current_digest=effective_local,
        registry_digest=registry_digest,
        registry=parsed["registry"],
        platform=lookup.digests.resolved_platform or platform,
        http_status=lookup.http_status,
        matched_field=matched_field,
        retry_after=lookup.retry_after,
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
            last_result: UpdateCheckResult | None = None
            for delay in FAILURE_RETRY_DELAYS:
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
    """Deprecated compatibility hook for callers expecting a clear step."""
    _docker_token_cache.clear()
    _registry_frozen_until.clear()


def reset_runtime_state() -> None:
    """Test helper: reset transient registry lookup state."""
    global _registry_client
    _registry_client = None
    clear_cache()
