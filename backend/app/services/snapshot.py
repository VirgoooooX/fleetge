"""Snapshot aggregation and caching — the central data fusion layer.

Polls host structure at a low background cadence and refreshes metrics
only while a frontend SSE stream is connected.

Cache tiers:
  - Metrics: frontend-driven SSE
  - Containers/Stacks: 1h background, faster frontend-driven POST
  - Update checks (registry): 12h
"""

import asyncio
from collections.abc import Sequence
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlmodel import select

from app.config import get_settings
from app.database import engine, Session
from app.models import HostConfig, HostSubscription, ImageUpdateCache
from app.schemas import (
    ContainerStats,
    ContainerSummary,
    ContainerPort,
    DockerInfo,
    DockerDiskUsage,
    HostMetrics,
    HostSummary,
    StackSummary,
    UpdateCheckResult,
)
from app.services.agent_client import AgentClient
from app.services.host_summary import build_host_summary
from app.services.metrics_broadcaster import MetricsBroadcaster, metrics_payload
from app.services.stack_parser import (
    _match_icon, _match_profile, apply_app_profiles, merge_stacks_with_container_labels,
    parse_agent_stacks, stacks_from_container_labels,
)
from app.time_utils import as_utc as _as_utc, utc_now as _utc_now
from app.services.update_check import MANIFEST_MEDIA_TYPES, _extract_local_digest, _parse_platform, _platform_matches, run_update_check

logger = logging.getLogger(__name__)

VISIBLE_UPDATE_STATUSES = {"up_to_date", "updatable"}
FAILED_UPDATE_STATUSES = {"needs_auth", "check_failed", "rate_limited"}
FAILED_UPDATE_RECHECK_INTERVAL_SECONDS = 900
PENDING_UPDATE_STATUS = "pending_update"
PENDING_UPDATE_CONFIRM_INTERVAL_SECONDS = 3600
TRANSIENT_AGENT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
    httpx.NetworkError,
)


_STOP_STRUCTURE_RETRY_STATUSES = {401, 403, 429}


