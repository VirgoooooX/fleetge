"""Snapshot aggregation and caching — the central data fusion layer.

Polls host structure at a low background cadence and refreshes host-metrics
only while a frontend SSE stream is connected.

Cache tiers:
  - Metrics (exporter): frontend-driven SSE
  - Containers/Stacks (proxy + Dockge): 1h background, faster frontend-driven POST
  - Update checks (registry): 12h
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

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
from app.services.crypto import decrypt_credentials
from app.services.dockge_client import dockge_pool
from app.services.docker_proxy import DockerProxyClient
from app.services.metrics_client import MetricsClient
from app.services.agent_client import AgentClient
from app.services.update_check import run_update_check

logger = logging.getLogger(__name__)

VISIBLE_UPDATE_STATUSES = {"up_to_date", "updatable"}
FAILED_UPDATE_STATUSES = {"needs_auth", "check_failed"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
        self._proxy_clients: dict[str, DockerProxyClient] = {}
        self._metrics_clients: dict[str, MetricsClient] = {}
        self._agent_clients: dict[str, AgentClient] = {}
        self._host_refresh_locks: dict[str, asyncio.Lock] = {}
        self._metrics_refresh_lock = asyncio.Lock()
        self._update_check_lock = asyncio.Lock()
        self._stats_tasks: dict[str, asyncio.Task] = {}
        self._realtime_refresh_tasks: dict[str, asyncio.Task] = {}  # coalesce WebSocket-triggered refreshes
        # Dockge connections are managed by dockge_pool

        # Active connection tracking for polling optimization
        self._active_connections = 0
        self._connection_event = asyncio.Event()

        # Failure backoff: skip unreachable hosts so they don't slow the poll cycle
        self._consecutive_failures: dict[str, int] = {}
        self._backoff_until: dict[str, float] = {}

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
        await dockge_pool.disconnect_all()
        for c in self._proxy_clients.values():
            await c.close()
        self._proxy_clients.clear()
        self._metrics_clients.clear()
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
                    self._proxy_clients.pop(hid, None)
                    self._metrics_clients.pop(hid, None)
                    self._agent_clients.pop(hid, None)
                    self._host_refresh_locks.pop(hid, None)
                    await dockge_pool.remove(hid)
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

    def get_update_check_results(self) -> list[UpdateCheckResult]:
        """Return visible cached update check results without hitting registries."""
        results: list[UpdateCheckResult] = []
        for snap in self._snapshots.values():
            results.extend(
                r for r in snap.update_check_results
                if r.status in VISIBLE_UPDATE_STATUSES
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
        """Apply persisted conclusive update results to one snapshot."""
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
                status=row.status,
            )
            for row in visible_rows
        ]
        for result in snap.update_check_results:
            snap.update_results[result.image] = result.status
        snap.update_count = sum(
            1 for row in visible_rows if row.status == "updatable"
        )

    async def refresh_update_checks_now(self) -> list[UpdateCheckResult]:
        """Run update checks immediately and return the refreshed cache."""
        await self._refresh_update_checks(force=True)
        return self.get_update_check_results()

    async def refresh_metrics_now(self) -> list[HostSummary]:
        """Refresh host metrics immediately and return current host summaries."""
        await self._refresh_metrics()
        return [self.build_host_summary(s) for s in self.list_snapshots()]

    async def refresh_all_structure_now(self) -> list[HostSummary]:
        """Refresh Docker/Dockge structure for all hosts and return summaries."""
        await self.refresh_hosts()
        await self._refresh_docker()
        return [self.build_host_summary(s) for s in self.list_snapshots()]

    async def refresh_host_structure_now(self, host_id: str) -> Optional[HostSnapshot]:
        """Refresh Docker/Dockge structure for one host and return its snapshot."""
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
                    self._proxy_clients.pop(hid, None)
                    self._metrics_clients.pop(hid, None)
                    self._agent_clients.pop(hid, None)
                    self._host_refresh_locks.pop(hid, None)
                    await dockge_pool.remove(hid)

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
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    break

    async def _refresh_metrics(self) -> None:
        """Poll all host-metrics exporters."""
        async with self._metrics_refresh_lock:
            async def refresh_one(snap: HostSnapshot) -> None:
                if not snap.host_config:
                    return
                cfg = snap.host_config
                if self._should_skip(cfg.host_id):
                    return
                try:
                    if cfg.agent_url:
                        if cfg.host_id not in self._agent_clients:
                            self._agent_clients[cfg.host_id] = AgentClient(cfg)
                        agent = self._agent_clients[cfg.host_id]
                        metrics = await agent.fetch_metrics()
                    else:
                        if cfg.host_id not in self._metrics_clients:
                            self._metrics_clients[cfg.host_id] = MetricsClient(cfg)
                        client = self._metrics_clients[cfg.host_id]
                        metrics = await client.fetch()
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
        """Poll docker-socket-proxy and Dockge for a specific host immediately."""
        if self._should_skip(host_id):
            return
        lock = self._host_refresh_locks.setdefault(host_id, asyncio.Lock())
        snap = self._snapshots.get(host_id)

        try:
            await asyncio.wait_for(lock.acquire(), timeout=lock_timeout)
        except asyncio.TimeoutError:
            logger.warning("Host %s refresh lock contention timeout", host_id)
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
            logger.warning("Host %s refresh execution timeout", host_id)
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
        """Poll docker-socket-proxy and Dockge for a specific host immediately."""
        snap = self._snapshots.get(host_id)
        if not snap or not snap.host_config:
            return
        cfg = snap.host_config
        if cfg.agent_url:
            if cfg.host_id not in self._agent_clients:
                self._agent_clients[cfg.host_id] = AgentClient(cfg)
            proxy = self._agent_clients[cfg.host_id]
        else:
            if cfg.host_id not in self._proxy_clients:
                self._proxy_clients[cfg.host_id] = DockerProxyClient(cfg)
            proxy = self._proxy_clients[cfg.host_id]

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
                    or labels.get("com.dockge.stack")
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

            # Fetch RepoDigests for each unique image
            unique_images = list({c.image for c in snap.containers if c.image})
            image_semaphore = asyncio.Semaphore(8)

            async def inspect_image(img_name: str) -> tuple[str, list[str]]:
                async with image_semaphore:
                    img_info = await proxy.image_inspect(img_name)
                rd = img_info.get("RepoDigests", []) or []
                return img_name, rd

            inspect_results = await asyncio.gather(
                *(inspect_image(img_name) for img_name in unique_images),
                return_exceptions=True,
            )
            image_digests: dict[str, list[str]] = {
                img_name: [] for img_name in unique_images
            }
            for img_name, result in zip(unique_images, inspect_results):
                if isinstance(result, Exception):
                    logger.debug(
                        "Image inspect failed for %s/%s: %s",
                        cfg.host_id, img_name, result,
                    )
                    continue
                try:
                    img_name, rd = result
                    image_digests[img_name] = rd
                except Exception as exc:
                    logger.debug(
                        "Image inspect parse failed for %s/%s: %s",
                        cfg.host_id, img_name, exc,
                    )
            for c in snap.containers:
                c.repo_digests = image_digests.get(c.image, [])

            # Stacks from Dockge
            await self._refresh_stacks(snap, cfg)

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
            logger.warning(
                "Docker proxy poll failed for %s: %s", cfg.host_id, exc, exc_info=True
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
        """Poll all docker-socket-proxy instances (info, containers, stats)."""
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

    def parse_dockge_stacks(self, raw_stacks: list) -> list[StackSummary]:
        """Parse raw Dockge stacks payload into StackSummary schemas."""
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
                )
            )
        return stacks

    def _apply_stack_icons(
        self, stacks: list[StackSummary], cfg: HostConfig | None
    ) -> list[StackSummary]:
        """Apply custom icon URLs from host config to stack summaries.

        Icon value handling:
        - Starts with ``http://`` or ``https://`` → URL, return as-is
        - Otherwise → local file path, rewrite as ``/api/static/icons/{filename}``
        """
        if cfg is None or not cfg.stack_icons:
            return stacks

        try:
            import json

            mapping: dict[str, str] = json.loads(cfg.stack_icons)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Invalid stack_icons JSON for host %s: %s", cfg.host_id, cfg.stack_icons
            )
            return stacks

        for stack in stacks:
            icon_value = self._match_icon(stack.name, mapping)
            if not icon_value:
                continue
            if icon_value.startswith("http://") or icon_value.startswith("https://"):
                stack.icon_url = icon_value
            else:
                filename = icon_value.lstrip("/")
                stack.icon_url = f"/api/static/icons/{filename}"

        return stacks

    @staticmethod
    def _match_icon(name: str, mapping: dict[str, str]) -> str | None:
        """Match a stack name against icon mapping keys.

        Priority: exact match > prefix wildcard (``key*``) > suffix wildcard (``*key``).
        """
        # 1. Exact match
        if name in mapping:
            return mapping[name]

        # 2. Wildcard match
        for key, value in mapping.items():
            if key.endswith("*") and name.startswith(key[:-1]):
                return value
            if key.startswith("*") and name.endswith(key[1:]):
                return value

        return None

    def update_host_stacks_realtime(self, host_id: str, raw_stacks: list) -> None:
        """Real-time update of host stacks when Dockge pushes stackList event."""
        snap = self._snapshots.get(host_id)
        if not snap:
            return
        try:
            logger.info("Real-time stack list update received for %s", host_id)
            stacks = self.parse_dockge_stacks(raw_stacks)
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
        """Fetch and merge Dockge stacks with container states."""
        try:
            if cfg.agent_url:
                if cfg.host_id not in self._agent_clients:
                    self._agent_clients[cfg.host_id] = AgentClient(cfg)
                conn = self._agent_clients[cfg.host_id]
                raw_stacks = await conn.list_stacks()
            else:
                # Decrypt Dockge password
                creds = decrypt_credentials(cfg.dockge_password_encrypted)
                conn = await dockge_pool.get_or_create(cfg, creds["password"])
                raw_stacks = await conn.list_stacks()

            stacks = self.parse_dockge_stacks(raw_stacks)
            stacks = self._apply_stack_icons(stacks, cfg)
            snap.stacks = self._merge_stacks_with_container_labels(stacks, snap)
            snap.stacks_updated = time.monotonic()

        except Exception as exc:
            logger.warning("Dockge refresh failed for %s: %s", cfg.host_id, exc)
            self._build_stacks_from_container_labels(snap)

    def _merge_stacks_with_container_labels(
        self, dockge_stacks: list[StackSummary], snap: HostSnapshot
    ) -> list[StackSummary]:
        """Fill missing Dockge service states from Docker Compose labels.

        Some Dockge versions return only the stack names in ``stackList``.
        When that happens the UI would show ``unknown`` even though the
        docker-socket-proxy already has reliable container state and compose
        labels for the same stacks.
        """
        label_stacks = self._stacks_from_container_labels(snap)
        label_by_name = {stack.name: stack for stack in label_stacks}

        merged: list[StackSummary] = []
        seen: set[str] = set()
        for stack in dockge_stacks:
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
                    )
                )
            else:
                merged.append(stack)

        for stack in label_stacks:
            if stack.name not in seen:
                merged.append(stack)

        return self._apply_stack_icons(merged, snap.host_config)

    async def _refresh_container_stats(
        self, snap: HostSnapshot, proxy: DockerProxyClient, cfg: HostConfig
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

        This keeps the monitoring UI useful when Dockge is offline or the
        stored Dockge credential is invalid. Mutating stack operations still
        require a working Dockge connection.
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

    async def _refresh_update_checks(self, force: bool = False) -> None:
        """Query registry digests for all container images across all hosts.

        Runs every configured interval. Results are persisted in SQLite and
        hydrated into memory for fast API responses.
        """
        async with self._update_check_lock:
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

    def _is_update_cache_due(
        self,
        row: ImageUpdateCache | None,
        now: datetime,
        interval: timedelta,
        force: bool,
    ) -> bool:
        if force or row is None:
            return True
        if row.status in FAILED_UPDATE_STATUSES:
            return True
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
        if existing is None:
            existing = ImageUpdateCache(
                host_id=host_id,
                image=result.image,
                status=result.status,
                current_digest=result.current_digest,
                registry_digest=result.registry_digest,
                checked_at=now,
            )
            session.add(existing)

        if result.status in FAILED_UPDATE_STATUSES:
            existing.failure_count += 1
            existing.last_failure_status = result.status
            existing.last_failure_at = now
            existing.updated_at = now

            # Preserve the last conclusive result when we have one, so a
            # transient registry failure does not erase useful UI state.
            if existing.status not in VISIBLE_UPDATE_STATUSES:
                existing.status = result.status
                existing.current_digest = result.current_digest
                existing.registry_digest = result.registry_digest
                existing.checked_at = now
            return existing

        existing.status = result.status
        existing.current_digest = result.current_digest
        existing.registry_digest = result.registry_digest
        existing.checked_at = now
        existing.failure_count = 0
        existing.last_failure_status = None
        existing.last_failure_at = None
        existing.updated_at = now
        return existing

    async def _refresh_update_checks_for_snapshot(
        self, snap: HostSnapshot, force: bool = False
    ) -> None:
        """Refresh cached update-check results for a single host snapshot."""
        if not snap.host_config:
            return

        host_id = snap.host_config.host_id
        image_refs = [(c.image, c.repo_digests) for c in snap.containers]
        current_images = {image for image, _ in image_refs}

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

        merged_refs: dict[str, list[str]] = {}
        for image_ref, repo_digests in image_refs:
            existing = merged_refs.setdefault(image_ref, [])
            for digest in repo_digests or []:
                if digest and digest not in existing:
                    existing.append(digest)

        due_refs = [
            (image_ref, repo_digests)
            for image_ref, repo_digests in merged_refs.items()
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
            results = await run_update_check(host_id, due_refs)

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
