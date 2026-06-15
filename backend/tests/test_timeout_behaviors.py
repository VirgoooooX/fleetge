import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure test env vars are set before importing app modules
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("CREDENTIALS_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "test-password-hash")

from app.models import HostConfig
from app.services.snapshot import HostSnapshot, SnapshotManager
from app.schemas import ContainerSummary, DockerInfo, DockerDiskUsage

class SnapshotManagerTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = SnapshotManager()
        self.host_id = "test-host"
        self.config = HostConfig(
            host_id=self.host_id,
            display_name="Test Host",
            enabled=True,
            dockge_url="http://localhost:5001",
            docker_proxy_url="http://localhost:2375"
        )
        self.snap = HostSnapshot()
        self.snap.host_config = self.config
        self.manager._snapshots[self.host_id] = self.snap

    async def test_lock_contention_timeout(self):
        # Mock _refresh_host_docker_locked to sleep
        async def slow_refresh(*args, **kwargs):
            await asyncio.sleep(2.0)

        self.manager._refresh_host_docker_locked = slow_refresh

        # Start first refresh (holding lock for 2s)
        first_task = asyncio.create_task(
            self.manager.refresh_host_docker(self.host_id, trigger_initial_update_check=False)
        )
        # Yield to let first_task acquire the lock
        await asyncio.sleep(0.05)

        # Call second refresh with a short lock_timeout
        await self.manager.refresh_host_docker(
            self.host_id,
            trigger_initial_update_check=False,
            lock_timeout=0.1,
            execution_timeout=1.0,
            force_status_on_timeout=True
        )

        # Assert status is degraded due to lock contention
        self.assertEqual(self.snap.status, "degraded")
        self.assertIn("lock contention", self.snap.error_message)

        # Clean up first task
        first_task.cancel()
        try:
            await first_task
        except asyncio.CancelledError:
            pass

    async def test_execution_timeout(self):
        # Mock _refresh_host_docker_locked to sleep 5s
        async def slow_refresh(*args, **kwargs):
            await asyncio.sleep(5.0)

        self.manager._refresh_host_docker_locked = slow_refresh

        # Call refresh with a short execution_timeout
        await self.manager.refresh_host_docker(
            self.host_id,
            trigger_initial_update_check=False,
            lock_timeout=1.0,
            execution_timeout=0.1,
            force_status_on_timeout=True
        )

        # Assert status is degraded due to execution timeout
        self.assertEqual(self.snap.status, "degraded")
        self.assertIn("execution timeout", self.snap.error_message)

    async def test_no_stats_task_accumulation(self):
        # Mock dependencies for _refresh_host_docker_locked
        self.manager._proxy_clients[self.host_id] = MagicMock()
        proxy = self.manager._proxy_clients[self.host_id]
        proxy.version = AsyncMock(return_value={"Version": "1.0"})
        proxy.info = AsyncMock(return_value={"OSType": "linux"})
        proxy.disk_usage = AsyncMock(return_value={})
        proxy.list_containers = AsyncMock(return_value=[])

        # Mock _refresh_container_stats to sleep
        async def slow_stats(*args, **kwargs):
            await asyncio.sleep(5.0)
        self.manager._refresh_container_stats = slow_stats

        # Call locked refresh helper directly to trigger background stats
        await self.manager._refresh_host_docker_locked(self.host_id, trigger_initial_update_check=False)

        # Verify a task was registered
        self.assertIn(self.host_id, self.manager._stats_tasks)
        first_task = self.manager._stats_tasks[self.host_id]
        self.assertFalse(first_task.done())

        # Call again, verify it does not create a new task or overwrite the old one
        await self.manager._refresh_host_docker_locked(self.host_id, trigger_initial_update_check=False)
        second_task = self.manager._stats_tasks[self.host_id]
        self.assertIs(first_task, second_task)

        # Clean up background task
        first_task.cancel()
        try:
            await first_task
        except asyncio.CancelledError:
            pass

    async def test_stop_cancels_stats_tasks(self):
        # Create a mock pending stats task
        async def pending_task():
            try:
                await asyncio.sleep(10.0)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(pending_task())
        self.manager._stats_tasks[self.host_id] = task

        # Call stop
        await self.manager.stop()

        # Assert task is cancelled and dict is cleared
        self.assertTrue(task.done())
        self.assertEqual(len(self.manager._stats_tasks), 0)

if __name__ == "__main__":
    unittest.main()
