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
os.environ.setdefault("ADMIN_PASSWORD", "test-password")
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

    async def test_refresh_host_docker_locked_mirrors_cache_without_clearing_tags(self):
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
            "Id": "sha256:new_id",
            "RepoDigests": ["nginx:latest@sha256:new_local_digest"],
        })

        # Mock self._refresh_stacks and self._refresh_container_stats to do nothing
        async def mock_refresh_stacks(*args, **kwargs):
            pass
        self.manager._refresh_stacks = mock_refresh_stacks

        async def mock_refresh_container_stats(*args, **kwargs):
            pass
        self.manager._refresh_container_stats = mock_refresh_container_stats

        # 2. Insert an ImageUpdateCache row where the status is "updatable" and
        #    the local digest now matches the cached registry target.
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

        with patch("app.services.snapshot.run_update_check", new_callable=AsyncMock) as mock_check:
            await self.manager._refresh_host_docker_locked(self.host_id, trigger_initial_update_check=False)
            mock_check.assert_not_called()

        # 3. Assert database cache is NOT auto-cleared — a plain refresh is
        #    read-only for tag state. The finalize path handles clearing.
        with Session(engine) as session:
            cached = session.exec(
                select(ImageUpdateCache).where(
                    ImageUpdateCache.host_id == self.host_id,
                    ImageUpdateCache.image == "nginx:latest"
                )
            ).first()
            self.assertIsNotNone(cached)
            self.assertEqual(cached.status, "updatable")
            self.assertEqual(cached.current_digest, "sha256:old_local_digest")

        # 4. Assert memory snapshot correctly mirrors the persisted cache
        #    (including the updatable status), proving read-only mirroring works.
        self.assertEqual(len(self.snap.update_check_results), 1)
        self.assertEqual(self.snap.update_check_results[0].status, "updatable")
        self.assertEqual(self.snap.update_check_results[0].image, "nginx:latest")
        self.assertEqual(self.snap.update_count, 1)

    async def test_forced_update_check_bypasses_memory_cache(self):
        from app.services import update_check

        async with update_check._cache_lock:
            update_check._update_cache.clear()
            update_check._update_cache[f"{self.host_id}:nginx:latest"] = {
                "local": "sha256:old",
                "registry": "sha256:old",
                "status": "up_to_date",
                "ts": update_check.time.monotonic(),
            }

        with patch("app.services.update_check._get_manifest_digest", new_callable=AsyncMock) as mock_digest:
            mock_digest.return_value = ("sha256:new", None)
            result = await update_check.check_image(
                self.host_id,
                "nginx:latest",
                ["nginx:latest@sha256:old"],
                force=True,
            )

        mock_digest.assert_called_once()
        self.assertEqual(result.status, "updatable")
        self.assertEqual(result.registry_digest, "sha256:new")

    async def test_update_check_resolves_oci_index_to_platform_config_digest(self):
        """Multi-arch tags compare remote config.digest with local image ID."""
        from app.services import update_check

        class FakeResponse:
            def __init__(self, status_code, headers=None, payload=None):
                self.status_code = status_code
                self.headers = headers or {}
                self._payload = payload or {}

            def json(self):
                return self._payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise update_check.httpx.HTTPStatusError(
                        "error",
                        request=update_check.httpx.Request("GET", "https://example.invalid"),
                        response=update_check.httpx.Response(self.status_code),
                    )

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None, params=None, timeout=None):
                if url.startswith("https://auth.docker.io/token"):
                    return FakeResponse(200, payload={"token": "token"})
                if url == "https://registry-1.docker.io/v2/library/postgres/manifests/15-alpine":
                    return FakeResponse(
                        200,
                        {
                            "Content-Type": "application/vnd.oci.image.index.v1+json",
                            "Docker-Content-Digest": "sha256:index",
                        },
                        {
                            "mediaType": "application/vnd.oci.image.index.v1+json",
                            "manifests": [
                                {
                                    "digest": "sha256:amd64-manifest",
                                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                                    "platform": {"os": "linux", "architecture": "amd64"},
                                },
                                {
                                    "digest": "sha256:arm64-manifest",
                                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                                    "platform": {"os": "linux", "architecture": "arm64"},
                                },
                            ],
                        },
                    )
                if url == "https://registry-1.docker.io/v2/library/postgres/manifests/sha256:amd64-manifest":
                    return FakeResponse(
                        200,
                        {"Docker-Content-Digest": "sha256:amd64-manifest"},
                        {"config": {"digest": "sha256:local-config"}},
                    )
                return FakeResponse(404)

        with patch("app.services.update_check.httpx.AsyncClient", return_value=FakeClient()):
            result = await update_check.check_image(
                self.host_id,
                "postgres:15-alpine",
                ["postgres@sha256:old-repodigest"],
                local_image_id="sha256:local-config",
                platform="linux/amd64",
                force=True,
            )

        self.assertEqual(result.status, "up_to_date")
        self.assertEqual(result.current_digest, "sha256:local-config")
        self.assertEqual(result.registry_digest, "sha256:local-config")

    async def test_ghcr_public_manifest_follows_bearer_challenge(self):
        from app.services import update_check

        class FakeResponse:
            def __init__(self, status_code, headers=None, payload=None):
                self.status_code = status_code
                self.headers = headers or {}
                self._payload = payload or {}

            def json(self):
                return self._payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise update_check.httpx.HTTPStatusError(
                        "error",
                        request=update_check.httpx.Request("GET", "https://example.invalid"),
                        response=update_check.httpx.Response(self.status_code),
                    )

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None, params=None, timeout=None):
                self.calls.append((url, headers or {}, params or {}))
                if url == "https://ghcr.io/v2/virgooooox/fleetge/manifests/latest":
                    if not (headers or {}).get("Authorization"):
                        return FakeResponse(
                            401,
                            {
                                "WWW-Authenticate": (
                                    'Bearer realm="https://ghcr.io/token",'
                                    'service="ghcr.io",'
                                    'scope="repository:virgooooox/fleetge:pull"'
                                )
                            },
                        )
                    return FakeResponse(
                        200,
                        {"Docker-Content-Digest": "sha256:registry"},
                        {
                            "mediaType": "application/vnd.oci.image.index.v1+json",
                            "manifests": [
                                {
                                    "digest": "sha256:linux-amd64",
                                    "platform": {"os": "linux", "architecture": "amd64"},
                                }
                            ],
                        },
                    )
                if url == "https://ghcr.io/v2/virgooooox/fleetge/manifests/sha256:linux-amd64":
                    assert (headers or {}).get("Authorization") == "Bearer anonymous-token"
                    return FakeResponse(
                        200,
                        {"Docker-Content-Digest": "sha256:linux-amd64"},
                        {"config": {"digest": "sha256:registry-config"}},
                    )
                if url == "https://ghcr.io/token":
                    assert params["service"] == "ghcr.io"
                    assert params["scope"] == "repository:virgooooox/fleetge:pull"
                    return FakeResponse(200, payload={"token": "anonymous-token"})
                return FakeResponse(404)

        fake_client = FakeClient()
        with patch("app.services.update_check.httpx.AsyncClient", return_value=fake_client):
            digest, error_status = await update_check._get_manifest_digest(
                "ghcr.io",
                "virgooooox/fleetge",
                "latest",
            )

        self.assertEqual(error_status, None)
        self.assertEqual(digest, "sha256:registry-config")
        self.assertEqual(len(fake_client.calls), 4)

    # ------------------------------------------------------------------
    # finalize_stack_update tests
    # ------------------------------------------------------------------

    async def test_finalize_clears_tag_when_digest_matches_and_healthy(self):
        """Happy path: local digest == cached target + container healthy -> cleared."""
        from app.database import engine as db_engine, Session as DbSession
        from sqlmodel import select
        from app.services.snapshot import _stack_convergence_block_reason

        # Insert an updatable cache row
        with DbSession(db_engine) as session:
            cache = ImageUpdateCache(
                host_id=self.host_id,
                image="nginx:latest",
                status="updatable",
                current_digest="sha256:old",
                registry_digest="sha256:matched",
                checked_at=datetime.now(timezone.utc),
            )
            session.add(cache)
            session.commit()

        # Set up containers in the snapshot: running, no healthcheck
        from app.schemas import ContainerSummary
        c = ContainerSummary(
            id="c1", name="nginx", image="nginx:latest", image_id="sha256:img",
            tag_image_id="sha256:img",
            state="running", status="Up 5 seconds", created=0,
            repo_digests=["nginx:latest@sha256:matched"],
            stack_name="my-stack", service_name="web",
            health=None,
        )
        self.snap.containers = [c]
        self.snap.update_results = {"nginx:latest": "updatable"}

        summaries = await self.manager.finalize_stack_update(
            self.host_id, "my-stack", ["nginx:latest"]
        )

        self.assertEqual(len(summaries), 1)
        self.assertTrue(summaries[0].cleared)
        self.assertIn("digest matched", summaries[0].verdict)

        # Verify DB was actually cleared
        with DbSession(db_engine) as session:
            row = session.exec(
                select(ImageUpdateCache).where(
                    ImageUpdateCache.host_id == self.host_id,
                    ImageUpdateCache.image == "nginx:latest",
                )
            ).first()
            self.assertEqual(row.status, "up_to_date")

    async def test_finalize_keeps_tag_when_container_still_uses_old_image_id(self):
        """A pulled tag digest is not enough if the running container was not recreated."""
        from app.database import engine as db_engine, Session as DbSession
        from sqlmodel import select
        from app.schemas import ContainerSummary

        with DbSession(db_engine) as session:
            cache = ImageUpdateCache(
                host_id=self.host_id,
                image="nginx:latest",
                status="updatable",
                current_digest="sha256:old",
                registry_digest="sha256:matched",
                checked_at=datetime.now(timezone.utc),
            )
            session.add(cache)
            session.commit()

        c = ContainerSummary(
            id="c1", name="nginx", image="nginx:latest", image_id="sha256:old_image",
            tag_image_id="sha256:new_image",
            state="running", status="Up 5 seconds", created=0,
            repo_digests=["nginx:latest@sha256:matched"],
            stack_name="my-stack", service_name="web",
            health=None,
        )
        self.snap.containers = [c]

        summaries = await self.manager.finalize_stack_update(
            self.host_id, "my-stack", ["nginx:latest"]
        )

        self.assertEqual(len(summaries), 1)
        self.assertFalse(summaries[0].cleared)
        self.assertIn("still uses image", summaries[0].verdict)

        with DbSession(db_engine) as session:
            row = session.exec(
                select(ImageUpdateCache).where(
                    ImageUpdateCache.host_id == self.host_id,
                    ImageUpdateCache.image == "nginx:latest",
                )
            ).first()
            self.assertEqual(row.status, "updatable")

    async def test_finalize_keeps_tag_when_health_starting(self):
        """Health starting blocks tag clearing."""
        from app.database import engine as db_engine, Session as DbSession
        from sqlmodel import select
        from app.schemas import ContainerSummary

        with DbSession(db_engine) as session:
            cache = ImageUpdateCache(
                host_id=self.host_id,
                image="nginx:latest",
                status="updatable",
                current_digest="sha256:old",
                registry_digest="sha256:matched",
                checked_at=datetime.now(timezone.utc),
            )
            session.add(cache)
            session.commit()

        c = ContainerSummary(
            id="c1", name="nginx", image="nginx:latest", image_id="sha256:img",
            tag_image_id="sha256:img",
            state="running", status="Up 5 seconds", created=0,
            repo_digests=["nginx:latest@sha256:matched"],
            stack_name="my-stack", service_name="web",
            health={"Status": "starting"},
        )
        self.snap.containers = [c]

        summaries = await self.manager.finalize_stack_update(
            self.host_id, "my-stack", ["nginx:latest"]
        )

        self.assertEqual(len(summaries), 1)
        self.assertFalse(summaries[0].cleared)
        self.assertIn("starting", summaries[0].verdict)

        # DB must still be updatable
        with DbSession(db_engine) as session:
            row = session.exec(
                select(ImageUpdateCache).where(
                    ImageUpdateCache.host_id == self.host_id,
                    ImageUpdateCache.image == "nginx:latest",
                )
            ).first()
            self.assertEqual(row.status, "updatable")

    async def test_finalize_waits_for_health_then_clears_tag(self):
        """The update path waits briefly for healthchecks to converge."""
        from app.database import engine as db_engine, Session as DbSession
        from sqlmodel import select
        from app.schemas import ContainerSummary

        with DbSession(db_engine) as session:
            cache = ImageUpdateCache(
                host_id=self.host_id,
                image="nginx:latest",
                status="updatable",
                current_digest="sha256:old",
                registry_digest="sha256:matched",
                checked_at=datetime.now(timezone.utc),
            )
            session.add(cache)
            session.commit()

        c = ContainerSummary(
            id="c1", name="nginx", image="nginx:latest", image_id="sha256:img",
            tag_image_id="sha256:img",
            state="running", status="Up 5 seconds", created=0,
            repo_digests=["nginx:latest@sha256:matched"],
            stack_name="my-stack", service_name="web",
            health={"Status": "starting"},
        )
        self.snap.containers = [c]

        async def mark_healthy(*args, **kwargs):
            self.snap.containers[0].health = {"Status": "healthy"}

        self.manager.refresh_host_docker = AsyncMock(side_effect=mark_healthy)

        summaries = await self.manager.finalize_stack_update(
            self.host_id,
            "my-stack",
            ["nginx:latest"],
            wait_timeout=0.1,
            wait_interval=0.01,
        )

        self.assertEqual(len(summaries), 1)
        self.assertTrue(summaries[0].cleared)
        self.manager.refresh_host_docker.assert_called()

        with DbSession(db_engine) as session:
            row = session.exec(
                select(ImageUpdateCache).where(
                    ImageUpdateCache.host_id == self.host_id,
                    ImageUpdateCache.image == "nginx:latest",
                )
            ).first()
            self.assertEqual(row.status, "up_to_date")

    async def test_finalize_keeps_tag_when_container_created(self):
        """Container in 'created' state blocks tag clearing."""
        from app.database import engine as db_engine, Session as DbSession
        from app.schemas import ContainerSummary

        with DbSession(db_engine) as session:
            cache = ImageUpdateCache(
                host_id=self.host_id,
                image="nginx:latest",
                status="updatable",
                current_digest="sha256:old",
                registry_digest="sha256:matched",
                checked_at=datetime.now(timezone.utc),
            )
            session.add(cache)
            session.commit()

        c = ContainerSummary(
            id="c1", name="nginx", image="nginx:latest", image_id="sha256:img",
            tag_image_id="sha256:img",
            state="created", status="Created", created=0,
            repo_digests=["nginx:latest@sha256:matched"],
            stack_name="my-stack", service_name="web",
            health=None,
        )
        self.snap.containers = [c]

        summaries = await self.manager.finalize_stack_update(
            self.host_id, "my-stack", ["nginx:latest"]
        )

        self.assertFalse(summaries[0].cleared)
        self.assertIn("created", summaries[0].verdict)

    async def test_finalize_keeps_tag_when_image_not_in_stack(self):
        """Image marked updatable but no container in this stack -> drift."""
        from app.database import engine as db_engine, Session as DbSession

        with DbSession(db_engine) as session:
            cache = ImageUpdateCache(
                host_id=self.host_id,
                image="postgres:15-alpine",
                status="updatable",
                current_digest="sha256:old",
                registry_digest="sha256:target",
                checked_at=datetime.now(timezone.utc),
            )
            session.add(cache)
            session.commit()

        self.snap.containers = []

        summaries = await self.manager.finalize_stack_update(
            self.host_id, "my-stack", ["postgres:15-alpine"]
        )

        self.assertFalse(summaries[0].cleared)
        self.assertIn("not found in running stack", summaries[0].verdict)
        self.assertIn("compose/runtime", summaries[0].verdict)

    async def test_finalize_repolls_on_mismatch(self):
        """Digest mismatch triggers a single re-poll; poll matches -> cleared."""
        from app.database import engine as db_engine, Session as DbSession
        from app.schemas import ContainerSummary

        with DbSession(db_engine) as session:
            cache = ImageUpdateCache(
                host_id=self.host_id,
                image="nginx:latest",
                status="updatable",
                current_digest="sha256:old",
                # Cached target is "sha256:cached_A" — stale vs reality
                registry_digest="sha256:cached_A",
                checked_at=datetime.now(timezone.utc),
            )
            session.add(cache)
            session.commit()

        c = ContainerSummary(
            id="c1", name="nginx", image="nginx:latest", image_id="sha256:img",
            tag_image_id="sha256:img",
            state="running", status="Up 5 seconds", created=0,
            # Local digest is B — the tag advanced between checks
            repo_digests=["nginx:latest@sha256:local_B"],
            stack_name="my-stack", service_name="web",
            health=None,
        )
        self.snap.containers = [c]

        # Mock run_update_check to return the fresh digest == local_B
        # Must patch where it is used (snapshot module), not where it is defined.
        from app.services import snapshot as snap_module
        with patch.object(snap_module, "run_update_check", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = [
                UpdateCheckResult(
                    host_id=self.host_id,
                    image="nginx:latest",
                    current_digest="sha256:local_B",
                    registry_digest="sha256:local_B",  # re-poll confirms tag advanced
                    status="up_to_date",
                )
            ]
            summaries = await self.manager.finalize_stack_update(
                self.host_id, "my-stack", ["nginx:latest"]
            )
            mock_check.assert_called_once()

        self.assertTrue(summaries[0].cleared)
        self.assertIn("tag advanced", summaries[0].verdict)
        self.assertIn("re-confirmed", summaries[0].verdict)

    async def test_finalize_shows_all_digests_on_mismatch_with_failed_repoll(self):
        """Digest mismatch + re-poll failure -> shows local/cached/registry."""
        from app.database import engine as db_engine, Session as DbSession
        from app.schemas import ContainerSummary

        with DbSession(db_engine) as session:
            cache = ImageUpdateCache(
                host_id=self.host_id,
                image="nginx:latest",
                status="updatable",
                current_digest="sha256:old",
                registry_digest="sha256:cached_A",
                checked_at=datetime.now(timezone.utc),
            )
            session.add(cache)
            session.commit()

        c = ContainerSummary(
            id="c1", name="nginx", image="nginx:latest", image_id="sha256:img",
            tag_image_id="sha256:img",
            state="running", status="Up 5 seconds", created=0,
            repo_digests=["nginx:latest@sha256:local_B"],
            stack_name="my-stack", service_name="web",
            health=None,
        )
        self.snap.containers = [c]

        from app.services import snapshot as snap_module
        with patch.object(snap_module, "run_update_check", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = [
                UpdateCheckResult(
                    host_id=self.host_id,
                    image="nginx:latest",
                    current_digest="sha256:local_B",
                    registry_digest="sha256:registry_C",  # Yet another digest!
                    status="updatable",
                )
            ]
            summaries = await self.manager.finalize_stack_update(
                self.host_id, "my-stack", ["nginx:latest"]
            )

        self.assertFalse(summaries[0].cleared)
        self.assertIn("sha256:img", summaries[0].verdict)
        self.assertIn("sha256:cached_A", summaries[0].verdict)
        # The fresh digest is truncated to [:19] in the verdict, so check the
        # untruncated prefix "sha256:registry_C"
        self.assertIn("sha256:registry_C", summaries[0].verdict)

    # ------------------------------------------------------------------
    # _stack_convergence_block_reason unit tests
    # ------------------------------------------------------------------

    def test_convergence_passes_for_running_no_healthcheck(self):
        from app.schemas import ContainerSummary
        from app.services.snapshot import _stack_convergence_block_reason
        c = ContainerSummary(
            id="c1", name="web", image="nginx", image_id="sha256:x",
            state="running", status="Up", created=0,
            health=None,
        )
        self.assertIsNone(_stack_convergence_block_reason([c]))

    def test_convergence_passes_for_running_healthy(self):
        from app.schemas import ContainerSummary
        from app.services.snapshot import _stack_convergence_block_reason
        c = ContainerSummary(
            id="c1", name="web", image="nginx", image_id="sha256:x",
            state="running", status="Up", created=0,
            health={"Status": "healthy"},
        )
        self.assertIsNone(_stack_convergence_block_reason([c]))

    def test_convergence_blocks_on_created(self):
        from app.schemas import ContainerSummary
        from app.services.snapshot import _stack_convergence_block_reason
        c = ContainerSummary(
            id="c1", name="web", image="nginx", image_id="sha256:x",
            state="created", status="Created", created=0,
            health=None,
        )
        reason = _stack_convergence_block_reason([c])
        self.assertIsNotNone(reason)
        self.assertIn("created", reason)

    def test_convergence_blocks_on_health_starting(self):
        from app.schemas import ContainerSummary
        from app.services.snapshot import _stack_convergence_block_reason
        c = ContainerSummary(
            id="c1", name="web", image="nginx", image_id="sha256:x",
            state="running", status="Up", created=0,
            health={"Status": "starting"},
        )
        reason = _stack_convergence_block_reason([c])
        self.assertIsNotNone(reason)
        self.assertIn("starting", reason)

    def test_convergence_blocks_on_health_unhealthy(self):
        from app.schemas import ContainerSummary
        from app.services.snapshot import _stack_convergence_block_reason
        c = ContainerSummary(
            id="c1", name="web", image="nginx", image_id="sha256:x",
            state="running", status="Up", created=0,
            health={"Status": "unhealthy"},
        )
        reason = _stack_convergence_block_reason([c])
        self.assertIsNotNone(reason)
        self.assertIn("unhealthy", reason)

    def test_convergence_blocks_on_any_container_in_bad_state(self):
        """If one container is bad among several, the whole stack is not converged."""
        from app.schemas import ContainerSummary
        from app.services.snapshot import _stack_convergence_block_reason
        c1 = ContainerSummary(
            id="c1", name="web", image="nginx", image_id="sha256:x",
            state="running", status="Up", created=0, health=None,
        )
        c2 = ContainerSummary(
            id="c2", name="db", image="postgres", image_id="sha256:y",
            state="exited", status="Exited", created=0, health=None,
        )
        reason = _stack_convergence_block_reason([c1, c2])
        self.assertIsNotNone(reason)
        self.assertIn("exited", reason)


if __name__ == "__main__":
    unittest.main()
