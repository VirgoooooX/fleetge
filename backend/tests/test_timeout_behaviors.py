import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

# Ensure test env vars are set before importing app modules
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("CREDENTIALS_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_PASSWORD", "test-password")

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
            agent_url="http://localhost:8080",
        )
        self.snap = HostSnapshot()
        self.snap.host_config = self.config
        self.manager._snapshots[self.host_id] = self.snap

    def make_proxy(self):
        proxy = MagicMock()
        proxy.fetch_snapshot = AsyncMock(side_effect=httpx.HTTPStatusError(
            "legacy agent", request=MagicMock(), response=MagicMock(status_code=404)
        ))
        self.manager._agent_clients[self.host_id] = proxy
        return proxy

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

    async def test_retry_lock_contention_is_debug_only(self):
        lock = self.manager._host_refresh_locks.setdefault(self.host_id, asyncio.Lock())
        await lock.acquire()
        try:
            with patch("app.services.snapshot.logger.warning") as warn_log, \
                 patch("app.services.snapshot.logger.debug") as debug_log:
                await self.manager.refresh_host_docker(
                    self.host_id,
                    trigger_initial_update_check=False,
                    lock_timeout=0.01,
                    force_status_on_timeout=False,
                )

            warn_log.assert_not_called()
            debug_log.assert_called()
        finally:
            lock.release()

    async def test_transient_agent_connection_error_logs_without_traceback(self):
        proxy = self.make_proxy()
        proxy.version = AsyncMock(side_effect=httpx.ConnectError("All connection attempts failed"))

        with self.assertLogs("app.services.snapshot", level="WARNING") as logs:
            await self.manager._refresh_host_docker_locked(
                self.host_id,
                trigger_initial_update_check=False,
            )

        self.assertIn("Agent poll failed for test-host", logs.output[0])
        self.assertIsNone(logs.records[0].exc_info)
        self.assertEqual(self.snap.status, "degraded")

    async def test_no_stats_task_accumulation(self):
        # Mock dependencies for _refresh_host_docker_locked
        proxy = self.make_proxy()
        proxy.version = AsyncMock(return_value={"Version": "1.0"})
        proxy.info = AsyncMock(return_value={"OSType": "linux"})
        proxy.disk_usage = AsyncMock(return_value={})
        proxy.list_images = AsyncMock(return_value=[])
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

    async def test_aggregate_refresh_reuses_running_image_evidence(self):
        proxy = self.make_proxy()
        proxy.fetch_snapshot = AsyncMock(return_value={
            "version": {"Version": "27.3.1"},
            "info": {"OSType": "linux"},
            "df": {},
            "images": [],
            "containers": [{
                "Id": "container-1", "Names": ["/app"], "Image": "repo/app:latest",
                "ImageID": "sha256:running", "State": "running", "Labels": {},
            }],
            "container_details": {"container-1": {
                "Config": {"Image": "repo/app:latest"}, "State": {"Status": "running"}, "HostConfig": {},
            }},
            "stack_names": ["app"],
            "errors": {},
        })
        proxy.fetch_image_evidence = AsyncMock(return_value={
            "running": {"sha256:running": {"Id": "sha256:running", "RepoDigests": []}},
            "tags": {"repo/app:latest": {"Id": "sha256:tag"}},
            "errors": {},
        })

        await self.manager._refresh_host_docker_locked(self.host_id, trigger_initial_update_check=False)
        self.assertEqual(proxy.fetch_image_evidence.await_args.args, (["sha256:running"], ["repo/app:latest"]))
        self.assertEqual(self.snap.containers[0].tag_image_id, "sha256:tag")
        self.assertEqual(self.snap.stacks[0].name, "app")

        proxy.fetch_image_evidence.return_value["running"] = {}
        await self.manager._refresh_host_docker_locked(self.host_id, trigger_initial_update_check=False)
        self.assertEqual(proxy.fetch_image_evidence.await_args.args, ([], ["repo/app:latest"]))
        self.assertTrue(self.snap.containers[0].inspection_complete)

        task = self.manager._stats_tasks.pop(self.host_id)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_missing_running_evidence_is_retried_next_round(self):
        proxy = self.make_proxy()
        proxy.fetch_snapshot = AsyncMock(return_value={
            "version": {"Version": "27.3.1"},
            "info": {"OSType": "linux"},
            "df": {},
            "images": [],
            "containers": [{
                "Id": "container-1", "Names": ["/app"], "Image": "repo/app:latest",
                "ImageID": "sha256:running", "State": "running", "Labels": {},
            }],
            "container_details": {"container-1": {
                "Config": {"Image": "repo/app:latest"}, "State": {"Status": "running"}, "HostConfig": {},
            }},
            "stack_names": [],
            "errors": {},
        })
        proxy.fetch_image_evidence = AsyncMock(return_value={
            "running": {}, "tags": {}, "errors": {"running:sha256:running": "temporary failure"},
        })

        await self.manager._refresh_host_docker_locked(self.host_id, trigger_initial_update_check=False)
        self.assertEqual(proxy.fetch_image_evidence.await_args.args, (["sha256:running"], ["repo/app:latest"]))
        self.assertFalse(self.snap.containers[0].inspection_complete)

        proxy.fetch_image_evidence.return_value = {
            "running": {"sha256:running": {"Id": "sha256:running", "RepoDigests": []}},
            "tags": {"repo/app:latest": {"Id": "sha256:tag"}},
            "errors": {},
        }
        await self.manager._refresh_host_docker_locked(self.host_id, trigger_initial_update_check=False)
        self.assertEqual(proxy.fetch_image_evidence.await_args.args, (["sha256:running"], ["repo/app:latest"]))
        self.assertTrue(self.snap.containers[0].inspection_complete)

        task = self.manager._stats_tasks.pop(self.host_id)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

if __name__ == "__main__":
    unittest.main()

