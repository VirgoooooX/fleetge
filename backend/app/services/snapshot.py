"""Snapshot aggregation and caching — the central data fusion layer.

Polls host structure at a low background cadence and refreshes metrics
only while a frontend SSE stream is connected.

Cache tiers:
  - Metrics: frontend-driven SSE
  - Containers/Stacks: 1h background, faster frontend-driven POST
  - Update checks (registry): 12h
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlmodel import select

from app.config import get_settings
from app.database import engine, Session
from app.models import HostConfig, ImageUpdateCache
from app.schemas import (
    ContainerDetail,
    ContainerStats,
    ContainerSummary,
    ContainerPort,
    DockerInfo,
    DockerDiskUsage,
    HostMetrics,
    HostSummary,
    StackSummary,
    StackService,
    UpdateCheckResult,
)
from app.services.agent_client import AgentClient
from app.services.update_check import _extract_local_digest, run_update_check

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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _same_digest(left: str | None, right: str | None) -> bool:
    return (left or "").strip().lower() == (right or "").strip().lower()


@dataclass
class FinalizeSummary:
    """One per-image verdict produced by finalize_stack_update."""

    image: str
    cleared: bool
    verdict: str


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


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
        self.stats_updated: float = 0.0
        self.error_message: str = ""
        # Update check results per image, keyed by image_ref
        self.update_results: dict[str, str] = {}  # image_ref -> status (up_to_date/updatable/...)
        self.update_check_results: list[UpdateCheckResult] = []
        self.update_count: int = 0


class SnapshotManager:
    """Manages all host snapshots with tiered polling."""

    # Backoff schedule for unreachable hosts (seconds)
    _BACKOFF_SCHEDULE = (5, 15, 30, 60, 120)

    def __init__(self):
        self._snapshots: dict[str, HostSnapshot] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._tasks: list[asyncio.Task] = []

        # Clients — lazily created
        self._agent_clients: dict[str, AgentClient] = {}
        self._host_refresh_locks: dict[str, asyncio.Lock] = {}
        self._metrics_refresh_lock = asyncio.Lock()
        self._update_check_lock = asyncio.Lock()
        self._stats_tasks: dict[str, asyncio.Task] = {}
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
        logger.info(
            "SnapshotManager started with low-frequency structure polling; metrics are frontend-driven"
        )

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in list(self._stats_tasks.values()):
            t.cancel()
        for t in list(self._realtime_refresh_tasks.values()):
            t.cancel()
        await asyncio.gather(
            *self._tasks, *self._stats_tasks.values(),
            *self._realtime_refresh_tasks.values(), return_exceptions=True,
        )
        self._stats_tasks.clear()
        self._realtime_refresh_tasks.clear()
        for c in self._agent_clients.values():
            await c.close()
        self._agent_clients.clear()
        logger.info("SnapshotManager stopped")

    async def restart_poll_loops(self) -> None:
        """Cancel and restart background pollers with updated config intervals.

        IMPORTANT: Tasks are cancelled OUTSIDE the lock to avoid deadlock,
        since _poll_loop → refresh_hosts() also acquires self._lock.
        """
        logger.info("Restarting poll loops...")

        # Step 1: Cancel tasks outside the lock
        self._running = False
        tasks_to_cancel = list(self._tasks)
        for t in tasks_to_cancel:
            t.cancel()
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

        # Step 2: Acquire lock for state rebuild
        async with self._lock:
            self._tasks.clear()

            # Clear settings cache so new intervals are read fresh
            from app.services.settings_service import clear_cache
            clear_cache()

            settings = get_settings()

            # Refresh host snapshots
            # (inline refresh since we hold the lock — don't call refresh_hosts() which also locks)
            with Session(engine) as session:
                hosts = session.exec(select(HostConfig).where(HostConfig.enabled == True)).all()
            configured_ids = {h.host_id for h in hosts}
            for hid in list(self._snapshots.keys()):
                if hid not in configured_ids:
                    del self._snapshots[hid]
                    self._agent_clients.pop(hid, None)
                    self._host_refresh_locks.pop(hid, None)
            for h in hosts:
                if h.host_id not in self._snapshots:
                    snap = HostSnapshot()
                    snap.host_config = h
                    self._snapshots[h.host_id] = snap
                else:
                    self._snapshots[h.host_id].host_config = h

            # Spin up new loops
            self._running = True
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
                        "update_checks",
                        settings.UPDATE_CHECK_INTERVAL,
                        self._refresh_update_checks,
                    )
                ),
            ]
        logger.info("Poll loops restarted successfully.")


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
        snap.update_check_results = [
            UpdateCheckResult(
                host_id=row.host_id,
                image=row.image,
                current_digest=row.current_digest,
                registry_digest=row.registry_digest,
                registry=row.registry,
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
            for row in scoped_rows
        ]
        for row in visible_rows:
            result = UpdateCheckResult(
                host_id=row.host_id,
                image=row.image,
                current_digest=row.current_digest,
                registry_digest=row.registry_digest,
                registry=row.registry,
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
            snap.update_results[result.image] = result.status
        snap.update_count = sum(
            1 for row in visible_rows if row.status == "updatable"
        )

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
            healthy/running + local != cached, re-poll == local
                -> clear tag, "up to date (tag advanced, re-checked)"
            healthy/running + local != cached, re-poll != local / failed
                -> keep, show local/cached/fresh digests
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

            if not row or row.status != "updatable":
                # Nothing to clear (already up_to_date, or a non-conclusive
                # cache row). Still report so the terminal confirms the state.
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
                    cleared=True,
                    verdict=f"{image}: up to date (digest matched)",
                ))
                continue

            # Mismatch: do ONE confirmatory re-poll to distinguish "tag
            # advanced" (container is actually newer) from a real digest
            # discrepancy. This is the only registry round-trip, and only on
            # the already-abnormal path.
            fresh_target = await self._confirm_registry_digest(
                host_id,
                image,
                primary_container.repo_digests,
                local_image_id=local_image_digest,
                platform=primary_container.tag_platform or primary_container.platform,
            )
            if fresh_target and fresh_target in local_candidates:
                self._clear_updatable_tag(host_id, image, local_candidates[0])
                summaries.append(FinalizeSummary(
                    image=image,
                    cleared=True,
                    verdict=(
                        f"{image}: up to date (tag advanced since last check; "
                        f"re-confirmed against registry)"
                    ),
                ))
                continue

            cached_txt = cached_target or "unknown"
            fresh_txt = fresh_target or "unavailable"
            summaries.append(FinalizeSummary(
                image=image,
                cleared=False,
                verdict=(
                    f"{image}: updated, but digest does not match target "
                    f"(local={local_candidates[0][:19]} cached={cached_txt[:19]} "
                    f"registry={fresh_txt[:19]})"
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

    async def _confirm_registry_digest(
        self,
        host_id: str,
        image: str,
        repo_digests: list[str],
        local_image_id: str | None = None,
        platform: str | None = None,
    ) -> Optional[str]:
        """Single forced re-poll of the registry for one image.

        Returns the freshly fetched registry digest, or None on any failure
        (network, auth, parse). Failures are non-fatal — the caller falls back
        to reporting all three digests without clearing the tag.
        """
        try:
            results = await run_update_check(
                host_id, [(image, repo_digests, local_image_id, platform)], force=True
            )
            if results:
                self.persist_update_check_results(host_id, results)
                return _normalize_image_id(results[0].registry_digest)
        except Exception as exc:
            logger.warning("Confirmatory registry re-poll failed for %s: %s", image, exc)
        return None


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
            hosts = session.query(HostConfig).filter(HostConfig.enabled == True).all()

        async with self._lock:
            # Remove hosts no longer configured
            configured_ids = {h.host_id for h in hosts}
            for hid in list(self._snapshots.keys()):
                if hid not in configured_ids:
                    del self._snapshots[hid]
                    self._agent_clients.pop(hid, None)
                    self._host_refresh_locks.pop(hid, None)

            # Add/update snapshots
            for h in hosts:
                if h.host_id not in self._snapshots:
                    snap = HostSnapshot()
                    snap.host_config = h
                    self._snapshots[h.host_id] = snap
                else:
                    self._snapshots[h.host_id].host_config = h

    # ── Poll helpers ───────────────────────────────────────────────

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
                    timeout = float(get_settings().DOCKER_POLL_INTERVAL) if self._active_connections > 0 else float(interval)
                    self._connection_event.clear()
                    if self._active_connections > 0:
                        await asyncio.sleep(timeout)
                    else:
                        try:
                            await asyncio.wait_for(self._connection_event.wait(), timeout=timeout)
                            logger.info("Wake up structure poll loop due to new connection")
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
    ) -> None:
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
            await asyncio.wait_for(
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
            try:
                lock.release()
            except RuntimeError:
                # In case the lock was not held or already released
                pass

    async def _refresh_host_docker_locked(
        self, host_id: str, trigger_initial_update_check: bool = True
    ) -> None:
        """Poll agent for a specific host immediately."""
        snap = self._snapshots.get(host_id)
        if not snap or not snap.host_config:
            return
        cfg = snap.host_config
        if not cfg.agent_url:
            logger.warning("Host %s has no agent_url configured", host_id)
            return

        if cfg.host_id not in self._agent_clients:
            self._agent_clients[cfg.host_id] = AgentClient(cfg)
        proxy = self._agent_clients[cfg.host_id]

        try:
            # Version / Info
            ver = await proxy.version()
            info = await proxy.info()
            snap.docker_info = DockerInfo(
                version=ver.get("Version"),
                api_version=ver.get("ApiVersion"),
                os=info.get("OSType"),
                architecture=info.get("Architecture"),
                docker_root_dir=info.get("DockerRootDir"),
                server_version=info.get("ServerVersion"),
                kernel_version=info.get("KernelVersion"),
                operating_system=info.get("OperatingSystem"),
                n_cpus=info.get("NCPU"),
                memory_total=info.get("MemTotal"),
                name=info.get("Name"),
            )

            # Disk usage (non-fatal, since /system/df can be slow/deadlocked on Windows/WSL2)
            try:
                df = await proxy.disk_usage()
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
            except Exception as df_exc:
                logger.warning(
                    "Failed to fetch docker disk usage for %s: %s",
                    cfg.host_id, df_exc
                )
                snap.docker_disk = None

            # /system/df can include extra disk-accounting entries. /images/json
            # matches the visible local image list more closely.
            raw_images = await proxy.list_images()
            snap.image_count = len(raw_images)
            snap.containers_updated = time.monotonic()

            # Container list
            raw_containers = await proxy.list_containers(all=True)
            inspect_semaphore = asyncio.Semaphore(8)

            async def inspect_container(container_id: str) -> tuple[str, dict]:
                async with inspect_semaphore:
                    return container_id, await proxy.container_inspect(container_id)

            inspect_results = await asyncio.gather(
                *(
                    inspect_container(c.get("Id", ""))
                    for c in raw_containers
                    if c.get("Id")
                ),
                return_exceptions=True,
            )
            inspect_by_id: dict[str, dict] = {}
            for result in inspect_results:
                if isinstance(result, Exception):
                    logger.debug(
                        "Container inspect failed for %s: %s",
                        cfg.host_id, result,
                    )
                    continue
                try:
                    container_id, detail = result
                    inspect_by_id[container_id] = detail
                except Exception as exc:
                    logger.debug(
                        "Container inspect parse failed for %s: %s",
                        cfg.host_id, exc,
                    )

            snap.containers = []
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

                snap.containers.append(
                    ContainerSummary(
                        id=c.get("Id", "")[:12],
                        name=container_name,
                        image=c.get("Image", ""),
                        image_id=c.get("ImageID", ""),
                        state=c.get("State", "unknown"),
                        status=c.get("Status", ""),
                        created=c.get("Created", 0),
                        ports=ports,
                        labels=labels,
                        stack_name=stack_name,
                        service_name=service_name,
                        restart_count=inspect.get("RestartCount"),
                        driver=inspect.get("Driver"),
                        platform=inspect.get("Platform"),
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
                    )
                )

            # Fetch tag image identity for each unique image. RepoDigests and
            # Id come from docker image inspect <tag>; the container's ImageID
            # remains the source of truth for what is actually running.
            unique_images = list({c.image for c in snap.containers if c.image})
            image_semaphore = asyncio.Semaphore(8)

            async def inspect_image(img_name: str) -> tuple[str, list[str], str, str]:
                async with image_semaphore:
                    img_info = await proxy.image_inspect(img_name)
                rd = img_info.get("RepoDigests", []) or []
                image_id = img_info.get("Id", "") or ""
                os_name = img_info.get("Os", "") or ""
                arch = img_info.get("Architecture", "") or ""
                variant = img_info.get("Variant", "") or ""
                platform = "/".join(part for part in (os_name, arch, variant) if part)
                return img_name, rd, image_id, platform

            inspect_results = await asyncio.gather(
                *(inspect_image(img_name) for img_name in unique_images),
                return_exceptions=True,
            )
            image_digests: dict[str, list[str]] = {img_name: [] for img_name in unique_images}
            tag_image_ids: dict[str, str] = {img_name: "" for img_name in unique_images}
            tag_platforms: dict[str, str] = {img_name: "" for img_name in unique_images}
            for img_name, result in zip(unique_images, inspect_results):
                if isinstance(result, Exception):
                    logger.debug(
                        "Image inspect failed for %s/%s: %s",
                        cfg.host_id, img_name, result,
                    )
                    continue
                try:
                    img_name, rd, image_id, platform = result
                    image_digests[img_name] = rd
                    tag_image_ids[img_name] = image_id
                    tag_platforms[img_name] = platform
                except Exception as exc:
                    logger.debug(
                        "Image inspect parse failed for %s/%s: %s",
                        cfg.host_id, img_name, exc,
                    )
            for c in snap.containers:
                c.repo_digests = image_digests.get(c.image, [])
                c.tag_image_id = tag_image_ids.get(c.image) or None
                c.tag_platform = tag_platforms.get(c.image) or None

            # Stacks from Agent
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

            snap.status = "online"
            snap.error_message = ""

            # Container stats are useful but must not block stack refresh
            # or the host's online status. Collect them after the core
            # snapshot is visible.
            existing_task = self._stats_tasks.get(cfg.host_id)
            if existing_task is None or existing_task.done():
                task = asyncio.create_task(self._refresh_container_stats(snap, proxy, cfg))
                self._stats_tasks[cfg.host_id] = task
                task.add_done_callback(lambda _: self._stats_tasks.pop(cfg.host_id, None))

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
        else:
            self._record_success(cfg.host_id)

    async def refresh_host_docker_with_retry(
        self, host_id: str, steps: list[float] = [0.0, 2.0, 5.0, 8.0]
    ) -> None:
        """Refresh host Docker state multiple times with delays to capture transition states."""
        for i, delay in enumerate(steps):
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                await self.refresh_host_docker(
                    host_id,
                    lock_timeout=3.0,
                    execution_timeout=5.0,
                    force_status_on_timeout=False,
                )
            except Exception as exc:
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

    def parse_agent_stacks(self, raw_stacks: list) -> list[StackSummary]:
        """Parse raw Agent stacks payload into StackSummary schemas."""
        stacks: list[StackSummary] = []
        for s in raw_stacks:
            name = s.get("name", s.get("Name", ""))
            services_raw = s.get("services", s.get("Services", [])) or []
            compose_file = s.get("composeFile", s.get("filePath"))

            svcs: list[StackService] = []
            running = 0
            for svc in services_raw:
                state = svc.get("state", svc.get("State", "unknown"))
                if state == "running":
                    running += 1
                svcs.append(
                    StackService(
                        name=svc.get("name", svc.get("Name", "")),
                        container_id=svc.get("containerId"),
                        state=state,
                        status=svc.get("status", ""),
                    )
                )

            # Overall stack status
            if not svcs:
                raw_status = s.get("status")
                if raw_status in ("inactive", "stopped"):
                    overall = "stopped"
                elif raw_status == "exited":
                    overall = "exited"
                elif raw_status in ("active", "running"):
                    overall = "running"
                elif raw_status in ("partial", "partially running"):
                    overall = "partially running"
                elif raw_status is None:
                    overall = "stopped"
                else:
                    overall = raw_status or "unknown"
            elif running == len(svcs):
                overall = "running"
            elif running == 0:
                if any(svc.state == "exited" for svc in svcs):
                    overall = "exited"
                else:
                    overall = "stopped"
            else:
                overall = "partially running"

            stacks.append(
                StackSummary(
                    name=name,
                    status=overall,
                    compose_file=compose_file,
                    service_count=len(svcs),
                    running_count=running,
                    services=svcs,
                    management_status=s.get("management_status", s.get("managementStatus", "managed")),
                )
            )
        return stacks

    def _apply_stack_icons(
        self, stacks: list[StackSummary], cfg: HostConfig | None
    ) -> list[StackSummary]:
        if cfg is None:
            return stacks
        snap = self.get_snapshot(cfg.host_id)
        if not snap:
            snap = HostSnapshot()
            snap.host_config = cfg
        return self._apply_app_profiles(stacks, snap)

    def _apply_app_profiles(
        self, stacks: list[StackSummary], snap: HostSnapshot
    ) -> list[StackSummary]:
        """Apply app profile metadata and fallback icons to stack summaries."""
        cfg = snap.host_config
        if cfg is None:
            return stacks

        profiles: list[dict] = []
        if cfg.app_profiles:
            try:
                import json
                parsed = json.loads(cfg.app_profiles)
                if isinstance(parsed, list):
                    profiles = parsed
            except Exception as e:
                logger.warning("Failed to parse app_profiles JSON for host %s: %s", cfg.host_id, e)

        stack_icons_mapping: dict[str, str] = {}
        if cfg.stack_icons:
            try:
                import json
                parsed_icons = json.loads(cfg.stack_icons)
                if isinstance(parsed_icons, dict):
                    stack_icons_mapping = parsed_icons
            except Exception as e:
                logger.warning("Failed to parse stack_icons JSON for host %s: %s", cfg.host_id, e)

        for stack in stacks:
            matched = self._match_profile(stack.name, profiles)
            
            if matched and matched.get("title"):
                stack.title = matched["title"]
            else:
                stack.title = self._format_stack_title(stack.name)

            if matched and matched.get("app_url"):
                stack.app_url = matched["app_url"]
            else:
                stack.app_url = None

            if matched and matched.get("group"):
                stack.group = matched["group"]
            else:
                stack.group = "未分组"

            icon_val = None
            if matched and matched.get("icon_value"):
                icon_val = matched["icon_value"]
            else:
                icon_val = self._match_icon(stack.name, stack_icons_mapping)

            if icon_val:
                if icon_val.startswith("http://") or icon_val.startswith("https://"):
                    stack.icon_url = icon_val
                else:
                    filename = icon_val.lstrip("/")
                    stack.icon_url = f"/api/static/icons/{filename}"
            else:
                stack.icon_url = None

        return stacks

    @staticmethod
    def _format_stack_title(name: str) -> str:
        s = name.replace("-", " ").replace("_", " ")
        return s.title()

    @staticmethod
    def _match_profile(name: str, profiles: list[dict]) -> dict | None:
        # Priority: exact match > prefix wildcard (key*) > suffix wildcard (*key).
        # 1. Exact match
        for p in profiles:
            pattern = p.get("stack_pattern", "")
            if pattern == name:
                return p

        # 2. Prefix wildcard (e.g. key*)
        for p in profiles:
            pattern = p.get("stack_pattern", "")
            if pattern.endswith("*") and not pattern.startswith("*"):
                prefix = pattern[:-1]
                if name.startswith(prefix):
                    return p

        # 3. Suffix wildcard (e.g. *key)
        for p in profiles:
            pattern = p.get("stack_pattern", "")
            if pattern.startswith("*") and not pattern.endswith("*"):
                suffix = pattern[1:]
                if name.endswith(suffix):
                    return p

        return None

    @staticmethod
    def _match_icon(name: str, mapping: dict[str, str]) -> str | None:
        """Match a stack name against icon mapping keys.

        Priority: exact match > prefix wildcard (``key*``) > suffix wildcard (``*key``).
        """
        # 1. Exact match
        if name in mapping:
            return mapping[name]

        # 2. Prefix wildcard (e.g. key*)
        for key, value in mapping.items():
            if key.endswith("*") and not key.startswith("*"):
                if name.startswith(key[:-1]):
                    return value

        # 3. Suffix wildcard (e.g. *key)
        for key, value in mapping.items():
            if key.startswith("*") and not key.endswith("*"):
                if name.endswith(key[1:]):
                    return value

        return None

    def update_host_stacks_realtime(self, host_id: str, raw_stacks: list) -> None:
        """Real-time update of host stacks when Agent pushes stackList event."""
        snap = self._snapshots.get(host_id)
        if not snap:
            return
        try:
            logger.info("Real-time stack list update received for %s", host_id)
            stacks = self.parse_agent_stacks(raw_stacks)
            stacks = self._apply_stack_icons(stacks, snap.host_config)
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
            stacks = self._apply_stack_icons(stacks, cfg)
            snap.stacks = self._merge_stacks_with_container_labels(stacks, snap)
            snap.stacks_updated = time.monotonic()

        except Exception as exc:
            logger.warning("Agent refresh failed for %s: %s", cfg.host_id, exc)
            self._build_stacks_from_container_labels(snap)

    def _merge_stacks_with_container_labels(
        self, agent_stacks: list[StackSummary], snap: HostSnapshot
    ) -> list[StackSummary]:
        """Fill missing Agent stack states from Docker Compose labels.

        Some Agent versions may return only the stack names.
        When that happens the UI would show ``unknown`` even though the
        Agent already has reliable container state and compose
        labels for the same stacks.
        """
        label_stacks = self._stacks_from_container_labels(snap)
        label_by_name = {stack.name: stack for stack in label_stacks}

        merged: list[StackSummary] = []
        seen: set[str] = set()
        for stack in agent_stacks:
            seen.add(stack.name)
            fallback = label_by_name.get(stack.name)
            if fallback and not stack.services:
                merged.append(
                    StackSummary(
                        name=stack.name,
                        status=fallback.status,
                        compose_file=stack.compose_file or fallback.compose_file,
                        service_count=fallback.service_count,
                        running_count=fallback.running_count,
                        services=fallback.services,
                        icon_url=stack.icon_url,
                        management_status="deployed",
                    )
                )
            else:
                if stack.management_status == "managed":
                    stack.management_status = "deployed" if fallback else "file-only"
                merged.append(stack)

        for stack in label_stacks:
            if stack.name not in seen:
                stack.management_status = "unmanaged"
                merged.append(stack)

        return self._apply_stack_icons(merged, snap.host_config)

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
        snap.stacks = self._stacks_from_container_labels(snap)
        snap.stacks = self._apply_stack_icons(snap.stacks, snap.host_config)
        snap.stacks_updated = time.monotonic()

    def _stacks_from_container_labels(self, snap: HostSnapshot) -> list[StackSummary]:
        """Build stack summaries from Docker Compose labels."""
        grouped: dict[str, list[ContainerSummary]] = {}
        for container in snap.containers:
            if not container.stack_name:
                continue
            grouped.setdefault(container.stack_name, []).append(container)

        stacks: list[StackSummary] = []
        for stack_name, containers in sorted(grouped.items()):
            services: list[StackService] = []
            running = 0
            for container in containers:
                if container.state == "running":
                    running += 1
                services.append(
                    StackService(
                        name=container.service_name or container.name,
                        container_id=container.id,
                        state=container.state,
                        status=container.status,
                    )
                )

            if running == len(services):
                overall = "running"
            elif running == 0:
                if any(svc.state == "exited" for svc in services):
                    overall = "exited"
                else:
                    overall = "stopped"
            else:
                overall = "partially running"

            compose_file = None
            labels = containers[0].labels if containers else {}
            if labels:
                compose_file = labels.get("com.docker.compose.project.config_files")

            stacks.append(
                StackSummary(
                    name=stack_name,
                    status=overall,
                    compose_file=compose_file,
                    service_count=len(services),
                    running_count=running,
                    services=services,
                )
            )

        return stacks

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
                await self._refresh_update_checks_for_snapshot(snap, force=force)

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
                registry=result.registry,
                platform=result.platform,
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
            existing.registry = result.registry
            existing.http_status = result.http_status
            existing.retry_after = result.retry_after
            existing.checked_at = now
            existing.updated_at = now
            existing.failure_count = 0
            existing.last_failure_status = None
            existing.last_failure_http_status = None
            existing.last_failure_retry_after = None
            existing.last_failure_at = None
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
                existing.registry = result.registry
                existing.platform = result.platform
                existing.http_status = result.http_status
                existing.matched_field = result.matched_field
                existing.retry_after = result.retry_after
                existing.checked_at = now
            return existing

        existing.status = result.status
        existing.current_digest = result.current_digest
        existing.registry_digest = result.registry_digest
        existing.registry = result.registry
        existing.platform = result.platform
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
        self, snap: HostSnapshot, force: bool = False
    ) -> None:
        """Refresh cached update-check results for a single host snapshot."""
        if not snap.host_config:
            return

        host_id = snap.host_config.host_id
        image_refs = [
            (
                c.image,
                c.repo_digests,
                c.tag_image_id or c.image_id,
                c.tag_platform or c.platform,
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
            return

        rows_by_image = {row.image: row for row in rows}
        now = _utc_now()
        interval = timedelta(seconds=get_settings().UPDATE_CHECK_INTERVAL)

        merged_refs: dict[str, dict] = {}
        for image_ref, repo_digests, local_image_id, platform in image_refs:
            existing = merged_refs.setdefault(
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

        due_refs = [
            (
                image_ref,
                info["repo_digests"],
                info["local_image_id"],
                info["platform"],
            )
            for image_ref, info in merged_refs.items()
            if self._is_update_cache_due(
                rows_by_image.get(image_ref),
                now,
                interval,
                force,
            )
        ]

        if not due_refs:
            self._apply_update_cache_rows_to_snapshot(snap, rows, current_images)
            return

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
        except Exception as exc:
            logger.warning(
                "Update check failed for %s: %s", host_id, exc, exc_info=True
            )
            self._apply_update_cache_rows_to_snapshot(snap, rows, current_images)

    # ── Build summaries for API ────────────────────────────────────

    def build_host_summary(self, snap: HostSnapshot) -> HostSummary:
        """Build a HostSummary from a snapshot, for the /api/hosts response."""
        cfg = snap.host_config
        info = snap.docker_info
        disk = snap.docker_disk
        containers = snap.containers

        if info is None and snap.status == "degraded":
            effective_status = "degraded"
        elif snap.metrics is None and snap.status == "online":
            effective_status = "degraded"
        else:
            effective_status = snap.status

        return HostSummary(
            host_id=cfg.host_id,
            display_name=cfg.display_name or cfg.host_id,
            status=effective_status,
            metrics=snap.metrics,
            docker_version=info.version if info else None,
            api_version=info.api_version if info else None,
            os_info=info.operating_system if info else None,
            architecture=info.architecture if info else None,
            docker_root_dir=info.docker_root_dir if info else None,
            container_running=sum(1 for c in containers if c.state == "running"),
            container_stopped=sum(1 for c in containers if c.state != "running"),
            container_total=len(containers),
            image_count=snap.image_count,
            docker_disk_images=disk.images_size if disk else None,
            docker_disk_containers=disk.containers_size if disk else None,
            docker_disk_volumes=disk.volumes_size if disk else None,
            docker_disk_build_cache=disk.build_cache_size if disk else None,
            update_count=snap.update_count,  # From update_check background task
            error_message=snap.error_message,  # From snapshot error state
        )


# Singleton
snapshot_manager = SnapshotManager()
