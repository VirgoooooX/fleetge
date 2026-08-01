import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.schemas import HostSummary
from app.services.snapshot import SnapshotManager


class SharedMetricsBroadcasterTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_subscribers_share_one_refresh_task(self):
        manager = SnapshotManager()
        manager._running = True
        manager.refresh_hosts = AsyncMock()
        manager.refresh_metrics_now = AsyncMock(return_value=[
            HostSummary(host_id="host-a", display_name="Host A", status="online")
        ])
        settings = SimpleNamespace(METRICS_STREAM_INTERVAL=0.05, DOCKER_POLL_INTERVAL=10)
        with patch("app.services.snapshot.get_settings", return_value=settings):
            first = manager.add_metrics_subscriber()
            task = manager._metrics_broadcast_task
            second = manager.add_metrics_subscriber()
            self.assertIs(task, manager._metrics_broadcast_task)
            await asyncio.wait_for(first.get(), timeout=1.0)
            await asyncio.wait_for(second.get(), timeout=1.0)
            await asyncio.sleep(0.12)
            self.assertLess(manager.refresh_metrics_now.await_count, 6)
            manager.remove_metrics_subscriber(first)
            manager.remove_metrics_subscriber(second)
            calls_at_disconnect = manager.refresh_metrics_now.await_count
            await asyncio.sleep(0.1)
            self.assertEqual(manager.refresh_metrics_now.await_count, calls_at_disconnect)
            manager._metrics_idle_deadline = 0
            manager._metrics_wake_event.set()
            await asyncio.wait_for(task, timeout=1.0)

    def test_structure_lease_uses_fastest_route_and_idles_to_background(self):
        manager = SnapshotManager()
        overview = manager.register_structure_lease(30)
        detail = manager.register_structure_lease(10)
        self.assertEqual(manager._structure_interval(3600), 10)
        manager.unregister_structure_lease(detail)
        self.assertEqual(manager._structure_interval(3600), 30)
        manager.unregister_structure_lease(overview)
        self.assertEqual(manager._structure_interval(3600), 3600)
