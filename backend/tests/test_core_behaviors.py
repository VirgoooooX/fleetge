import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault(
    "CREDENTIALS_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
os.environ.setdefault("ADMIN_PASSWORD_HASH", "test-password-hash")
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(tempfile.gettempdir(), 'host_dashboard_test.db')}",
)

from app.models import HostConfig, ImageUpdateCache
from app.schemas import DockerDiskUsage, UpdateCheckResult
from app.services.snapshot import HostSnapshot, SnapshotManager





class SnapshotManagerTests(unittest.TestCase):
    def test_update_check_results_are_read_from_snapshot_cache(self):
        manager = SnapshotManager()
        snap = HostSnapshot()
        snap.update_check_results = [
            UpdateCheckResult(
                host_id="host-a",
                image="nginx:latest",
                status="updatable",
            )
        ]
        manager._snapshots = {"host-a": snap}

        results = manager.get_update_check_results()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].image, "nginx:latest")

    def test_host_summary_uses_local_image_list_count(self):
        manager = SnapshotManager()
        snap = HostSnapshot()
        snap.host_config = HostConfig(
            host_id="host-a",
            display_name="Host A",
            enabled=True,
            agent_url="http://localhost:8080",
        )
        snap.status = "online"
        snap.image_count = 7
        snap.docker_disk = DockerDiskUsage(images_total=39)

        summary = manager.build_host_summary(snap)

        self.assertEqual(summary.image_count, 7)

    def test_failed_update_cache_rows_are_hidden_from_snapshot(self):
        manager = SnapshotManager()
        snap = HostSnapshot()
        rows = [
            ImageUpdateCache(
                host_id="host-a",
                image="nginx:latest",
                status="check_failed",
                checked_at=datetime.now(timezone.utc),
            )
        ]

        manager._apply_update_cache_rows_to_snapshot(snap, rows)

        self.assertEqual(snap.update_check_results, [])
        self.assertEqual(snap.update_count, 0)

    def test_failed_update_check_does_not_overwrite_visible_cache(self):
        manager = SnapshotManager()
        existing = ImageUpdateCache(
            host_id="host-a",
            image="nginx:latest",
            status="updatable",
            current_digest="sha256:old",
            registry_digest="sha256:new",
            checked_at=datetime.now(timezone.utc),
        )
        result = UpdateCheckResult(
            host_id="host-a",
            image="nginx:latest",
            status="check_failed",
        )

        manager._persist_update_check_result(
            MagicMock(),
            "host-a",
            result,
            existing,
            datetime.now(timezone.utc),
        )

        self.assertEqual(existing.status, "updatable")
        self.assertEqual(existing.current_digest, "sha256:old")
        self.assertEqual(existing.registry_digest, "sha256:new")
        self.assertEqual(existing.failure_count, 1)
        self.assertEqual(existing.last_failure_status, "check_failed")


class SnapshotManagerAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = SnapshotManager()
        self.host_id = "test-host-b"
        self.config = HostConfig(
            host_id=self.host_id,
            display_name="Test Host B",
            enabled=True,
            agent_url="http://localhost:8080",
        )
        self.snap = HostSnapshot()
        self.snap.host_config = self.config
        self.manager._snapshots[self.host_id] = self.snap

        # Initialize the DB schema & clear any pre-existing test data for this host
        from app.database import engine, Session
        from sqlmodel import delete
        with Session(engine) as session:
            session.exec(delete(ImageUpdateCache).where(ImageUpdateCache.host_id == self.host_id))
            session.commit()

    async def test_refresh_host_docker_locked_auto_verifies_pulled_image(self):
        # 1. Setup mock AgentClient responses
        self.manager._agent_clients[self.host_id] = MagicMock()
        proxy = self.manager._agent_clients[self.host_id]
        proxy.version = AsyncMock(return_value={"Version": "1.0"})
        proxy.info = AsyncMock(return_value={"OSType": "linux"})
        proxy.disk_usage = AsyncMock(return_value={})
        proxy.list_images = AsyncMock(return_value=[])
        proxy.list_containers = AsyncMock(return_value=[
            {
                "Id": "c1",
                "Names": ["/nginx"],
                "Image": "nginx:latest",
                "ImageID": "sha256:new_id",
                "State": "running",
            }
        ])
        proxy.container_inspect = AsyncMock(return_value={})
        # Mock image_inspect to return the new local repo digest
        proxy.image_inspect = AsyncMock(return_value={
            "RepoDigests": ["nginx:latest@sha256:new_local_digest"]
        })

        # Mock self._refresh_stacks and self._refresh_container_stats to do nothing
        async def mock_refresh_stacks(*args, **kwargs):
            pass
        self.manager._refresh_stacks = mock_refresh_stacks
        
        async def mock_refresh_container_stats(*args, **kwargs):
            pass
        self.manager._refresh_container_stats = mock_refresh_container_stats

        # 2. Insert an old ImageUpdateCache row where the status is "updatable"
        from app.database import engine, Session
        from sqlmodel import select
        with Session(engine) as session:
            old_cache = ImageUpdateCache(
                host_id=self.host_id,
                image="nginx:latest",
                status="updatable",
                current_digest="sha256:old_local_digest",
                registry_digest="sha256:new_local_digest",
                checked_at=datetime.now(timezone.utc),
            )
            session.add(old_cache)
            session.commit()

        # 3. Patch run_update_check to mock the registry check and return up-to-date
        from app.schemas import UpdateCheckResult
        mock_result = UpdateCheckResult(
            host_id=self.host_id,
            image="nginx:latest",
            current_digest="sha256:new_local_digest",
            registry_digest="sha256:new_local_digest",
            status="up_to_date"
        )
        
        with patch("app.services.snapshot.run_update_check", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = [mock_result]
            
            # 4. Trigger docker refresh
            await self.manager._refresh_host_docker_locked(self.host_id, trigger_initial_update_check=False)
            
            # Verify run_update_check was called for the changed image
            mock_check.assert_called_once()
            
        # 5. Assert database cache is updated to "up_to_date"
        with Session(engine) as session:
            updated_cache = session.exec(
                select(ImageUpdateCache).where(
                    ImageUpdateCache.host_id == self.host_id,
                    ImageUpdateCache.image == "nginx:latest"
                )
            ).first()
            self.assertIsNotNone(updated_cache)
            self.assertEqual(updated_cache.status, "up_to_date")
            self.assertEqual(updated_cache.current_digest, "sha256:new_local_digest")

        # 6. Assert memory snapshot is updated
        self.assertEqual(len(self.snap.update_check_results), 1)
        self.assertEqual(self.snap.update_check_results[0].status, "up_to_date")
        self.assertEqual(self.snap.update_count, 0)


if __name__ == "__main__":
    unittest.main()
