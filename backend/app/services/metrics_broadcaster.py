"""Share one metrics refresh and the latest payload across SSE subscribers."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from app.schemas import HostSummary

logger = logging.getLogger(__name__)


def metrics_payload(summaries: list[HostSummary]) -> dict:
    return {"hosts": [summary.model_dump(mode="json") for summary in summaries], "updated": time.time()}


def _metrics_signature(summaries: list[HostSummary]) -> tuple:
    return tuple(
        (
            summary.host_id, summary.status, summary.error_message,
            summary.metrics.timestamp if summary.metrics else None,
            summary.metrics.networkCounterEpoch if summary.metrics else None,
        )
        for summary in summaries
    )


class MetricsBroadcaster:
    def __init__(
        self, refresh: Callable[[], Awaitable[list[HostSummary]]], interval: Callable[[], float],
    ) -> None:
        self._refresh = refresh
        self._interval = interval
        self._subscribers: set[asyncio.Queue] = set()
        self._wake_event = asyncio.Event()
        self._idle_deadline: float | None = None
        self.task: asyncio.Task[None] | None = None

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        self._idle_deadline = None
        self._wake_event.set()
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)
        if not self._subscribers and self._idle_deadline is None:
            self._idle_deadline = time.monotonic() + 15.0
        self._wake_event.set()

    def start(self) -> None:
        if self._subscribers and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self._run(), name="fleetge-metrics-broadcaster")

    async def stop(self, *, clear_subscribers: bool = False) -> None:
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if clear_subscribers:
            self._subscribers.clear()
            self._wake_event = asyncio.Event()
            self._idle_deadline = None

    async def _wait_for_change(self, timeout: float) -> bool:
        self._wake_event.clear()
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return True

    async def _run(self) -> None:
        next_deadline = time.monotonic()
        last_signature: tuple | None = None
        while True:
            now = time.monotonic()
            if not self._subscribers:
                if self._idle_deadline is None:
                    self._idle_deadline = now + 15.0
                remaining = self._idle_deadline - now
                if remaining <= 0 or not await self._wait_for_change(remaining):
                    return
                next_deadline = time.monotonic()
                continue

            try:
                summaries = await self._refresh()
                signature = _metrics_signature(summaries)
                if signature != last_signature:
                    payload = metrics_payload(summaries)
                    for queue in self._subscribers:
                        if queue.full():
                            queue.get_nowait()
                        queue.put_nowait(payload)
                    last_signature = signature
            except Exception as exc:
                logger.debug("Shared metrics refresh failed: %s", exc)

            interval = max(self._interval(), 0.5)
            next_deadline += interval
            now = time.monotonic()
            if next_deadline <= now:
                next_deadline = now + interval
            if await self._wait_for_change(next_deadline - now) and self._subscribers:
                next_deadline = min(next_deadline, time.monotonic())
