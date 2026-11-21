"""Coordinate full registry sweeps and checks queued by structure changes."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.snapshot import HostSnapshot

logger = logging.getLogger(__name__)


class UpdateCheckOrchestrator:
    def __init__(self) -> None:
        self.sweep_running = False
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self._pending: dict[str, set[str]] = {}

    async def run_sweep(self, sweep: Callable[[], Awaitable[None]]) -> bool:
        """Coalesce overlapping manual and scheduled sweeps on the event loop."""
        if self.sweep_running:
            return False
        self.sweep_running = True
        try:
            await sweep()
            return True
        finally:
            self.sweep_running = False

    async def check_snapshots(
        self,
        snapshots: Iterable["HostSnapshot"],
        check: Callable[["HostSnapshot"], Awaitable[list[str]]],
        enqueue: Callable[[str, list[str]], None],
    ) -> None:
        semaphore = asyncio.Semaphore(3)

        async def check_host(snapshot: "HostSnapshot") -> None:
            async with semaphore:
                images = await check(snapshot)
                if images and snapshot.host_config:
                    enqueue(snapshot.host_config.host_id, images)

        results = await asyncio.gather(
            *(check_host(snapshot) for snapshot in snapshots), return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Update check task failed: %s", result)

    def schedule(
        self, host_id: str, images: set[str], check: Callable[[set[str]], Awaitable[list[str]]],
    ) -> None:
        if not images:
            return
        self._pending.setdefault(host_id, set()).update(images)
        existing = self.tasks.get(host_id)
        if existing and not existing.done():
            return
        self.tasks[host_id] = asyncio.create_task(self._run_pending(host_id, check), name=f"fleetge-registry-check:{host_id}")

    async def _run_pending(self, host_id: str, check: Callable[[set[str]], Awaitable[list[str]]]) -> None:
        try:
            while images := self._pending.pop(host_id, None):
                try:
                    await check(images)
                except Exception as exc:
                    logger.warning("Update check failed for %s: %s", host_id, exc)
        finally:
            if self.tasks.get(host_id) is asyncio.current_task():
                self.tasks.pop(host_id)
                self._pending.pop(host_id, None)

    def cancel_host(self, host_id: str) -> asyncio.Task[None] | None:
        self._pending.pop(host_id, None)
        task = self.tasks.pop(host_id, None)
        if task is not None:
            task.cancel()
        return task

    async def stop(self) -> None:
        tasks = [task for host_id in list(self.tasks) if (task := self.cancel_host(host_id)) is not None]
        await asyncio.gather(*tasks, return_exceptions=True)