def _stop_structure_retry(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _STOP_STRUCTURE_RETRY_STATUSES


def _same_digest(left: str | None, right: str | None) -> bool:
    return (left or "").strip().lower() == (right or "").strip().lower()


@dataclass
class FinalizeSummary:
    """One per-image verdict produced by finalize_stack_update."""

    image: str
    cleared: bool
    verdict: str
    verified: bool = False


# Container states that block tag clearing: the stack has not converged to a
# stable, healthy state. ``starting`` is included because a healthcheck that
# has not yet turned ``healthy`` means we cannot confirm the new image runs.
_BLOCKING_CONTAINER_STATES = {"created", "exited", "dead", "restarting", "paused"}
_BLOCKING_HEALTH_STATUSES = {"starting", "unhealthy"}
_FINALIZE_WAIT_INTERVAL_SECONDS = 2.0


def _stack_convergence_block_reason(containers: list[ContainerSummary]) -> Optional[str]:
    """Return a human-readable reason if the stack has NOT converged, else None.

    A stack is considered converged when every container of the image is in a
    running state and either has no healthcheck or reports ``healthy``. Any
    Created/Exited/Restarting container, or a still-``starting``/``unhealthy``
    healthcheck, blocks clearing the update tag.
    """
    for c in containers:
        state = (c.state or "").lower()
        if state in _BLOCKING_CONTAINER_STATES:
            return f"container '{c.name}' is {state}"
        if state != "running":
            return f"container '{c.name}' state is '{state}'"

        health = c.health
        if isinstance(health, dict):
            health_status = (health.get("Status") or "").lower()
            if health_status in _BLOCKING_HEALTH_STATUSES:
                return f"container '{c.name}' health is {health_status}"
    return None


def _normalize_image_id(value: str | None) -> str:
    return (value or "").strip().lower()


def _container_image_identity_block_reason(
    containers: list[ContainerSummary],
) -> Optional[str]:
    """Return a reason if a running container is not using the current tag image.

    ``repo_digests`` are read from ``docker image inspect <tag>``. A successful
    pull updates that tag even if compose fails to recreate the container, so
    digest comparison alone can clear a tag incorrectly. ``image_id`` is the
    actual running container image, and ``tag_image_id`` is the current local
    tag target; both must match before finalize can clear.
    """
    for c in containers:
        container_image_id = _normalize_image_id(c.image_id)
        tag_image_id = _normalize_image_id(c.tag_image_id)
        if not container_image_id:
            return f"container '{c.name}' image id is unknown"
        if not tag_image_id:
            return f"current tag image id for '{c.image}' is unknown"
        if container_image_id != tag_image_id:
            return (
                f"container '{c.name}' still uses image {container_image_id[:19]} "
                f"while tag points to {tag_image_id[:19]}"
            )
    return None


class HostSnapshot:
    """Immutable snapshot of one host's data."""

    def __init__(self):
        self.host_config: Optional[HostConfig] = None
        self.status: str = "unknown"
        self.metrics: Optional[HostMetrics] = None
        self.metrics_updated: float = 0.0
        self.docker_info: Optional[DockerInfo] = None
        self.docker_disk: Optional[DockerDiskUsage] = None
        self.image_count: int = 0
        self.containers: list[ContainerSummary] = []
        self.containers_updated: float = 0.0
        self.stacks: list[StackSummary] = []
        self.stacks_updated: float = 0.0
        self.container_stats: dict[str, ContainerStats] = {}  # container_id -> stats
        self._running_image_metadata: dict[str, tuple] = {}
        self.stats_updated: float = 0.0
        self.error_message: str = ""
        # Update check results per image, keyed by image_ref
        self.update_results: dict[str, str] = {}  # image_ref -> status (up_to_date/updatable/...)
        self.update_check_results: list[UpdateCheckResult] = []
        self.update_count: int = 0
        self.subscription: Optional[HostSubscription] = None


class SnapshotManager:
    """Manages all host snapshots with tiered polling."""

    # Backoff schedule for unreachable hosts (seconds)
    _BACKOFF_SCHEDULE = (5, 15, 30, 60, 120)

    def __init__(self):
        self._snapshots: dict[str, HostSnapshot] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._stopping = False
        self._tasks: list[asyncio.Task] = []

        # Clients — lazily created
        self._agent_clients: dict[str, AgentClient] = {}
        self._host_refresh_locks: dict[str, asyncio.Lock] = {}
        self._metrics_refresh_lock = asyncio.Lock()
        self._metrics_broadcaster = MetricsBroadcaster(
            self._collect_metrics_summaries, lambda: float(get_settings().METRICS_STREAM_INTERVAL),
        )
        self._update_check_lock = asyncio.Lock()
        self._stats_tasks: dict[str, asyncio.Task] = {}
        self._update_check_tasks: dict[str, asyncio.Task] = {}
        self._pending_update_checks: dict[str, set[str]] = {}
        self._operation_refresh_tasks: dict[str | None, asyncio.Task] = {}
        self._realtime_refresh_tasks: dict[str, asyncio.Task] = {}  # coalesce WebSocket-triggered refreshes

        # Update-check gating. Plain bools are the right primitive here:
        # asyncio is single-threaded and only switches coroutines at await
        # points, so the check-then-set below has no scheduling gap. The common
        # running flag covers both manual and background sweeps, preventing any
        # caller from queuing behind _update_check_lock and then duplicating a
        # full registry pass.
        self._update_check_running: bool = False

        # Active connection tracking for polling optimization
        self._active_connections = 0
        self._connection_event = asyncio.Event()
        self._structure_leases: dict[str, float] = {}

        # Failure backoff: skip unreachable hosts so they don't slow the poll cycle
        self._consecutive_failures: dict[str, int] = {}
        self._backoff_until: dict[str, float] = {}

    def _finalize_block_reason_for_snapshot(
        self,
        snap: HostSnapshot,
        stack_name: str,
        target_images: list[str],
    ) -> Optional[str]:
        stack_containers = [
            c for c in snap.containers
            if c.stack_name == stack_name and c.image
        ]
        containers_by_image: dict[str, list[ContainerSummary]] = {}
        for c in stack_containers:
            containers_by_image.setdefault(c.image, []).append(c)

        for image in target_images:
            containers = containers_by_image.get(image, [])
            if not containers:
                return f"{image}: no container found in stack '{stack_name}'"
            identity_reason = _container_image_identity_block_reason(containers)
            if identity_reason:
                return f"{image}: {identity_reason}"
            convergence_reason = _stack_convergence_block_reason(containers)
            if convergence_reason:
                return f"{image}: {convergence_reason}"
        return None

    async def _wait_for_stack_update_convergence(
        self,
        host_id: str,
        stack_name: str,
        target_images: list[str],
        wait_timeout: float,
        wait_interval: float = _FINALIZE_WAIT_INTERVAL_SECONDS,
    ) -> None:
        if wait_timeout <= 0 or not target_images:
            return

        deadline = time.monotonic() + wait_timeout
        while True:
            snap = self._snapshots.get(host_id)
            if snap is not None:
                reason = self._finalize_block_reason_for_snapshot(
                    snap, stack_name, target_images
                )
                if reason is None:
                    return

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return

            await asyncio.sleep(min(wait_interval, remaining))
            try:
                await self.refresh_host_docker(
                    host_id,
                    trigger_initial_update_check=False,
                    force_status_on_timeout=False,
                )
            except Exception as exc:
                logger.debug(
                    "Finalize convergence refresh failed for %s/%s: %s",
                    host_id, stack_name, exc,
                )

    def increment_connections(self) -> None:
        self._active_connections += 1
        self._connection_event.set()
        logger.info("Active connections incremented: %d", self._active_connections)

    def decrement_connections(self) -> None:
        self._active_connections = max(0, self._active_connections - 1)
        logger.info("Active connections decremented: %d", self._active_connections)

    def register_structure_lease(self, interval: float) -> str:
        token = uuid.uuid4().hex
        self._structure_leases[token] = max(5.0, min(float(interval), 3600.0))
        self._connection_event.set()
        return token

    def unregister_structure_lease(self, token: str | None) -> None:
        if token:
            self._structure_leases.pop(token, None)
            self._connection_event.set()

    def _structure_interval(self, background_interval: float) -> float:
        candidates = list(self._structure_leases.values())
        if self._active_connections > 0:
            candidates.append(float(get_settings().DOCKER_POLL_INTERVAL))
        return min(candidates) if candidates else float(background_interval)

    def add_metrics_subscriber(self) -> asyncio.Queue:
        queue = self._metrics_broadcaster.subscribe()
        if self._running:
            self._metrics_broadcaster.start()
        return queue

    def remove_metrics_subscriber(self, queue: asyncio.Queue) -> None:
        self._metrics_broadcaster.unsubscribe(queue)

    def current_metrics_payload(self) -> dict:
        return metrics_payload([self.build_host_summary(snapshot) for snapshot in self.list_snapshots()])

    async def _collect_metrics_summaries(self) -> list[HostSummary]:
        await self.refresh_hosts()
        return await self.refresh_metrics_now()

    # ── Failure backoff ─────────────────────────────────────────────

    def _should_skip(self, host_id: str) -> bool:
        """Return True if this host should be skipped due to recent failures."""
        until = self._backoff_until.get(host_id)
        if until is None:
            return False
        if time.monotonic() < until:
            return True
        # Backoff expired — allow one probe
        self._backoff_until.pop(host_id, None)
        return False

    def _record_failure(self, host_id: str) -> None:
        n = self._consecutive_failures.get(host_id, 0) + 1
        self._consecutive_failures[host_id] = n
        idx = min(n - 1, len(self._BACKOFF_SCHEDULE) - 1)
        delay = self._BACKOFF_SCHEDULE[idx]
        self._backoff_until[host_id] = time.monotonic() + delay
        logger.info("host %s: %d consecutive failures, backoff %ds", host_id, n, delay)

    def _record_success(self, host_id: str) -> None:
        prev = self._consecutive_failures.pop(host_id, 0)
        self._backoff_until.pop(host_id, None)
        if prev > 0:
            logger.info("host %s: recovered after %d failures", host_id, prev)

    # ── Public ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the polling loops."""
        if self._running:
            return
        self._running = True
        self._stopping = False
        settings = get_settings()
        self._tasks = [
            asyncio.create_task(
                self._poll_loop(
                    "structure",
                    settings.BACKGROUND_STRUCTURE_REFRESH_INTERVAL,
                    self._refresh_docker,
                )
            ),
            asyncio.create_task(
                self._poll_loop(
                    "update_checks", settings.UPDATE_CHECK_INTERVAL, self._refresh_update_checks
                )
            ),
        ]
        self._metrics_broadcaster.start()
        logger.info(
            "SnapshotManager started with low-frequency structure polling; metrics are frontend-driven"
        )

    async def stop(self) -> None:
        self._stopping = True
        self._running = False
        tasks = [
            *self._tasks, *self._stats_tasks.values(), *self._update_check_tasks.values(),
            *self._realtime_refresh_tasks.values(), *self._operation_refresh_tasks.values(),
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        await self._metrics_broadcaster.stop(clear_subscribers=True)
        self._stats_tasks.clear()
        self._update_check_tasks.clear()
        self._pending_update_checks.clear()
        self._realtime_refresh_tasks.clear()
        self._operation_refresh_tasks.clear()
        clients = list(self._agent_clients.values())
        self._agent_clients.clear()
        for result in await asyncio.gather(*(client.close() for client in clients), return_exceptions=True):
            if isinstance(result, Exception):
                logger.warning("Could not close Agent client: %s", result)
        logger.info("SnapshotManager stopped")

    async def restart_poll_loops(self) -> None:
        """Restart background pollers with updated intervals."""
        from app.services.settings_service import clear_cache

        logger.info("Restarting poll loops...")
        self._running = False
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        # The poll loops can acquire the host lock, so drain them outside it.
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._metrics_broadcaster.stop()
        clear_cache()
        await self.refresh_hosts()
        await self.start()
        logger.info("Poll loops restarted successfully")

    def get_snapshot(self, host_id: str) -> Optional[HostSnapshot]:
        return self._snapshots.get(host_id)

    def list_snapshots(self) -> list[HostSnapshot]:
        return sorted(
            self._snapshots.values(),
            key=lambda s: (s.host_config.sort_order if s.host_config else 0, s.host_config.id if s.host_config else 0),
        )

    def get_update_check_results(self, *, include_failures: bool = False) -> list[UpdateCheckResult]:
        """Return cached update check results without hitting registries.

        When *include_failures* is True, failure statuses (needs_auth,
        check_failed, rate_limited) are included. This is intended for the
        dedicated updates / diagnostic page. The host/app views never pass
        this flag, so they remain unaffected.
        """
        allowed = VISIBLE_UPDATE_STATUSES | FAILED_UPDATE_STATUSES if include_failures else VISIBLE_UPDATE_STATUSES
        results: list[UpdateCheckResult] = []
        for snap in self._snapshots.values():
            results.extend(
                r for r in snap.update_check_results
                if r.status in allowed
            )
        return results

    def load_update_check_cache_from_db(self) -> None:
        """Hydrate in-memory snapshots from persistent image update cache."""
        with Session(engine) as session:
            rows = session.exec(select(ImageUpdateCache)).all()

        rows_by_host: dict[str, list[ImageUpdateCache]] = {}
        for row in rows:
            rows_by_host.setdefault(row.host_id, []).append(row)

        for host_id, snap in self._snapshots.items():
            self._apply_update_cache_rows_to_snapshot(
                snap,
                rows_by_host.get(host_id, []),
            )

    def _apply_update_cache_rows_to_snapshot(
        self,
        snap: HostSnapshot,
        rows: list[ImageUpdateCache],
        current_images: set[str] | None = None,
    ) -> None:
        """Apply persisted update-check rows to one snapshot.

        snap.update_check_results keeps the full per-image state so the
        dedicated updates page can show failures. snap.update_results remains
        a visible-status index for host/app surfaces that only care about
        actionable update badges.
        """
        scoped_rows = [
            row for row in rows
            if current_images is None or row.image in current_images
        ]
        visible_rows = [
            row for row in rows
            if row.status in VISIBLE_UPDATE_STATUSES
            and (current_images is None or row.image in current_images)
        ]
        snap.update_results.clear()

        def to_result(row: ImageUpdateCache) -> UpdateCheckResult:
            return UpdateCheckResult(
                host_id=row.host_id,
                image=row.image,
                current_digest=row.current_digest,
                registry_digest=row.registry_digest,
                registry_index_digest=row.registry_index_digest,
                registry_manifest_digest=row.registry_manifest_digest,
                registry_config_digest=row.registry_config_digest,
                identity_error=row.identity_error,
                registry=row.registry_name,
                platform=row.platform,
                http_status=row.http_status,
                matched_field=row.matched_field,
                retry_after=row.retry_after,
                failure_count=row.failure_count,
                last_failure_status=row.last_failure_status,
                last_failure_http_status=row.last_failure_http_status,
                last_failure_retry_after=row.last_failure_retry_after,
                last_failure_at=row.last_failure_at,
                status=row.status,
            )

        snap.update_check_results = [to_result(row) for row in scoped_rows]
        for row in visible_rows:
            result = to_result(row)
            snap.update_results[result.image] = result.status
        snap.update_count = sum(
            1 for row in visible_rows if row.status == "updatable"
        )
        self._enforce_runtime_update_status(snap)

    def _enforce_runtime_update_status(self, snap: HostSnapshot) -> None:
        """Keep a shared image tag actionable while any instance is still old."""
        results = {result.image: result for result in snap.update_check_results}
        for image, status in list(snap.update_results.items()):
            result = results.get(image)
            if result is None:
                continue
            containers = [container for container in snap.containers if container.image == image]
            if not containers:
                continue
            runtime_types = {
                "config" if container.image_config_digest else "manifest"
                for container in containers
            }
            cached_target = None
            if runtime_types == {"config"}:
                cached_target = result.registry_config_digest
            elif runtime_types == {"manifest"}:
                cached_target = result.registry_manifest_digest
            cache_type_changed = bool(cached_target and cached_target != result.registry_digest)
            # Keep an update badge until the post-update finalizer clears it,
            # except when the old check compared unlike digest types. In that
            # case, re-evaluate with the matching cached identity right away.
            if status == "updatable" and not cache_type_changed:
                continue

            comparisons: list[tuple[str, str, str]] = []
            legacy_matches: list[bool] = []
            identity_error = None
            for container in containers:
                if not container.inspection_complete or not (container.image_config_digest or container.image_manifest_digest):
                    identity_error = "Running image identity is unavailable; cannot determine whether an update is needed."
                    break
                if container.image_config_digest and result.registry_config_digest:
                    comparisons.append((container.image_config_digest, result.registry_config_digest, "config_digest"))
                elif container.image_manifest_digest and result.registry_manifest_digest and result.platform:
                    if not _platform_matches(
                        _parse_platform(container.platform), _parse_platform(result.platform), exact_variant=False,
                    ):
                        identity_error = "Running image platform does not match the cached registry target platform."
                        break
                    comparisons.append((container.image_manifest_digest, result.registry_manifest_digest, "manifest_digest"))
                elif not result.registry_config_digest and not result.registry_manifest_digest and result.registry_digest:
                    target = _normalize_image_id(result.registry_digest)
                    candidates = {
                        _normalize_image_id(container.image_config_digest),
                        _normalize_image_id(container.image_manifest_digest),
                        *(_normalize_image_id(d.split("@", 1)[-1]) for d in (container.repo_digests or [])),
                    }
                    legacy_matches.append(target in candidates)
                    local = container.image_config_digest or container.image_manifest_digest or result.current_digest or ""
                    comparisons.append((local, result.registry_digest, "registry_digest"))
                else:
                    identity_error = "Registry identity of the matching type is unavailable; update status cannot be confirmed."
                    break

            if identity_error:
                snap.update_results.pop(image, None)
                result.status = "check_failed"
                result.identity_error = identity_error
                continue

            all_match = all(
                _normalize_image_id(local) == _normalize_image_id(target)
                for local, target, field in comparisons
                if field != "registry_digest"
            ) and all(legacy_matches)
            result.status = "up_to_date" if all_match else "updatable"
            result.current_digest = comparisons[0][0]
            result.registry_digest = comparisons[0][1]
            result.matched_field = comparisons[0][2] if all_match else None
            result.identity_error = None
            snap.update_results[image] = result.status
        snap.update_count = sum(1 for status in snap.update_results.values() if status == "updatable")


    def persist_update_check_results(
        self,
        host_id: str,
        results: list[UpdateCheckResult],
    ) -> None:
        """Persist fresh update-check results and immediately update the snapshot cache."""
        if not results:
            return

        now = _utc_now()
        with Session(engine) as session:
            rows = session.exec(
                select(ImageUpdateCache).where(ImageUpdateCache.host_id == host_id)
            ).all()
            rows_by_image = {row.image: row for row in rows}
            for result in results:
                self._persist_update_check_result(
                    session,
                    host_id,
                    result,
                    rows_by_image.get(result.image),
                    now,
                )
            session.commit()
            rows = session.exec(
                select(ImageUpdateCache).where(ImageUpdateCache.host_id == host_id)
            ).all()

        snap = self._snapshots.get(host_id)
        if snap is not None:
            current_images = {c.image for c in snap.containers if c.image}
            self._apply_update_cache_rows_to_snapshot(snap, rows, current_images)

    async def finalize_stack_update(
        self,
        host_id: str,
        stack_name: str,
        target_images: list[str],
        wait_timeout: float = 0.0,
        wait_interval: float = _FINALIZE_WAIT_INTERVAL_SECONDS,
    ) -> list[FinalizeSummary]:
        """Authoritative post-update tag clearing + per-image verdict.

        Runs *after* a successful ``docker compose up``. For each image that
        was marked ``updatable`` before the update, decide whether the update
        actually landed and produce a terminal-ready verdict line. The tag is
        cleared only when the evidence is conclusive; otherwise it is left in
        place with a human-readable reason.

        Decision matrix per image::

            healthy/running + local == cached registry_digest
                -> clear tag, "up to date (digest matched)"
            healthy/running + local != cached
                -> keep, await the next scheduled registry check
            stack not converged (created/exited/restarting/unhealthy/starting)
                -> keep, "waiting for health" or the blocking state
            local digest missing
                -> keep, "cannot determine local digest"
            image not running in this stack
                -> keep, "not found in running stack"

        Note: digest match and health are evaluated independently. A matching
        digest means "the image bytes updated"; health means "the new
        container is well". We require *both* to clear, because clearing on a
        digest match alone would hide a container that updated its image but
        fails to start (the exact failure mode behind the original bug).
        """
        ordered_targets = list(dict.fromkeys(target_images))
        await self._wait_for_stack_update_convergence(
            host_id, stack_name, ordered_targets, wait_timeout, wait_interval
        )

        snap = self._snapshots.get(host_id)
        summaries: list[FinalizeSummary] = []
        if snap is None:
            return summaries

        # Containers of this stack, keyed by image. Only running/transitioning
        # containers in THIS stack matter — other stacks sharing the image are
        # out of scope for this update's verdict.
        stack_containers = [
            c for c in snap.containers
            if c.stack_name == stack_name and c.image
        ]
        containers_by_image: dict[str, list[ContainerSummary]] = {}
        for c in stack_containers:
            containers_by_image.setdefault(c.image, []).append(c)

        with Session(engine) as session:
            rows = session.exec(
                select(ImageUpdateCache).where(
                    ImageUpdateCache.host_id == host_id,
                    ImageUpdateCache.image.in_(ordered_targets),  # type: ignore[attr-defined]
                )
            ).all()
            rows_by_image = {row.image: row for row in rows}

        for image in ordered_targets:
            row = rows_by_image.get(image)
            containers = containers_by_image.get(image, [])

            if not row or row.status not in {"updatable", "up_to_date"}:
                # Unknown/failed checks cannot prove an update. An up-to-date
                # cache row still needs running-image and health verification.
                status = row.status if row else "unknown"
                summaries.append(FinalizeSummary(
                    image=image,
                    cleared=False,
                    verdict=f"{image}: no updatable tag ({status})",
                ))
                continue

            if not containers:
                summaries.append(FinalizeSummary(
                    image=image,
                    cleared=False,
                    verdict=(
                        f"{image}: marked updatable from running container, "
                        f"but not found in running stack '{stack_name}' "
                        f"(compose/runtime drift)"
                    ),
                ))
                continue

            primary_container = containers[0]
            local_repo_digest = _extract_local_digest(primary_container.repo_digests)
            local_image_digest = _normalize_image_id(
                primary_container.tag_image_id or primary_container.image_id
            ) or None
            local_candidates = [
                digest for digest in (local_repo_digest, local_image_digest) if digest
            ]
            if not local_candidates:
                summaries.append(FinalizeSummary(
                    image=image,
                    cleared=False,
                    verdict=(
                        f"{image}: cannot determine local digest "
                        f"(image id and RepoDigests missing)"
                    ),
                ))
                continue

            identity_reason = _container_image_identity_block_reason(containers)
            if identity_reason:
                summaries.append(FinalizeSummary(
                    image=image,
                    cleared=False,
                    verdict=f"{image}: {identity_reason}",
                ))
                continue

            # Health convergence gate across every container of this image.
            block_reason = _stack_convergence_block_reason(containers)
            if block_reason:
                summaries.append(FinalizeSummary(
                    image=image,
                    cleared=False,
                    verdict=f"{image}: {block_reason}",
                ))
                continue

            cached_target = _normalize_image_id(row.registry_digest)
            if cached_target in local_candidates:
                self._clear_updatable_tag(host_id, image, local_candidates[0])
                summaries.append(FinalizeSummary(
                    image=image,
                    cleared=row.status == "updatable",
                    verified=True,
                    verdict=f"{image}: up to date (digest matched)",
                ))
                continue

            # Finalization never performs registry I/O. A moving tag is
            # reconciled by the next explicit or scheduled image check.
            cached_txt = cached_target or "unknown"
            local_txt = ",".join(candidate[:19] for candidate in local_candidates)
            summaries.append(FinalizeSummary(
                image=image,
                cleared=False,
                verdict=(
                    f"{image}: updated, but digest does not match target "
                    f"(local={local_txt} cached={cached_txt[:19]}); "
                    "awaiting the next scheduled image check"
                ),
            ))

        # Mirror the (possibly cleared) cache back into the snapshot so the UI
        # reflects the new tag state without waiting for the next poll.
        current_images = {c.image for c in snap.containers if c.image}
        with Session(engine) as session:
            rows = session.exec(
                select(ImageUpdateCache).where(ImageUpdateCache.host_id == host_id)
            ).all()
        self._apply_update_cache_rows_to_snapshot(snap, rows, current_images)
        return summaries

    async def verify_update_targets(
        self,
        host_id: str,
        stack_name: str,
        targets: dict[str, dict],
        *,
        not_before: float = 0.0,
        wait_timeout: float = 180.0,
        wait_interval: float = 2.0,
        require_cached_target: bool = True,
    ) -> tuple[str, str]:
        """Verify pulled image identity and health, plus the cached target for detected updates.

        This path only reads local Docker evidence; registry checks belong to
        the explicit/scheduled image-check workflow.
        """
        deadline = time.monotonic() + wait_timeout
        last_reason = "Updated container evidence is not available yet."
        uncertain_reason = ""
        while True:
            await self.refresh_host_docker(
                host_id,
                trigger_initial_update_check=False,
                force_status_on_timeout=False,
                lock_timeout=10.0,
                execution_timeout=20.0,
            )
            snap = self._snapshots.get(host_id)
            if snap is None or snap.status != "online" or snap.containers_updated <= not_before:
                uncertain_reason = "A fresh post-update container snapshot could not be confirmed."
            else:
                failure_reasons: list[str] = []
                pending_health = False
                missing_evidence: list[str] = []
                for service_name, target in targets.items():
                    expected_count = int(target.get("container_count") or 0)
                    service_containers = [
                        container for container in snap.containers
                        if container.stack_name == stack_name
                        and container.service_name == service_name
                        and (container.labels or {}).get("com.docker.compose.oneoff", "False").lower() != "true"
                    ]
                    if len(service_containers) < expected_count:
                        failure_reasons.append(
                            f"{service_name}: expected at least {expected_count} container(s), found {len(service_containers)}"
                        )
                        continue
                    for container in service_containers:
                        if not container.inspection_complete:
                            missing_evidence.append(f"{service_name}/{container.name}: inspect data is incomplete")
                            continue
                        if container.state != "running":
                            failure_reasons.append(f"{service_name}/{container.name}: state is {container.state}")
                            continue
                        target_image_id = _normalize_image_id(target.get("image_id"))
                        if not target_image_id:
                            missing_evidence.append(f"{service_name}: pulled image ID is missing")
                        elif _normalize_image_id(container.image_id) != target_image_id:
                            failure_reasons.append(
                                f"{service_name}/{container.name}: running image {container.image_id[:19]} "
                                f"does not match pulled image {target_image_id[:19]}"
                            )
                        target_platform = _parse_platform(target.get("platform"))
                        if not target_platform or not _parse_platform(container.platform):
                            missing_evidence.append(f"{service_name}/{container.name}: image platform is unavailable")
                        elif not _platform_matches(_parse_platform(container.platform), target_platform, exact_variant=False):
                            failure_reasons.append(f"{service_name}/{container.name}: platform does not match pulled target")
                        if container.healthcheck_configured:
                            health_status = (container.health or {}).get("Status", "").lower()
                            if not health_status:
                                missing_evidence.append(f"{service_name}/{container.name}: healthcheck state is unavailable")
                            elif health_status == "starting":
                                pending_health = True
                            elif health_status != "healthy":
                                failure_reasons.append(f"{service_name}/{container.name}: health is {health_status}")
                if not failure_reasons and not missing_evidence and not pending_health:
                    mismatched: list[str] = []
                    for service_name, target in targets.items():
                        if not require_cached_target:
                            continue
                        cached = target.get("cached_target") or {}
                        cached_platform = _parse_platform(cached.get("platform"))
                        for container in snap.containers:
                            if container.stack_name != stack_name or container.service_name != service_name:
                                continue
                            if (container.labels or {}).get("com.docker.compose.oneoff", "False").lower() == "true":
                                continue
                            local = expected = None
                            if container.image_config_digest and cached.get("registry_config_digest"):
                                local, expected = container.image_config_digest, cached["registry_config_digest"]
                            elif container.image_manifest_digest and cached.get("registry_manifest_digest"):
                                local, expected = container.image_manifest_digest, cached["registry_manifest_digest"]
                            if (not local or not expected or not cached_platform
                                    or not _platform_matches(_parse_platform(container.platform), cached_platform, exact_variant=False)
                                    or _normalize_image_id(local) != _normalize_image_id(expected)):
                                mismatched.append(service_name)
                    if mismatched:
                        return "uncertain", (
                            "服务已重建并通过本地镜像与健康检查，但镜像与缓存目标不同或缺少同类摘要："
                            + ", ".join(dict.fromkeys(mismatched)) + "。待下次定时检测确认。"
                        )
                    # Reconcile badges without changing the check time: the
                    # verified pull becomes the cached target so a tag that moved
                    # since the last registry check cannot re-mark the image.
                    images = {target.get("image") for target in targets.values()}
                    verified_targets = {
                        str(target.get("image")): target
                        for target in targets.values()
                        if target.get("image") and target.get("image_id")
                    }
                    with Session(engine) as session:
                        rows = session.exec(select(ImageUpdateCache).where(ImageUpdateCache.host_id == host_id)).all()
                        for row in rows:
                            if row.image in images and row.status in {"updatable", "up_to_date"}:
                                target = verified_targets.get(row.image)
                                if target:
                                    self._record_verified_target(row, target, snap.containers)
                                row.status = "up_to_date"
                        self._apply_update_cache_rows_to_snapshot(snap, rows, {c.image for c in snap.containers if c.image})
                        by_image = {result.image: result for result in snap.update_check_results}
                        for row in rows:
                            result = by_image.get(row.image)
                            if row.image in images and result and result.status in {"updatable", "up_to_date"}:
                                row.status = result.status
                                row.current_digest = result.current_digest
                                row.matched_field = result.matched_field
                                session.add(row)
                        session.commit()
                    return "success", (
                        "本地运行镜像与缓存目标一致，容器运行及健康检查通过。" if require_cached_target
                        else "本地运行镜像与本次拉取目标一致，容器运行及健康检查通过。"
                    )
                last_reason = "; ".join(failure_reasons + missing_evidence) or "Container healthchecks are still starting."
                uncertain_reason = "; ".join(missing_evidence)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if uncertain_reason:
                    return "uncertain", f"Update result could not be confirmed: {uncertain_reason}"
                return "failed", f"Update verification timed out: {last_reason}"
            await asyncio.sleep(min(wait_interval, remaining))

    def _record_verified_target(
        self, row: ImageUpdateCache, target: dict, containers: list[ContainerSummary],
    ) -> None:
        """Adopt the identity proven by a verified pull as the cached target.

        A pull is registry truth at update time, so a tag re-published after the
        last registry check must not keep the freshly updated image marked
        updatable. Only the digest type the running containers expose is
        recorded; the next registry check refreshes the remaining identities.
        """
        image_id = _normalize_image_id(target.get("image_id"))
        if not image_id:
            return
        running = [container for container in containers if container.image == row.image]
        if any(container.image_config_digest for container in running):
            row.registry_config_digest = image_id
            row.matched_field = "config_digest"
        elif any(container.image_manifest_digest for container in running):
            row.registry_manifest_digest = image_id
            row.matched_field = "manifest_digest"
        else:
            return
        row.registry_digest = image_id
        row.platform = target.get("platform") or row.platform
        row.identity_error = None

    def _clear_updatable_tag(
        self, host_id: str, image: str, local_digest: str
    ) -> None:
        now = _utc_now()
        with Session(engine) as session:
            row = session.exec(
                select(ImageUpdateCache).where(
                    ImageUpdateCache.host_id == host_id,
                    ImageUpdateCache.image == image,
                )
            ).first()
            if not row or row.status != "updatable":
                return
            row.status = "up_to_date"
            row.current_digest = local_digest
            row.failure_count = 0
            row.last_failure_status = None
            row.last_failure_http_status = None
            row.last_failure_retry_after = None
            row.last_failure_at = None
            row.updated_at = now
            session.add(row)
            session.commit()


    def _evaluate_local_digest_against_cache(
        self,
        containers: list[ContainerSummary],
        rows: list[ImageUpdateCache],
    ) -> dict[str, str]:
        """Read-only check: which images now have a local digest matching the
        cached registry target?

        This is intentionally a *query only* — it never writes to the DB. The
        result is consumed by the post-update finalize path, which decides
        whether to clear the ``updatable`` tag based on stack health and
        compose/runtime consistency. Performing this clear as a side-effect of
        a plain refresh was unsafe: it ran even when the update had failed, as
        long as the image had already been pulled.
        """
        matched: dict[str, str] = {}
        rows_by_image = {row.image: row for row in rows}
        for container in containers:
            if not container.image:
                continue
            row = rows_by_image.get(container.image)
            if not row or row.status != "updatable" or not row.registry_digest:
                continue
            local_digest = _extract_local_digest(container.repo_digests)
            if local_digest and local_digest == row.registry_digest:
                matched[container.image] = local_digest
        return matched

    async def refresh_update_checks_now(self) -> list[UpdateCheckResult]:
        """Run update checks immediately and return the refreshed cache.

        Prefer try_refresh_update_checks_now() from request handlers so callers
        can tell whether this trigger actually started or was coalesced.
        """
        await self._refresh_update_checks(force=True)
        return self.get_update_check_results()

    def is_update_check_running(self) -> bool:
        return self._update_check_running

    async def try_refresh_update_checks_now(
        self,
        *,
        include_failures: bool = False,
    ) -> tuple[bool, list[UpdateCheckResult]]:
        """Run a manual force=True update check, unless one is already running.

        Returns (started, results):
          - started=True, results=<fresh>  : this call ran the sweep.
          - started=False, results=<cache> : another sweep is already in flight;
            the caller should surface cached results rather than wait or trigger
            another full registry pass.

        The common running flag is set without an await in between, so under the
        single-threaded asyncio loop the check-then-set cannot be preempted.
        """
        started = await self._refresh_update_checks(force=True)
        return started, self.get_update_check_results(include_failures=include_failures)

    async def refresh_metrics_now(self) -> list[HostSummary]:
        """Refresh host metrics immediately and return current host summaries."""
        await self._refresh_metrics()
        return [self.build_host_summary(s) for s in self.list_snapshots()]

    async def refresh_all_structure_now(self) -> list[HostSummary]:
        """Refresh Docker/Agent structure for all hosts and return summaries."""
        await self.refresh_hosts()
        await self._refresh_docker()
        return [self.build_host_summary(s) for s in self.list_snapshots()]

    def schedule_host_structure_refresh(self, host_id: str) -> None:
        self._schedule_operation_refresh(host_id)

    def schedule_all_structure_refresh(self) -> None:
        self._schedule_operation_refresh(None)

    def _schedule_operation_refresh(self, host_id: str | None) -> None:
        if self._stopping or host_id in self._operation_refresh_tasks:
            return
        refresh = self.refresh_all_structure_now() if host_id is None else self.refresh_host_docker_with_retry(host_id)
        task = asyncio.create_task(refresh, name=f"fleetge-structure-refresh:{host_id or 'all'}")
        self._operation_refresh_tasks[host_id] = task

        def done(finished: asyncio.Task) -> None:
            if self._operation_refresh_tasks.get(host_id) is finished:
                self._operation_refresh_tasks.pop(host_id)
            if not finished.cancelled() and (error := finished.exception()) is not None:
                logger.warning("Scheduled structure refresh for %s failed: %s", host_id or "all hosts", error)

        task.add_done_callback(done)

    async def refresh_host_structure_now(self, host_id: str) -> Optional[HostSnapshot]:
        """Refresh Docker/Agent structure for one host and return its snapshot."""
        await self.refresh_hosts()
        await self.refresh_host_docker(host_id)
        return self.get_snapshot(host_id)

    async def refresh_hosts(self) -> None:
        """(Re)load host configurations from database into snapshots.

        Call this after any host config change.
        """
        with Session(engine) as session:
            hosts = session.exec(select(HostConfig).where(HostConfig.enabled.is_(True))).all()
            subscriptions = {s.host_id: s for s in session.exec(select(HostSubscription)).all()}

        stale_clients = []
        cancelled_tasks = []
        async with self._lock:
            # Remove hosts no longer configured
            configured_ids = {h.host_id for h in hosts}
            for hid in list(self._snapshots.keys()):
                if hid not in configured_ids:
                    del self._snapshots[hid]
                    if (client := self._agent_clients.pop(hid, None)) is not None:
                        stale_clients.append(client)
                    self._host_refresh_locks.pop(hid, None)
                    self._pending_update_checks.pop(hid, None)
                    for tasks in (self._stats_tasks, self._update_check_tasks, self._realtime_refresh_tasks, self._operation_refresh_tasks):
                        if (task := tasks.pop(hid, None)) is not None:
                            task.cancel()
                            cancelled_tasks.append(task)

            # Add/update snapshots
            for h in hosts:
                if h.host_id not in self._snapshots:
                    snap = HostSnapshot()
                    snap.host_config = h
                    snap.subscription = subscriptions.get(h.host_id)
                    self._snapshots[h.host_id] = snap
                else:
                    snap = self._snapshots[h.host_id]
                    previous = snap.host_config
                    connection_changed = bool(
                        previous
                        and (
                            previous.agent_url != h.agent_url
                            or previous.agent_token_encrypted != h.agent_token_encrypted
                        )
                    )
                    snap.host_config = h
                    snap.subscription = subscriptions.get(h.host_id)
                    if connection_changed:
                        stale_client = self._agent_clients.pop(h.host_id, None)
                        if stale_client is not None:
                            stale_clients.append(stale_client)

        await asyncio.gather(*cancelled_tasks, return_exceptions=True)
        for result in await asyncio.gather(*(client.close() for client in stale_clients), return_exceptions=True):
            if isinstance(result, Exception):
                logger.warning("Could not close stale Agent client: %s", result)

    # ── Poll helpers ───────────────────────────────────────────────

    def _schedule_update_checks(self, host_id: str, snap: HostSnapshot, images: set[str]) -> None:
        """Run registry checks off the structure refresh path.

        A single registry lookup costs several seconds over a WAN link, so
        awaiting them here pushed an otherwise healthy refresh past its timeout.
        """
        if not images:
            return
        self._pending_update_checks.setdefault(host_id, set()).update(images)
        task = self._update_check_tasks.get(host_id)
        if task is not None and not task.done():
            return
        self._update_check_tasks[host_id] = asyncio.create_task(
            self._run_pending_update_checks(host_id, snap)
        )

    async def _run_pending_update_checks(self, host_id: str, snap: HostSnapshot) -> None:
        try:
            while True:
                images = self._pending_update_checks.get(host_id) or set()
                if not images:
                    break
                self._pending_update_checks[host_id] = set()
                try:
                    await self._refresh_update_checks_for_snapshot(snap, refresh_images=images)
                except Exception as exc:
                    logger.warning("Update check failed for %s: %s", host_id, exc)
        finally:
            self._update_check_tasks.pop(host_id, None)
            self._pending_update_checks.pop(host_id, None)

    async def _poll_loop(self, name: str, interval: int, fn) -> None:
        """Generic async poll loop."""
        while self._running:
            try:
                await self.refresh_hosts()
                await fn()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Poll loop %s error: %s", name, exc, exc_info=True)

            if name == "structure":
                try:
                    # Active connections: fast poll at DOCKER_POLL_INTERVAL.
                    # Idle: wait for a connection event or BACKGROUND_STRUCTURE_REFRESH_INTERVAL.
                    timeout = self._structure_interval(float(interval))
                    self._connection_event.clear()
                    try:
                        await asyncio.wait_for(self._connection_event.wait(), timeout=timeout)
                        logger.debug("Wake up structure poll loop due to lease change")
                    except asyncio.TimeoutError:
                        pass
                except asyncio.CancelledError:
                    break
            else:
                try:
                    if name == "update_checks":
                        await asyncio.sleep(self._next_update_check_interval(interval))
                    else:
                        await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    break

    async def _refresh_metrics(self) -> None:
        """Poll all hosts for current metrics via the Agent."""
        async with self._metrics_refresh_lock:
            async def refresh_one(snap: HostSnapshot) -> None:
                if not snap.host_config:
                    return
                cfg = snap.host_config
                if self._should_skip(cfg.host_id):
                    return
                if not cfg.agent_url:
                    return
                try:
                    if cfg.host_id not in self._agent_clients:
                        self._agent_clients[cfg.host_id] = AgentClient(cfg)
                    agent = self._agent_clients[cfg.host_id]
                    metrics = await agent.fetch_metrics()
                    snap.metrics = metrics
                    snap.metrics_updated = time.monotonic()
                    self._record_success(cfg.host_id)
                except Exception:
                    self._record_failure(cfg.host_id)
                    raise

            results = await asyncio.gather(
                *(refresh_one(snap) for snap in list(self._snapshots.values())),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.debug("Metrics poll task failed: %s", result)

    async def refresh_host_docker(
        self,
        host_id: str,
        trigger_initial_update_check: bool = True,
        force_status_on_timeout: bool = True,
        lock_timeout: float = 10.0,
        execution_timeout: float = 15.0,
    ) -> int | None:
        """Poll the Agent for a specific host immediately."""
        if self._should_skip(host_id):
            return
        lock = self._host_refresh_locks.setdefault(host_id, asyncio.Lock())
        snap = self._snapshots.get(host_id)

        try:
            await asyncio.wait_for(lock.acquire(), timeout=lock_timeout)
        except asyncio.TimeoutError:
            log = logger.warning if force_status_on_timeout else logger.debug
            log("Host %s refresh lock contention timeout", host_id)
            if force_status_on_timeout and snap:
                snap.status = "degraded"
                snap.error_message = "refresh lock contention timeout"
            return

        try:
            return await asyncio.wait_for(
                self._refresh_host_docker_locked(
                    host_id,
                    trigger_initial_update_check=trigger_initial_update_check,
                ),
                timeout=execution_timeout,
            )
        except asyncio.TimeoutError:
            log = logger.warning if force_status_on_timeout else logger.debug
            log("Host %s refresh execution timeout", host_id)
            if force_status_on_timeout and snap:
                snap.status = "degraded"
                snap.error_message = "refresh execution timeout"
        finally:
            lock.release()
        return None

    async def _refresh_host_docker_locked(
        self, host_id: str, trigger_initial_update_check: bool = True
    ) -> int | None:
        """Poll agent for a specific host immediately."""
        snap = self._snapshots.get(host_id)
        if not snap or not snap.host_config:
            return
        cfg = snap.host_config
        previous_images = {
            (container.id, container.image, container.image_id)
            for container in snap.containers
        }
        previous_snapshot_containers = {
            container.id: container for container in snap.containers
        }
        previous_container_completeness = {
            container.id: container.inspection_complete for container in snap.containers
        }
        if not cfg.agent_url:
            logger.warning("Host %s has no agent_url configured", host_id)
            return

        if cfg.host_id not in self._agent_clients:
            self._agent_clients[cfg.host_id] = AgentClient(cfg)
        proxy = self._agent_clients[cfg.host_id]

        try:
            try:
                structure = await proxy.fetch_snapshot()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (404, 405, 501):
                    raise
                structure = None

            failures = {}
            stop_retry_status = None
            if structure is not None:
                failures = dict(structure.get("errors") or {})
            else:
                structure_parts = {
                    "version": await proxy.version(),
                }
                for key, fetch in (
                    ("info", proxy.info), ("images", proxy.list_images),
                    ("containers", lambda: proxy.list_containers(all=True)), ("df", proxy.disk_usage),
                ):
                    try:
                        structure_parts[key] = await fetch()
                    except (httpx.HTTPError, ValueError) as exc:
                        failures[key] = str(exc)
                        if _stop_structure_retry(exc):
                            stop_retry_status = exc.response.status_code
                            break
            parts = structure if structure is not None else structure_parts

            def read_part(key: str, expected: type):
                value = parts.get(key)
                if key in failures or not isinstance(value, expected):
                    return None
                return value

            ver = read_part("version", dict)
            info = read_part("info", dict)
            raw_images = read_part("images", list)
            raw_containers = read_part("containers", list)
            df = read_part("df", dict)
            inspect_by_id = read_part("container_details", dict)

            # Merge independent successes before touching the container inventory.
            values = {}
            if ver is not None:
                values.update(version=ver.get("Version"), api_version=ver.get("ApiVersion"))
            if info is not None:
                values.update(
                    os=info.get("OSType"), architecture=info.get("Architecture"),
                    docker_root_dir=info.get("DockerRootDir"), server_version=info.get("ServerVersion"),
                    kernel_version=info.get("KernelVersion"), operating_system=info.get("OperatingSystem"),
                    n_cpus=info.get("NCPU"), memory_total=info.get("MemTotal"), name=info.get("Name"),
                )
            if values:
                snap.docker_info = (snap.docker_info or DockerInfo()).model_copy(update=values)

            # Disk usage (non-fatal, since /system/df can be slow/deadlocked on Windows/WSL2)
            if df is not None:
                snap.docker_disk = DockerDiskUsage(
                    images_total=len(df.get("Images", [])),
                    images_size=sum(
                        i.get("Size", 0) for i in df.get("Images", [])
                    ),
                    containers_total=len(df.get("Containers", [])),
                    containers_size=sum(
                        c.get("SizeRw", 0) for c in df.get("Containers", [])
                    ),
                    volumes_total=len(df.get("Volumes", [])),
                    volumes_size=sum(
                        v.get("UsageData", {}).get("Size", 0)
                        for v in df.get("Volumes", [])
                    ),
                    build_cache_total=len(df.get("BuildCache", [])),
                    build_cache_size=sum(
                        b.get("Size", 0) for b in df.get("BuildCache", [])
                    ),
                )
            # /system/df can include extra disk-accounting entries. /images/json
            # matches the visible local image list more closely.
            if raw_images is not None:
                snap.image_count = len(raw_images)

            if raw_containers is None:
                self._record_failure(cfg.host_id)
                snap.status = "degraded"
                snap.error_message = failures.get("containers", "Agent did not return a container inventory.")
                return stop_retry_status

            if inspect_by_id is None:
                inspect_semaphore = asyncio.Semaphore(8)

                async def inspect_container(container_id: str) -> tuple[str, dict]:
                    async with inspect_semaphore:
                        return container_id, await proxy.container_inspect(container_id)

                inspect_results = await asyncio.gather(
                    *(inspect_container(c.get("Id", "")) for c in raw_containers if c.get("Id")),
                    return_exceptions=True,
                )
                inspect_by_id = {}
                for result in inspect_results:
                    if isinstance(result, Exception):
                        logger.debug("Container inspect failed for %s: %s", cfg.host_id, result)
                        continue
                    container_id, detail = result
                    inspect_by_id[container_id] = detail

            containerd_store = any(
                key == "driver-type" and "containerd" in value
                for key, value in ((info or {}).get("DriverStatus") or [])
            )
            # Container list
            containers = []
            for c in raw_containers:
                inspect = inspect_by_id.get(c.get("Id", ""), {})
                host_config = inspect.get("HostConfig", {}) or {}
                config = inspect.get("Config", {}) or {}
                state_detail = inspect.get("State", {}) or {}
                network_settings = inspect.get("NetworkSettings", {}) or {}
                networks = network_settings.get("Networks", {}) or {}
                ports = [
                    ContainerPort(
                        private_port=p.get("PrivatePort"),
                        public_port=p.get("PublicPort"),
                        ip=p.get("IP"),
                        type=p.get("Type", "tcp"),
                    )
                    for p in (c.get("Ports") or [])
                ]
                # Extract stack/service from compose labels
                labels = c.get("Labels", {}) or {}
                stack_name = (
                    labels.get("com.docker.compose.project")
                )
                service_name = labels.get("com.docker.compose.service")

                names = c.get("Names") or []
                container_name = (
                    names[0].lstrip("/")
                    if isinstance(names, list) and names
                    else c.get("Name", "").lstrip("/")
                )

                runtime_descriptor = inspect.get("ImageManifestDescriptor") or c.get("ImageManifestDescriptor") or {}
                runtime_platform = runtime_descriptor.get("platform") or {}
                containers.append(
                    ContainerSummary(
                        id=c.get("Id", "")[:12],
                        name=container_name,
                        # Docker's list API can replace an untagged running
                        # image reference with its SHA after a newer pull.
                        # Config.Image retains the reference used to create it.
                        image=config.get("Image") or c.get("Image", ""),
                        image_id=c.get("ImageID", ""),
                        image_manifest_digest=(runtime_descriptor.get("digest") if runtime_descriptor.get("mediaType") in MANIFEST_MEDIA_TYPES else None),
                        state=c.get("State", "unknown"),
                        status=c.get("Status", ""),
                        created=c.get("Created", 0),
                        ports=ports,
                        labels=labels,
                        stack_name=stack_name,
                        service_name=service_name,
                        restart_count=inspect.get("RestartCount"),
                        driver=inspect.get("Driver"),
                        platform="/".join(runtime_platform[key] for key in ("os", "architecture", "variant") if runtime_platform.get(key)) or inspect.get("Platform"),
                        hostname=config.get("Hostname"),
                        domainname=config.get("Domainname"),
                        user=config.get("User"),
                        working_dir=config.get("WorkingDir"),
                        entrypoint=config.get("Entrypoint"),
                        command=config.get("Cmd"),
                        restart_policy=host_config.get("RestartPolicy"),
                        network_mode=host_config.get("NetworkMode"),
                        privileged=host_config.get("Privileged"),
                        mounts=inspect.get("Mounts", []) or [],
                        networks=networks,
                        health=state_detail.get("Health"),
                        healthcheck_configured=bool(config.get("Healthcheck")),
                        inspection_complete=bool(inspect) and bool(config) and bool(state_detail),
                    )
                )

            # Resolve the new container's image metadata without repeatedly
            # inspecting unchanged running IDs. Tag targets are refreshed every
            # round because an external docker pull does not change containers.
            running_image_ids = list({c.image_id for c in containers if c.image_id})
            unique_images = list({c.image for c in containers if c.image})

            def image_metadata(info: dict) -> tuple[list[str], str, str, dict]:
                digests = info.get("RepoDigests", []) or []
                image_id = info.get("Id", "") or ""
                platform_parts = (info.get("Os", ""), info.get("Architecture", ""), info.get("Variant", ""))
                platform_value = "/".join(part for part in platform_parts if part)
                return digests, image_id, platform_value, info.get("Descriptor") or {}

            if structure is not None:
                try:
                    evidence = await proxy.fetch_image_evidence(
                        [
                            image_id for image_id in running_image_ids
                            if image_id not in getattr(snap, "_running_image_metadata", {})
                        ],
                        unique_images,
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    logger.debug("Image evidence fetch failed for %s: %s", cfg.host_id, exc)
                    evidence = {"running": {}, "tags": {}}
                    if _stop_structure_retry(exc):
                        stop_retry_status = exc.response.status_code
                evidence = evidence if isinstance(evidence, dict) else {}
                evidence_running = evidence.get("running") or {}
                evidence_tags = evidence.get("tags") or {}
                running_metadata = dict(getattr(snap, "_running_image_metadata", {}))
                for image_id, info in evidence_running.items():
                    running_metadata[image_id] = image_metadata(info)
                for image_id in list(running_metadata):
                    if (
                        image_id not in evidence_running
                        and any(
                            c.image_id == image_id
                            and not (
                                (previous := previous_snapshot_containers.get(c.id)) is not None
                                and c.image == previous.image and previous.inspection_complete
                            )
                            for c in containers
                        )
                    ):
                        del running_metadata[image_id]
                snap._running_image_metadata = running_metadata
                tag_metadata = {ref: image_metadata(info) for ref, info in evidence_tags.items()}
            else:
                running_metadata = {}
                tag_metadata = {}
                image_semaphore = asyncio.Semaphore(8)

                async def inspect_image(image_ref: str) -> tuple[str, dict]:
                    async with image_semaphore:
                        return image_ref, await proxy.image_inspect(image_ref)

                running_results = await asyncio.gather(
                    *(inspect_image(image_id) for image_id in running_image_ids),
                    return_exceptions=True,
                )
                tag_results = await asyncio.gather(
                    *(inspect_image(image_ref) for image_ref in unique_images),
                    return_exceptions=True,
                )
                for image_id, result in zip(running_image_ids, running_results):
                    if not isinstance(result, Exception):
                        _, info = result
                        running_metadata[image_id] = image_metadata(info)
                for image_ref, result in zip(unique_images, tag_results):
                    if not isinstance(result, Exception):
                        _, info = result
                        tag_metadata[image_ref] = image_metadata(info)

            for container in containers:
                previous = previous_snapshot_containers.get(container.id)
                if (
                    structure is not None and previous is not None
                    and previous_container_completeness.get(container.id, False)
                    and container.image_id == previous.image_id and container.image == previous.image
                ):
                    container.repo_digests = previous.repo_digests
                    container.image_config_digest = previous.image_config_digest
                    container.image_manifest_digest = container.image_manifest_digest or previous.image_manifest_digest
                    container.platform = container.platform or previous.platform
                    container.inspection_complete = previous.inspection_complete
                running = running_metadata.get(container.image_id)
                tag = tag_metadata.get(container.image)
                if running:
                    container.repo_digests = running[0]
                    descriptor = running[3]
                    if not containerd_store and not descriptor and not container.image_manifest_digest:
                        container.image_config_digest = running[1] or None
                    elif (not container.image_manifest_digest
                          and descriptor.get("mediaType") in MANIFEST_MEDIA_TYPES
                          and _normalize_image_id(descriptor.get("digest")) == _normalize_image_id(container.image_id)):
                        container.image_manifest_digest = descriptor.get("digest")
                    if not _parse_platform(container.platform).get("architecture"):
                        container.platform = running[2] or container.platform
                else:
                    container.inspection_complete = False
                if tag:
                    container.tag_image_id = tag[1] or None
                    container.tag_platform = tag[2] or None

            snap.containers = containers
            snap.containers_updated = time.monotonic()

            # Stacks from Agent. The aggregate snapshot already includes the
            # stack names; service states are derived from the container labels.
            if structure is not None:
                stack_names = read_part("stack_names", list)
                if stack_names is None:
                    # Containers can still provide service state for known stacks.
                    snap.stacks = self._merge_stacks_with_container_labels(snap.stacks, snap)
                else:
                    self._build_stacks_from_container_labels(snap)
                    existing = {stack.name for stack in snap.stacks}
                    snap.stacks.extend(
                        StackSummary(name=name, status="stopped", management_status="file-only")
                        for name in stack_names if name not in existing
                    )
                    snap.stacks = apply_app_profiles(snap.stacks, cfg)
            else:
                await self._refresh_stacks(snap, cfg)

            # Read-only mirror of the persisted update cache into the snapshot.
            # Tag clearing (updatable -> up_to_date) is intentionally NOT done
            # here: a plain refresh can run after a failed update that still
            # pulled the image, and silently clearing the tag in that case is a
            # false "updated" signal. Clearing is the job of the post-update
            # finalize path (finalize_stack_update), which checks stack health
            # and compose/runtime consistency first.
            try:
                with Session(engine) as session:
                    rows = session.exec(
                        select(ImageUpdateCache).where(ImageUpdateCache.host_id == host_id)
                    ).all()

                current_images = {c.image for c in snap.containers if c.image}
                self._apply_update_cache_rows_to_snapshot(snap, rows, current_images)
            except Exception as cache_exc:
                logger.warning("Failed to verify/update image update cache for host %s: %s", host_id, cache_exc)

            missing = [name for name, value in (("version", ver), ("info", info), ("images", raw_images)) if value is None]
            snap.status = "degraded" if missing else "online"
            snap.error_message = f"Partial Agent snapshot: {', '.join(missing)} unavailable." if missing else ""

            # A recreated container can have a new running image while its tag's
            # registry cache is still within the normal check interval.
            changed_images = {
                container.image for container in snap.containers
                if (container.id, container.image, container.image_id) not in previous_images
                and container.image and container.inspection_complete
            }
            if trigger_initial_update_check and changed_images:
                self._schedule_update_checks(cfg.host_id, snap, changed_images)

            # Container stats are useful but must not block stack refresh
            # or the host's online status. Collect them after the core
            # snapshot is visible.
            existing_task = self._stats_tasks.get(cfg.host_id)
            if existing_task is None or existing_task.done():
                task = asyncio.create_task(self._refresh_container_stats(snap, proxy, cfg))
                self._stats_tasks[cfg.host_id] = task
                def remove_stats_task(finished: asyncio.Task) -> None:
                    if self._stats_tasks.get(cfg.host_id) is finished:
                        self._stats_tasks.pop(cfg.host_id)

                task.add_done_callback(remove_stats_task)

        except Exception as exc:
            if isinstance(exc, TRANSIENT_AGENT_ERRORS):
                logger.warning("Agent poll failed for %s: %s", cfg.host_id, exc)
            else:
                logger.warning(
                    "Agent poll failed for %s: %s", cfg.host_id, exc, exc_info=True
                )
            self._record_failure(cfg.host_id)
            snap.status = "degraded"
            snap.error_message = str(exc)
            if _stop_structure_retry(exc):
                return exc.response.status_code
        else:
            self._record_success(cfg.host_id)
            return stop_retry_status
        return None

    async def refresh_host_docker_with_retry(
        self, host_id: str, steps: Sequence[float] = (0.0, 2.0, 5.0, 8.0)
    ) -> None:
        """Refresh host Docker state multiple times with delays to capture transition states."""
        for i, delay in enumerate(steps):
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                status_code = await self.refresh_host_docker(
                    host_id,
                    lock_timeout=3.0,
                    execution_timeout=5.0,
                    force_status_on_timeout=False,
                )
                if status_code in _STOP_STRUCTURE_RETRY_STATUSES:
                    return
            except Exception as exc:
                if _stop_structure_retry(exc):
                    return
                logger.warning(
                    "Retry refresh failed for host %s (step %d): %s",
                    host_id, i, exc
                )

    async def _refresh_docker(
        self, trigger_initial_update_check: bool = True
    ) -> None:
        """Poll all Agent instances (info, containers, stats)."""
        semaphore = asyncio.Semaphore(4)

        async def refresh_one(snap: HostSnapshot) -> None:
            if not snap.host_config:
                return
            async with semaphore:
                await self.refresh_host_docker(
                    snap.host_config.host_id,
                    trigger_initial_update_check=trigger_initial_update_check,
                )

        results = await asyncio.gather(
            *(refresh_one(snap) for snap in list(self._snapshots.values())),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Docker poll task failed: %s", result)

    parse_agent_stacks = staticmethod(parse_agent_stacks)
    _match_profile = staticmethod(_match_profile)
    _match_icon = staticmethod(_match_icon)

    def update_host_stacks_realtime(self, host_id: str, raw_stacks: list) -> None:
        """Real-time update of host stacks when Agent pushes stackList event."""
        snap = self._snapshots.get(host_id)
        if not snap:
            return
        try:
            logger.info("Real-time stack list update received for %s", host_id)
            stacks = self.parse_agent_stacks(raw_stacks)
            stacks = apply_app_profiles(stacks, snap.host_config)
            snap.stacks = self._merge_stacks_with_container_labels(stacks, snap)
            snap.stacks_updated = time.monotonic()
            # Coalesce rapid stackList events: cancel previous pending refresh and
            # create a new one so only one realtime refresh is queued per host.
            prev_task = self._realtime_refresh_tasks.get(host_id)
            if prev_task and not prev_task.done():
                prev_task.cancel()
            task = asyncio.create_task(
                self.refresh_host_docker(host_id, force_status_on_timeout=False)
            )
            self._realtime_refresh_tasks[host_id] = task

            def cleanup(_t: asyncio.Task, hid: str = host_id) -> None:
                if self._realtime_refresh_tasks.get(hid) is _t:
                    self._realtime_refresh_tasks.pop(hid, None)

            task.add_done_callback(cleanup)
        except Exception as exc:
            logger.error("Failed to apply real-time stacks update for %s: %s", host_id, exc)

    async def _refresh_stacks(self, snap: HostSnapshot, cfg: HostConfig) -> None:
        """Fetch and merge Agent stacks with container states."""
        try:
            if not cfg.agent_url:
                raise ValueError("No agent_url configured")

            if cfg.host_id not in self._agent_clients:
                self._agent_clients[cfg.host_id] = AgentClient(cfg)
            conn = self._agent_clients[cfg.host_id]
            raw_stacks = await conn.list_stacks()

            async def enrich_services(stack: dict) -> dict:
                name = stack.get("name", stack.get("Name", ""))
                if not name:
                    return stack
                try:
                    rows = await conn.list_stack_services(name)
                except Exception as exc:
                    logger.debug("Service status fetch failed for %s/%s: %s", cfg.host_id, name, exc)
                    return stack

                services = []
                for row in rows:
                    service_name = row.get("Service") or row.get("Name") or row.get("service") or row.get("name")
                    state = row.get("State") or row.get("state") or "unknown"
                    services.append({
                        "name": service_name,
                        "containerId": row.get("ID") or row.get("Id") or row.get("id"),
                        "state": state,
                        "status": row.get("Status") or row.get("Health") or state,
                    })
                if services:
                    stack = dict(stack)
                    stack["services"] = services
                return stack

            raw_stacks = await asyncio.gather(
                *(enrich_services(stack) for stack in raw_stacks),
                return_exceptions=False,
            )

            stacks = self.parse_agent_stacks(raw_stacks)
            stacks = apply_app_profiles(stacks, cfg)
            snap.stacks = self._merge_stacks_with_container_labels(stacks, snap)
            snap.stacks_updated = time.monotonic()

        except Exception as exc:
            logger.warning("Agent refresh failed for %s: %s", cfg.host_id, exc)
            snap.stacks = self._merge_stacks_with_container_labels(snap.stacks, snap)

    def _merge_stacks_with_container_labels(
        self, agent_stacks: list[StackSummary], snap: HostSnapshot,
    ) -> list[StackSummary]:
        return apply_app_profiles(merge_stacks_with_container_labels(agent_stacks, snap.containers), snap.host_config)

    async def _refresh_container_stats(
        self, snap: HostSnapshot, proxy: AgentClient, cfg: HostConfig
    ) -> None:
        """Refresh running-container stats concurrently.

        Docker stats calls can be slow or hang per container. Running them
        serially delays the whole host snapshot, so cap concurrency and keep
        failures local to each container.
        """
        running_containers = [c for c in snap.containers if c.state == "running"]
        if not running_containers:
            snap.container_stats.clear()
            snap.stats_updated = time.monotonic()
            return

        semaphore = asyncio.Semaphore(6)

        async def fetch_one(container: ContainerSummary) -> tuple[str, ContainerStats | None]:
            async with semaphore:
                stats = await proxy.container_stats(container.id)
            if stats is None:
                return container.id, None
            try:
                cpu_delta = stats.get("cpu_stats", {}).get(
                    "cpu_usage", {}
                ).get("total_usage", 0) - stats.get("precpu_stats", {}).get(
                    "cpu_usage", {}
                ).get("total_usage", 0)
                system_delta = stats.get("cpu_stats", {}).get(
                    "system_cpu_usage", 0
                ) - stats.get("precpu_stats", {}).get("system_cpu_usage", 1)
                num_cpus = stats.get("cpu_stats", {}).get("online_cpus", 1)
                cpu_percent = 0.0
                if system_delta > 0 and cpu_delta > 0:
                    cpu_percent = round(
                        (cpu_delta / system_delta) * num_cpus * 100.0, 1
                    )

                mem = stats.get("memory_stats", {})
                net = stats.get("networks", {})
                blk = stats.get("blkio_stats", {})

                return container.id, ContainerStats(
                    cpu_percent=cpu_percent,
                    memory_usage=mem.get("usage", 0),
                    memory_limit=mem.get("limit", 0),
                    memory_percent=round(
                        (mem.get("usage", 0) / max(mem.get("limit", 1), 1)) * 100,
                        1,
                    ),
                    network_rx_bytes=sum(n.get("rx_bytes", 0) for n in net.values()),
                    network_tx_bytes=sum(n.get("tx_bytes", 0) for n in net.values()),
                    block_read_bytes=sum(
                        e.get("value", 0)
                        for e in blk.get("io_service_bytes_recursive", [])
                        if e.get("op") == "read"
                    ),
                    block_write_bytes=sum(
                        e.get("value", 0)
                        for e in blk.get("io_service_bytes_recursive", [])
                        if e.get("op") == "write"
                    ),
                )
            except Exception as exc:
                logger.debug(
                    "Stats parse error for %s/%s: %s", cfg.host_id, container.id, exc
                )
                return container.id, None

        results = await asyncio.gather(
            *(fetch_one(container) for container in running_containers),
            return_exceptions=True,
        )
        next_stats: dict[str, ContainerStats] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.debug("Stats fetch task failed for %s: %s", cfg.host_id, result)
                continue
            container_id, stats = result
            if stats is not None:
                next_stats[container_id] = stats

        snap.container_stats = next_stats
        snap.stats_updated = time.monotonic()

    def _build_stacks_from_container_labels(self, snap: HostSnapshot) -> None:
        """Build a read-only stack view from Docker Compose labels.

        This keeps the monitoring UI useful when the Agent is offline.
        Mutating stack operations still require a working Agent connection.
        """
        snap.stacks = stacks_from_container_labels(snap.containers)
        snap.stacks = apply_app_profiles(snap.stacks, snap.host_config)
        snap.stacks_updated = time.monotonic()

    # ── Update checks ─────────────────────────────────────────────

    async def _refresh_update_checks(self, force: bool = False) -> bool:
        """Query registry digests for all container images across all hosts.

        Runs every configured interval. Results are persisted in SQLite and
        hydrated into memory for fast API responses.

        If any sweep is already running, this call is skipped rather than queued
        behind _update_check_lock. That avoids duplicate registry passes for
        both "manual after background" and "background after manual" races.
        """
        if self._update_check_running:
            logger.debug(
                "Skipping %s update check: another sweep is in progress",
                "manual" if force else "background",
            )
            return False
        self._update_check_running = True
        try:
            async with self._update_check_lock:
                await self._refresh_update_checks_locked(force=force)
            return True
        finally:
            self._update_check_running = False

    async def _refresh_update_checks_locked(self, force: bool = False) -> None:
        """Update-check sweep body, expected to run under _update_check_lock."""
        await self.refresh_hosts()
        await self._refresh_docker(trigger_initial_update_check=False)
        semaphore = asyncio.Semaphore(3)

        async def refresh_one(snap: HostSnapshot) -> None:
            async with semaphore:
                fresh_images = await self._refresh_update_checks_for_snapshot(snap, force=force)
                if fresh_images:
                    from app.services.auto_update import auto_update_manager
                    auto_update_manager.enqueue(snap.host_config.host_id, fresh_images)

        results = await asyncio.gather(
            *(refresh_one(snap) for snap in list(self._snapshots.values())),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Update check task failed: %s", result)

    def _next_update_check_interval(self, interval: int) -> int:
        if any(
            getattr(result, "status", "") == PENDING_UPDATE_STATUS
            for snap in self._snapshots.values()
            for result in snap.update_check_results
        ):
            return min(interval, PENDING_UPDATE_CONFIRM_INTERVAL_SECONDS)
        if any(
            result.status in FAILED_UPDATE_STATUSES
            or result.last_failure_status in FAILED_UPDATE_STATUSES
            for snap in self._snapshots.values()
            for result in snap.update_check_results
        ):
            return min(interval, FAILED_UPDATE_RECHECK_INTERVAL_SECONDS)
        return interval

    def _is_update_cache_due(
        self,
        row: ImageUpdateCache | None,
        now: datetime,
        interval: timedelta,
        force: bool,
    ) -> bool:
        if force or row is None:
            return True
        pending_detected_at = _as_utc(row.pending_detected_at)
        if row.pending_registry_digest and pending_detected_at is not None:
            return (
                pending_detected_at
                + timedelta(seconds=PENDING_UPDATE_CONFIRM_INTERVAL_SECONDS)
                <= now
            )
        last_failure_at = _as_utc(row.last_failure_at)
        if row.last_failure_status in FAILED_UPDATE_STATUSES and last_failure_at is not None:
            retry_seconds = (
                row.last_failure_retry_after
                if row.last_failure_status == "rate_limited" and row.last_failure_retry_after
                else min(get_settings().UPDATE_CHECK_INTERVAL, FAILED_UPDATE_RECHECK_INTERVAL_SECONDS)
            )
            return last_failure_at + timedelta(seconds=retry_seconds) <= now
        if row.status in FAILED_UPDATE_STATUSES:
            checked_at = _as_utc(row.checked_at)
            if checked_at is None:
                return True
            retry_seconds = (
                row.retry_after
                if row.status == "rate_limited" and row.retry_after
                else min(get_settings().UPDATE_CHECK_INTERVAL, FAILED_UPDATE_RECHECK_INTERVAL_SECONDS)
            )
            retry_interval = timedelta(seconds=retry_seconds)
            return checked_at + retry_interval <= now
        checked_at = _as_utc(row.checked_at)
        if checked_at is None:
            return True
        return checked_at + interval <= now

    def _persist_update_check_result(
        self,
        session: Session,
        host_id: str,
        result: UpdateCheckResult,
        existing: ImageUpdateCache | None,
        now: datetime,
    ) -> ImageUpdateCache:
        def clear_pending(row: ImageUpdateCache) -> None:
            row.pending_current_digest = None
            row.pending_registry_digest = None
            row.pending_platform = None
            row.pending_matched_field = None
            row.pending_detected_at = None

        def assign_identity(row: ImageUpdateCache) -> None:
            row.registry_index_digest = result.registry_index_digest
            row.registry_manifest_digest = result.registry_manifest_digest
            row.registry_config_digest = result.registry_config_digest
            row.identity_error = result.identity_error

        def pending_matches(row: ImageUpdateCache) -> bool:
            return (
                _same_digest(row.pending_current_digest, result.current_digest)
                and _same_digest(row.pending_registry_digest, result.registry_digest)
                and (row.pending_platform or "") == (result.platform or "")
            )

        if existing is None:
            existing = ImageUpdateCache(
                host_id=host_id,
                image=result.image,
                status=PENDING_UPDATE_STATUS if result.status == "updatable" else result.status,
                current_digest=result.current_digest,
                registry_digest=result.registry_digest,
                registry_name=result.registry,
                platform=result.platform,
                registry_index_digest=result.registry_index_digest,
                registry_manifest_digest=result.registry_manifest_digest,
                registry_config_digest=result.registry_config_digest,
                identity_error=result.identity_error,
                http_status=result.http_status,
                matched_field=result.matched_field,
                retry_after=result.retry_after,
                checked_at=now,
            )
            session.add(existing)

        if result.status == "updatable" and not pending_matches(existing):
            existing.pending_current_digest = result.current_digest
            existing.pending_registry_digest = result.registry_digest
            existing.pending_platform = result.platform
            existing.pending_matched_field = result.matched_field
            existing.pending_detected_at = now
            existing.registry_name = result.registry
            existing.http_status = result.http_status
            existing.retry_after = result.retry_after
            existing.checked_at = now
            existing.updated_at = now
            existing.failure_count = 0
            existing.last_failure_status = None
            existing.last_failure_http_status = None
            existing.last_failure_retry_after = None
            existing.last_failure_at = None
            assign_identity(existing)
            if existing.status != "updatable":
                existing.status = PENDING_UPDATE_STATUS
                existing.current_digest = result.current_digest
                existing.registry_digest = result.registry_digest
                existing.platform = result.platform
                existing.matched_field = result.matched_field
            return existing

        if result.status in FAILED_UPDATE_STATUSES:
            existing.failure_count += 1
            existing.last_failure_status = result.status
            existing.last_failure_http_status = result.http_status
            existing.last_failure_retry_after = result.retry_after
            existing.last_failure_at = now
            existing.updated_at = now

            # Preserve the last conclusive result when we have one, so a
            # transient registry failure does not erase useful UI state.
            if existing.status not in VISIBLE_UPDATE_STATUSES and existing.status != PENDING_UPDATE_STATUS:
                existing.status = result.status
                existing.current_digest = result.current_digest
                existing.registry_digest = result.registry_digest
                existing.registry_name = result.registry
                existing.platform = result.platform
                existing.http_status = result.http_status
                existing.matched_field = result.matched_field
                existing.retry_after = result.retry_after
                existing.checked_at = now
                assign_identity(existing)
            return existing

        existing.status = result.status
        existing.current_digest = result.current_digest
        existing.registry_digest = result.registry_digest
        existing.registry_name = result.registry
        existing.platform = result.platform
        existing.registry_index_digest = result.registry_index_digest
        existing.registry_manifest_digest = result.registry_manifest_digest
        existing.registry_config_digest = result.registry_config_digest
        existing.identity_error = result.identity_error
        existing.http_status = result.http_status
        existing.matched_field = result.matched_field
        existing.retry_after = result.retry_after
        existing.checked_at = now
        existing.failure_count = 0
        existing.last_failure_status = None
        existing.last_failure_http_status = None
        existing.last_failure_retry_after = None
        existing.last_failure_at = None
        clear_pending(existing)
        existing.updated_at = now
        return existing

    async def _refresh_update_checks_for_snapshot(
        self, snap: HostSnapshot, force: bool = False, *, refresh_images: set[str] | None = None
    ) -> list[str]:
        """Refresh checks; return newly confirmed updatable images for this sweep."""
        if not snap.host_config:
            return []

        host_id = snap.host_config.host_id
        image_refs = [
            (
                c.image,
                c.repo_digests,
                c.image_config_digest,
                c.platform,
                c.image_manifest_digest,
            )
            for c in snap.containers
            if c.image
        ]
        current_images = {image for image, *_ in image_refs}

        with Session(engine) as session:
            rows = session.exec(
                select(ImageUpdateCache).where(ImageUpdateCache.host_id == host_id)
            ).all()

        if not image_refs:
            self._apply_update_cache_rows_to_snapshot(snap, rows)
            return []

        rows_by_image = {row.image: row for row in rows}
        now = _utc_now()
        interval = timedelta(seconds=get_settings().UPDATE_CHECK_INTERVAL)

        merged_refs: dict[str, dict] = {}
        for image_ref, repo_digests, local_image_id, platform, local_manifest_digest in image_refs:
            existing = merged_refs.setdefault(
                image_ref,
                {"repo_digests": [], "local_image_id": None, "platform": None, "local_manifest_digest": None},
            )
            for digest in repo_digests or []:
                if digest and digest not in existing["repo_digests"]:
                    existing["repo_digests"].append(digest)
            if local_image_id and not existing["local_image_id"]:
                existing["local_image_id"] = local_image_id
            if platform and not existing["platform"]:
                existing["platform"] = platform
            if local_manifest_digest and not existing["local_manifest_digest"]:
                existing["local_manifest_digest"] = local_manifest_digest

        def identity_type_changed(image_ref: str, info: dict) -> bool:
            row = rows_by_image.get(image_ref)
            if row is None or row.status in FAILED_UPDATE_STATUSES or row.last_failure_status in FAILED_UPDATE_STATUSES:
                return False
            target = row.registry_config_digest if info["local_image_id"] else (
                row.registry_manifest_digest if info["local_manifest_digest"] else None
            )
            return bool(target and target != row.registry_digest)

        due_refs = [
            (
                image_ref,
                info["repo_digests"],
                info["local_image_id"],
                info["platform"],
                info["local_manifest_digest"],
            )
            for image_ref, info in merged_refs.items()
            if (
                image_ref in refresh_images if refresh_images is not None
                else (self._is_update_cache_due(rows_by_image.get(image_ref), now, interval, force)
                      or identity_type_changed(image_ref, info))
            )
        ]

        if not due_refs:
            self._apply_update_cache_rows_to_snapshot(snap, rows, current_images)
            return []

        try:
            results = await run_update_check(host_id, due_refs, force=force)

            with Session(engine) as session:
                fresh_rows = session.exec(
                    select(ImageUpdateCache).where(ImageUpdateCache.host_id == host_id)
                ).all()
                fresh_by_image = {row.image: row for row in fresh_rows}

                for result in results:
                    row = fresh_by_image.get(result.image)
                    persisted = self._persist_update_check_result(
                        session,
                        host_id,
                        result,
                        row,
                        now,
                    )
                    fresh_by_image[result.image] = persisted

                session.commit()
                final_rows = session.exec(
                    select(ImageUpdateCache).where(ImageUpdateCache.host_id == host_id)
                ).all()

            self._apply_update_cache_rows_to_snapshot(
                snap,
                final_rows,
                current_images,
            )
            return [r.image for r in results if r.status == "updatable" and snap.update_results.get(r.image) == "updatable"]
        except Exception as exc:
            logger.warning(
                "Update check failed for %s: %s", host_id, exc, exc_info=True
            )
            self._apply_update_cache_rows_to_snapshot(snap, rows, current_images)
            return []

    # ── Build summaries for API ────────────────────────────────────

    def build_host_summary(self, snap: HostSnapshot) -> HostSummary:
        return build_host_summary(snap)


# Singleton
snapshot_manager = SnapshotManager()
