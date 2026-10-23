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
        return ContainerSummary(id=name, name=name, image=self.image, image_id=image_id, image_config_digest=image_id,
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
        self.assertEqual(self.snap.containers[0].image_config_digest, "sha256:new")
        self.assertIsNone(self.snap.containers[0].image_manifest_digest)
        await self.manager._refresh_host_docker_locked("nas")
        self.assertEqual(self.manager._refresh_update_checks_for_snapshot.await_count, 1)
        for version in ("25.0.5", "26.1.5", "27.3.1", "28.5.0"):
            proxy.version.return_value = {"Version": version}
            await self.manager._refresh_host_docker_locked("nas")
            self.assertEqual(self.snap.containers[0].image_config_digest, "sha256:new")
        await asyncio.gather(*self.manager._stats_tasks.values())

    async def test_pull_without_recreate_keeps_reference_and_update_badge(self):
        # After pull moves the tag, Docker list returns the old SHA as Image,
        # while inspect.Config.Image still retains the original reference.
        self.snap.host_config.agent_url = "http://agent"
        with Session(self.engine) as session:
            session.add(ImageUpdateCache(host_id="nas", image=self.image, status="updatable",
                current_digest="sha256:old", registry_digest="sha256:new",
                registry_config_digest="sha256:new", platform="linux/amd64"))
            session.commit()
        proxy = SimpleNamespace(
            version=AsyncMock(return_value={}), info=AsyncMock(return_value={}),
            disk_usage=AsyncMock(return_value={}), list_images=AsyncMock(return_value=[]),
            list_containers=AsyncMock(return_value=[{
                "Id": "unchanged", "Names": ["/old-db"], "Image": "sha256:old",
                "ImageID": "sha256:old", "State": "running", "Status": "Up 9 days (healthy)",
            }]),
            container_inspect=AsyncMock(return_value={
                "Config": {"Image": self.image}, "State": {"Status": "running"},
            }),
        )
        async def inspect_image(reference):
            return {"Id": "sha256:new" if reference == self.image else "sha256:old",
                    "Os": "linux", "Architecture": "amd64"}
        proxy.image_inspect = AsyncMock(side_effect=inspect_image)
        self.manager._agent_clients["nas"] = proxy
        self.manager._refresh_stacks = AsyncMock()
        self.manager._refresh_container_stats = AsyncMock()
        with patch.object(module, "run_update_check", new=AsyncMock(side_effect=AssertionError("registry accessed"))) as check:
            for _ in range(2):
                await self.manager._refresh_host_docker_locked("nas", trigger_initial_update_check=False)
                container = self.snap.containers[0]
                self.assertEqual(container.image, self.image)
                self.assertEqual(container.image_id, "sha256:old")
                self.assertEqual(container.tag_image_id, "sha256:new")
                self.assertEqual(self.snap.update_results[self.image], "updatable")
                self.assertEqual(self.snap.update_count, 1)
            check.assert_not_awaited()
        with Session(self.engine) as session:
            row = session.exec(select(ImageUpdateCache).where(ImageUpdateCache.image == self.image)).one()
            self.assertEqual(row.status, "updatable")
        await asyncio.gather(*self.manager._stats_tasks.values())

    async def test_shared_tag_with_old_instance_stays_updatable(self):
        self.snap.containers.append(self.container("old-stack", "sha256:old"))
        row = ImageUpdateCache(host_id="nas", image=self.image, status="up_to_date",
                               registry_digest="sha256:new", registry_config_digest="sha256:new")
        self.manager._apply_update_cache_rows_to_snapshot(self.snap, [row], {self.image})
        self.assertEqual(self.snap.update_results[self.image], "updatable")
        self.assertEqual(self.snap.update_count, 1)

    async def test_verified_deployment_uses_cached_target_without_registry_and_keeps_shared_badge(self):
        self.manager.refresh_host_docker = AsyncMock()
        self.snap.containers.append(self.container("old-stack", "sha256:old"))
        with Session(self.engine) as session:
            session.add(ImageUpdateCache(host_id="nas", image=self.image, status="updatable",
                registry_config_digest="sha256:new", registry_digest="sha256:new", platform="linux/amd64"))
            session.commit()
        with patch.object(module, "run_update_check", new=AsyncMock(side_effect=AssertionError("registry accessed"))) as check:
            outcome = await self.manager.verify_update_targets("nas", "new", {
                "app": {"image": self.image, "image_id": "sha256:new", "platform": "linux/amd64", "container_count": 1,
                        "cached_target": {"registry_config_digest": "sha256:new", "platform": "linux/amd64"}},
            }, not_before=1, wait_timeout=0)
        self.assertEqual(outcome[0], "success")
        check.assert_not_awaited()
        # Another Stack using the same tag is still old; its badge must remain.
        self.assertEqual(self.snap.update_results[self.image], "updatable")

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

    async def test_containerd_index_is_not_mistaken_for_config(self):
        self.snap.host_config.agent_url = "http://agent"
        proxy = SimpleNamespace(
            version=AsyncMock(return_value={}), info=AsyncMock(return_value={}),
            disk_usage=AsyncMock(return_value={}), list_images=AsyncMock(return_value=[]),
            list_containers=AsyncMock(return_value=[{
                "Id": "runtime", "Names": ["/app"], "Image": self.image,
                "ImageID": "sha256:index", "State": "running",
            }]),
            container_inspect=AsyncMock(return_value={
                "Config": {"Image": self.image}, "State": {"Status": "running"},
                "ImageManifestDescriptor": {"mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": "sha256:arm-manifest", "platform": {"os": "linux", "architecture": "arm64"}},
            }),
            image_inspect=AsyncMock(return_value={
                "Id": "sha256:index", "Os": "linux", "Architecture": "amd64",
                "Descriptor": {"mediaType": "application/vnd.oci.image.index.v1+json", "digest": "sha256:index"},
            }),
        )
        self.manager._agent_clients["nas"] = proxy
        self.manager._refresh_stacks = AsyncMock()
        self.manager._refresh_container_stats = AsyncMock()
        self.manager._refresh_update_checks_for_snapshot = AsyncMock(return_value=[])
        await self.manager._refresh_host_docker_locked("nas")
        container = self.snap.containers[0]
        self.assertIsNone(container.image_config_digest)
        self.assertEqual(container.image_manifest_digest, "sha256:arm-manifest")
        self.assertEqual(container.platform, "linux/arm64")
        proxy.info.return_value = {"DriverStatus": [["driver-type", "io.containerd.snapshotter.v1"]]}
        proxy.container_inspect.return_value = {"Config": {"Image": self.image}, "State": {"Status": "running"}}
        await self.manager._refresh_host_docker_locked("nas")
        self.assertIsNone(self.snap.containers[0].image_config_digest)
        self.assertIsNone(self.snap.containers[0].image_manifest_digest)
        # A single-platform image can use the image descriptor directly.
        proxy.list_containers.return_value[0]["ImageID"] = "sha256:manifest"
        proxy.image_inspect.return_value["Id"] = "sha256:manifest"
        proxy.image_inspect.return_value["Descriptor"] = {
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json", "digest": "sha256:manifest",
        }
        await self.manager._refresh_host_docker_locked("nas")
        self.assertIsNone(self.snap.containers[0].image_config_digest)
        self.assertEqual(self.snap.containers[0].image_manifest_digest, "sha256:manifest")
        await asyncio.gather(*self.manager._stats_tasks.values())

    async def test_containerd_single_manifest_uses_its_descriptor(self):
        # Docker 29's single-platform fb3 image has a manifest Id, not a config Id.
        container = self.container("new", "sha256:manifest")
        container.image_config_digest = None
        container.image_manifest_digest = "sha256:manifest"
        self.snap.containers = [container]
        row = ImageUpdateCache(host_id="nas", image=self.image, status="up_to_date",
            registry_config_digest="sha256:config", registry_manifest_digest="sha256:manifest",
            registry_digest="sha256:manifest", platform="linux/amd64")
        self.manager._apply_update_cache_rows_to_snapshot(self.snap, [row], {self.image})
        self.assertEqual(self.snap.update_results[self.image], "up_to_date")
        old = self.container("other-stack", "sha256:old-manifest")
        old.image_config_digest = None
        old.image_manifest_digest = "sha256:old-manifest"
        self.snap.containers.append(old)
        self.manager._apply_update_cache_rows_to_snapshot(self.snap, [row], {self.image})
        self.assertEqual(self.snap.update_results[self.image], "updatable")

    async def test_containerd_cache_corrects_old_config_comparison_without_registry_access(self):
        container = self.snap.containers[0]
        container.image_id = "sha256:index"
        container.image_config_digest = None
        container.image_manifest_digest = "sha256:manifest"
        row = ImageUpdateCache(host_id="nas", image=self.image, status="updatable",
            current_digest="sha256:index", registry_digest="sha256:config",
            registry_config_digest="sha256:config", registry_manifest_digest="sha256:manifest",
            platform="linux/amd64")
        self.manager._apply_update_cache_rows_to_snapshot(self.snap, [row], {self.image})
        result = self.snap.update_check_results[0]
        self.assertEqual(self.snap.update_results[self.image], "up_to_date")
        self.assertEqual(result.current_digest, "sha256:manifest")
        self.assertEqual(result.registry_digest, "sha256:manifest")
        self.assertEqual(result.matched_field, "manifest_digest")

    async def test_containerd_rate_limit_uses_cached_typed_identity_without_retrying(self):
        now = datetime.now(timezone.utc)
        container = self.snap.containers[0]
        container.image_id = "sha256:index"
        container.image_config_digest = None
        container.image_manifest_digest = "sha256:manifest"
        row = ImageUpdateCache(host_id="nas", image=self.image, status="updatable",
            current_digest="sha256:index", registry_digest="sha256:config",
            registry_config_digest="sha256:config", registry_manifest_digest="sha256:manifest",
            platform="linux/amd64", checked_at=now, last_failure_status="rate_limited",
            last_failure_at=now, last_failure_retry_after=3600, failure_count=1)
        with Session(self.engine) as session:
            session.add(row)
            session.commit()
        with patch.object(module, "run_update_check", new=AsyncMock()) as check:
            await self.manager._refresh_update_checks_for_snapshot(self.snap)
        check.assert_not_awaited()
        self.assertEqual(self.snap.update_results[self.image], "up_to_date")
        self.assertEqual(self.snap.update_check_results[0].last_failure_status, "rate_limited")

    async def test_containerd_compares_running_platform_manifest(self):
        lookup = update_check.RegistryLookupResult(digests=update_check.RegistryDigests(
            repo_digests=["sha256:index", "sha256:manifest"], index_digest="sha256:index",
            manifest_digest="sha256:manifest", config_digest="sha256:config", resolved_platform="linux/amd64"))
        with patch.object(update_check, "_lookup_registry_identity", new=AsyncMock(return_value=lookup)):
            for local_manifest, expected in (("sha256:manifest", "up_to_date"), ("sha256:old-manifest", "updatable")):
                result = await update_check.check_image("nas", self.image, [self.image + "@sha256:index"],
                    platform="linux/amd64", local_manifest_digest=local_manifest)
                self.assertEqual(result.status, expected)
                self.assertEqual(result.current_digest, local_manifest)
                self.assertEqual(result.registry_digest, "sha256:manifest")
            unknown = await update_check.check_image("nas", self.image, [self.image + "@sha256:index"], platform="linux/amd64")
            self.assertEqual(unknown.status, "check_failed")

    async def test_unknown_runtime_identity_does_not_produce_a_false_update_badge(self):
        self.snap.containers[0].image_config_digest = None
        for status in ("up_to_date", "updatable"):
            row = ImageUpdateCache(host_id="nas", image=self.image, status=status,
                registry_config_digest="sha256:new", registry_manifest_digest="sha256:manifest", platform="linux/amd64")
            self.manager._apply_update_cache_rows_to_snapshot(self.snap, [row], {self.image})
            self.assertNotIn(self.image, self.snap.update_results)
            self.assertEqual(self.snap.update_count, 0)
            self.assertEqual(self.snap.update_check_results[0].status, "check_failed")

    async def test_changed_target_after_pull_is_uncertain_without_registry_retry(self):
        self.manager.refresh_host_docker = AsyncMock()
        with patch.object(module, "run_update_check", new=AsyncMock(side_effect=AssertionError("registry accessed"))) as check:
            status, detail = await self.manager.verify_update_targets("nas", "new", {
                "app": {"image": self.image, "image_id": "sha256:new", "platform": "linux/amd64", "container_count": 1,
                        "cached_target": {"registry_config_digest": "sha256:newer", "platform": "linux/amd64"}},
            }, not_before=1, wait_timeout=0)
        self.assertEqual(status, "uncertain")
        self.assertIn("待下次定时检测确认", detail)
        check.assert_not_awaited()

    async def test_missing_cached_identity_is_uncertain_without_registry_retry(self):
        self.manager.refresh_host_docker = AsyncMock()
        with patch.object(module, "run_update_check", new=AsyncMock(side_effect=AssertionError("registry accessed"))) as check:
            status, detail = await self.manager.verify_update_targets("nas", "new", {
                "app": {"image": self.image, "image_id": "sha256:new", "platform": "linux/amd64", "container_count": 1},
            }, not_before=1, wait_timeout=0)
        self.assertEqual(status, "uncertain")
        self.assertIn("缓存目标", detail)
        check.assert_not_awaited()

    async def test_recent_config_cache_is_rechecked_when_runtime_uses_containerd_manifest(self):
        container = self.snap.containers[0]
        container.image_id = "sha256:index"
        container.image_config_digest = None
        container.image_manifest_digest = "sha256:manifest"
        with Session(self.engine) as session:
            session.add(ImageUpdateCache(host_id="nas", image=self.image, status="updatable",
                current_digest="sha256:index", registry_digest="sha256:config",
                registry_config_digest="sha256:config", registry_manifest_digest="sha256:manifest",
                checked_at=datetime.now(timezone.utc)))
            session.commit()
        result = UpdateCheckResult(host_id="nas", image=self.image, status="up_to_date",
            current_digest="sha256:manifest", registry_digest="sha256:manifest",
            registry_config_digest="sha256:config", registry_manifest_digest="sha256:manifest", platform="linux/amd64")
        with patch.object(module, "run_update_check", new=AsyncMock(return_value=[result])) as check:
            await self.manager._refresh_update_checks_for_snapshot(self.snap)
        self.assertEqual(check.await_args.args[1], [(self.image, [], None, "linux/amd64", "sha256:manifest")])
        self.assertEqual(self.snap.update_results[self.image], "up_to_date")
        with patch.object(module, "run_update_check", new=AsyncMock()) as check:
            await self.manager._refresh_update_checks_for_snapshot(self.snap)
        check.assert_not_awaited()

    async def test_unhealthy_container_cannot_pass_even_when_its_image_matches(self):
        self.manager.refresh_host_docker = AsyncMock()
        self.snap.containers[0].healthcheck_configured = True
        self.snap.containers[0].health = {"Status": "unhealthy"}
        with patch.object(module, "run_update_check", new=AsyncMock()) as check:
            status, _ = await self.manager.verify_update_targets("nas", "new", {
                "app": {"image": self.image, "image_id": "sha256:new", "platform": "linux/amd64", "container_count": 1},
            }, not_before=1, wait_timeout=0)
        self.assertEqual(status, "failed")
        check.assert_not_awaited()

    async def test_wrong_runtime_platform_cannot_pass_verification(self):
        self.manager.refresh_host_docker = AsyncMock()
        with patch.object(module, "run_update_check", new=AsyncMock()) as check:
            status, _ = await self.manager.verify_update_targets("nas", "new", {
                "app": {"image": self.image, "image_id": "sha256:new", "platform": "linux/arm64", "container_count": 1},
            }, not_before=1, wait_timeout=0)
        self.assertEqual(status, "failed")
        check.assert_not_awaited()
