import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from app.models import HostConfig, ImageUpdateCache
from app.schemas import ContainerSummary, UpdateCheckResult
from app.services import snapshot as module
from app.services.snapshot import HostSnapshot, SnapshotManager
from app.services import update_check


class RuntimeUpdateChecksTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch.object(module, "engine", self.engine)
        self.engine_patch.start()
        self.manager = SnapshotManager()
        self.snap = HostSnapshot()
        self.snap.host_config = HostConfig(host_id="nas")
        self.snap.status = "online"
        self.snap.containers_updated = 2
        self.image = "ghcr.io/jxxghp/moviepilot:latest"
        self.snap.containers = [self.container("new", "sha256:new")]
        self.manager._snapshots["nas"] = self.snap

    def container(self, name, image_id):
        return ContainerSummary(id=name, name=name, image=self.image, image_id=image_id,
                                platform="linux/amd64", state="running", status="Up", created=0,
                                stack_name=name, service_name="app", inspection_complete=True)

    async def asyncTearDown(self):
        self.engine_patch.stop()
        self.engine.dispose()

    async def test_changed_reference_bypasses_recent_stale_cache_without_checking_other_images(self):
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session:
            session.add(ImageUpdateCache(host_id="nas", image=self.image, status="updatable",
                                         current_digest="sha256:old", registry_digest="sha256:old-target", checked_at=now))
            session.commit()
        self.snap.containers.append(self.container("other", "sha256:other"))
        self.snap.containers[-1].image = "other:latest"
        result = UpdateCheckResult(host_id="nas", image=self.image, status="up_to_date",
                                   current_digest="sha256:new", registry_digest="sha256:new",
                                   registry_config_digest="sha256:new", platform="linux/amd64")
        with patch.object(module, "run_update_check", new=AsyncMock(return_value=[result])) as check:
            await self.manager._refresh_update_checks_for_snapshot(self.snap, refresh_images={self.image})
        self.assertEqual([ref[0] for ref in check.await_args.args[1]], [self.image])
        self.assertEqual(self.snap.update_results[self.image], "up_to_date")
        with Session(self.engine) as session:
            row = session.exec(select(ImageUpdateCache).where(ImageUpdateCache.image == self.image)).one()
            self.assertEqual(row.status, "up_to_date")
            self.assertEqual(row.registry_config_digest, "sha256:new")

    async def test_container_recreation_rechecks_reference_once(self):
        self.snap.host_config.agent_url = "http://agent"
        proxy = SimpleNamespace(
            version=AsyncMock(return_value={}), info=AsyncMock(return_value={}),
            disk_usage=AsyncMock(return_value={}), list_images=AsyncMock(return_value=[]),
            list_containers=AsyncMock(return_value=[{
                "Id": "replacement", "Names": ["/MoviePilot_v2"], "Image": self.image,
                "ImageID": "sha256:new", "State": "running",
            }]),
            container_inspect=AsyncMock(return_value={"Config": {"Image": self.image}, "State": {"Status": "running"}}),
            image_inspect=AsyncMock(return_value={"Id": "sha256:new", "Os": "linux", "Architecture": "amd64"}),
        )
        self.manager._agent_clients["nas"] = proxy
        self.manager._refresh_stacks = AsyncMock()
        self.manager._refresh_container_stats = AsyncMock()
        self.manager._refresh_update_checks_for_snapshot = AsyncMock(return_value=[])
        await self.manager._refresh_host_docker_locked("nas")
        self.manager._refresh_update_checks_for_snapshot.assert_awaited_once_with(self.snap, refresh_images={self.image})
        await self.manager._refresh_host_docker_locked("nas")
        self.assertEqual(self.manager._refresh_update_checks_for_snapshot.await_count, 1)
        await asyncio.gather(*self.manager._stats_tasks.values())

    async def test_shared_tag_with_old_instance_stays_updatable(self):
        self.snap.containers.append(self.container("old-stack", "sha256:old"))
        row = ImageUpdateCache(host_id="nas", image=self.image, status="up_to_date",
                               registry_digest="sha256:new", registry_config_digest="sha256:new")
        self.manager._apply_update_cache_rows_to_snapshot(self.snap, [row], {self.image})
        self.assertEqual(self.snap.update_results[self.image], "updatable")
        self.assertEqual(self.snap.update_count, 1)

    async def test_verified_deployment_refreshes_only_its_image_badge(self):
        self.manager.refresh_host_docker = AsyncMock()
        self.manager._refresh_update_checks_for_snapshot = AsyncMock(return_value=[])
        outcome = await self.manager.verify_update_targets("nas", "new", {
            "app": {"image": self.image, "image_id": "sha256:new", "platform": "linux/amd64", "container_count": 1},
        }, not_before=1, wait_timeout=0)
        self.assertEqual(outcome[0], "success")
        self.manager._refresh_update_checks_for_snapshot.assert_awaited_once_with(self.snap, refresh_images={self.image})

    async def test_matching_index_cannot_override_different_running_config(self):
        lookup = update_check.RegistryLookupResult(digests=update_check.RegistryDigests(
            repo_digests=["sha256:index", "sha256:manifest"], index_digest="sha256:index",
            manifest_digest="sha256:manifest", config_digest="sha256:new", resolved_platform="linux/amd64"))
        with patch.object(update_check, "_lookup_registry_identity", new=AsyncMock(return_value=lookup)):
            result = await update_check.check_image("nas", self.image, [self.image + "@sha256:index"],
                                                     local_image_id="sha256:old", platform="linux/amd64")
        self.assertEqual(result.status, "updatable")
        self.assertEqual(result.registry_digest, "sha256:new")

    async def test_platform_unknown_is_not_assumed_to_be_amd64(self):
        self.assertEqual(update_check._parse_platform(None), {})
