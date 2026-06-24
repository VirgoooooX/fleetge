import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
from app.services import update_check as update_check_module





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

    def test_failed_update_cache_rows_are_hidden_from_visible_snapshot_index(self):
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

        self.assertEqual(len(snap.update_check_results), 1)
        self.assertEqual(snap.update_check_results[0].status, "check_failed")
        self.assertEqual(snap.update_results, {})
        self.assertEqual(snap.update_count, 0)

    def test_get_update_check_results_can_include_failures(self):
        manager = SnapshotManager()
        snap = HostSnapshot()
        snap.update_check_results = [
            UpdateCheckResult(
                host_id="host-a",
                image="nginx:latest",
                status="check_failed",
            ),
            UpdateCheckResult(
                host_id="host-a",
                image="postgres:16",
                status="updatable",
            ),
        ]
        manager._snapshots = {"host-a": snap}

        visible = manager.get_update_check_results()
        all_results = manager.get_update_check_results(include_failures=True)

        self.assertEqual([item.status for item in visible], ["updatable"])
        self.assertEqual(
            [item.status for item in all_results],
            ["check_failed", "updatable"],
        )

    def test_first_updatable_result_is_pending_and_hidden(self):
        manager = SnapshotManager()
        session = MagicMock()
        now = datetime.now(timezone.utc)
        result = UpdateCheckResult(
            host_id="host-a",
            image="nginx:latest",
            status="updatable",
            current_digest="sha256:old",
            registry_digest="sha256:new",
        )

        row = manager._persist_update_check_result(
            session,
            "host-a",
            result,
            None,
            now,
        )

        self.assertEqual(row.status, "pending_update")
        self.assertEqual(row.pending_current_digest, "sha256:old")
        self.assertEqual(row.pending_registry_digest, "sha256:new")

        snap = HostSnapshot()
        manager._apply_update_cache_rows_to_snapshot(snap, [row])
        self.assertEqual(snap.update_results, {})
        self.assertEqual(snap.update_count, 0)

    def test_matching_second_updatable_result_is_published(self):
        manager = SnapshotManager()
        now = datetime.now(timezone.utc)
        existing = ImageUpdateCache(
            host_id="host-a",
            image="nginx:latest",
            status="pending_update",
            current_digest="sha256:old",
            registry_digest="sha256:new",
            pending_current_digest="sha256:old",
            pending_registry_digest="sha256:new",
            pending_detected_at=now - timedelta(hours=1),
            checked_at=now - timedelta(hours=1),
        )
        result = UpdateCheckResult(
            host_id="host-a",
            image="nginx:latest",
            status="updatable",
            current_digest="sha256:old",
            registry_digest="sha256:new",
        )

        row = manager._persist_update_check_result(
            MagicMock(),
            "host-a",
            result,
            existing,
            now,
        )

        self.assertEqual(row.status, "updatable")
        self.assertIsNone(row.pending_registry_digest)

        snap = HostSnapshot()
        manager._apply_update_cache_rows_to_snapshot(snap, [row])
        self.assertEqual(snap.update_results, {"nginx:latest": "updatable"})
        self.assertEqual(snap.update_count, 1)

    def test_pending_update_rows_are_due_after_confirmation_interval(self):
        manager = SnapshotManager()
        now = datetime.now(timezone.utc)
        row = ImageUpdateCache(
            host_id="host-a",
            image="nginx:latest",
            status="pending_update",
            current_digest="sha256:old",
            registry_digest="sha256:new",
            pending_current_digest="sha256:old",
            pending_registry_digest="sha256:new",
            pending_detected_at=now - timedelta(seconds=3599),
            checked_at=now,
        )

        self.assertFalse(
            manager._is_update_cache_due(
                row,
                now,
                timedelta(hours=6),
                force=False,
            )
        )
        self.assertTrue(
            manager._is_update_cache_due(
                row,
                now + timedelta(seconds=2),
                timedelta(hours=6),
                force=False,
            )
        )

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
            status="rate_limited",
            http_status=429,
            retry_after=120,
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
        self.assertEqual(existing.last_failure_status, "rate_limited")
        self.assertEqual(existing.last_failure_http_status, 429)
        self.assertEqual(existing.last_failure_retry_after, 120)

        snap = HostSnapshot()
        manager._apply_update_cache_rows_to_snapshot(snap, [existing])
        self.assertEqual(snap.update_check_results[0].status, "updatable")
        self.assertEqual(snap.update_check_results[0].last_failure_status, "rate_limited")
        self.assertEqual(snap.update_check_results[0].last_failure_retry_after, 120)

    def test_rate_limited_cache_rows_respect_retry_after(self):
        manager = SnapshotManager()
        now = datetime.now(timezone.utc)
        row = ImageUpdateCache(
            host_id="host-a",
            image="nginx:latest",
            status="rate_limited",
            retry_after=120,
            checked_at=now - timedelta(seconds=119),
        )

        self.assertFalse(
            manager._is_update_cache_due(
                row,
                now,
                timedelta(seconds=1),
                force=False,
            )
        )
        self.assertTrue(
            manager._is_update_cache_due(
                row,
                now + timedelta(seconds=2),
                timedelta(seconds=1),
                force=False,
            )
        )

    def test_visible_cache_with_recent_failure_respects_retry_after(self):
        manager = SnapshotManager()
        now = datetime.now(timezone.utc)
        row = ImageUpdateCache(
            host_id="host-a",
            image="nginx:latest",
            status="updatable",
            current_digest="sha256:old",
            registry_digest="sha256:new",
            checked_at=now - timedelta(days=1),
            last_failure_status="rate_limited",
            last_failure_retry_after=120,
            last_failure_at=now - timedelta(seconds=119),
        )

        self.assertFalse(
            manager._is_update_cache_due(
                row,
                now,
                timedelta(seconds=1),
                force=False,
            )
        )
        self.assertTrue(
            manager._is_update_cache_due(
                row,
                now + timedelta(seconds=2),
                timedelta(seconds=1),
                force=False,
            )
        )

    def test_match_profile_priority(self):
        manager = SnapshotManager()
        profiles = [
            {"stack_pattern": "*app", "title": "Suffix Match"},
            {"stack_pattern": "my*", "title": "Prefix Match"},
            {"stack_pattern": "myapp", "title": "Exact Match"},
        ]
        # Exact match should take highest priority
        matched = manager._match_profile("myapp", profiles)
        self.assertEqual(matched["title"], "Exact Match")

        # Prefix wildcard should take priority over suffix wildcard
        profiles_no_exact = [
            {"stack_pattern": "*app", "title": "Suffix Match"},
            {"stack_pattern": "my*", "title": "Prefix Match"},
        ]
        matched_prefix = manager._match_profile("myapp", profiles_no_exact)
        self.assertEqual(matched_prefix["title"], "Prefix Match")

        # Suffix wildcard matches
        profiles_only_suffix = [
            {"stack_pattern": "*app", "title": "Suffix Match"},
        ]
        matched_suffix = manager._match_profile("myapp", profiles_only_suffix)
        self.assertEqual(matched_suffix["title"], "Suffix Match")


class SnapshotManagerAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = SnapshotManager()
        update_check_module.reset_runtime_state()
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

    async def test_try_refresh_coalesces_concurrent_manual_runs(self):
        """A second manual /run while one is in flight returns started=False,
        and does NOT trigger a second full sweep (no extra registry traffic)."""
        call_count = {"n": 0}
        started_event = asyncio.Event()

        original_locked = self.manager._refresh_update_checks_locked

        async def counting_locked(force: bool = False) -> None:
            call_count["n"] += 1
            # Hold the sweep open so the second try_ lands while it is running.
            if force:
                try:
                    await asyncio.wait_for(started_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
            await original_locked(force=force)

        self.manager._refresh_update_checks_locked = counting_locked

        async def run_manual():
            return await self.manager.try_refresh_update_checks_now()

        first = asyncio.create_task(run_manual())
        # Let the first task reach the in-flight sweep. The running flag is set
        # before any await inside the sweep, so a short yield is enough.
        await asyncio.sleep(0.05)
        second = asyncio.create_task(run_manual())

        # The second call must resolve quickly with started=False, without waiting
        # for the first sweep to finish.
        try:
            await asyncio.wait_for(asyncio.shield(second), timeout=0.5)
        except asyncio.TimeoutError:
            started_event.set()
            await first
            self.fail("Second manual /run queued behind the first instead of coalescing")

        started2, _results2 = second.result()
        self.assertFalse(started2)

        # Release the first sweep and let it finish.
        started_event.set()
        started1, _results1 = await first
        self.assertTrue(started1)

        # Exactly one full sweep ran — the second trigger did not duplicate work.
        self.assertEqual(call_count["n"], 1)

    async def test_background_loop_yields_to_in_flight_manual_run(self):
        """A background poll (force=False) arriving while a manual run is in
        flight is skipped, so it does not queue a second sweep behind it."""
        call_count = {"n": 0}
        started_event = asyncio.Event()

        original_locked = self.manager._refresh_update_checks_locked

        async def counting_locked(force: bool = False) -> None:
            call_count["n"] += 1
            if force:
                try:
                    await asyncio.wait_for(started_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
            await original_locked(force=force)

        self.manager._refresh_update_checks_locked = counting_locked

        manual = asyncio.create_task(self.manager.try_refresh_update_checks_now())
        await asyncio.sleep(0.05)
        # Background tick fires while the manual run holds the flag.
        await self.manager._refresh_update_checks(force=False)

        started_event.set()
        started, _ = await manual
        self.assertTrue(started)
        # Only the manual (force=True) sweep ran; the background one was skipped.
        self.assertEqual(call_count["n"], 1)

    async def test_manual_run_yields_to_in_flight_background_run(self):
        """A manual /run arriving after the background sweep has started returns
        started=False and does not queue a force=True sweep behind it."""
        call_count = {"n": 0}
        release_event = asyncio.Event()

        original_locked = self.manager._refresh_update_checks_locked

        async def counting_locked(force: bool = False) -> None:
            call_count["n"] += 1
            if not force:
                try:
                    await asyncio.wait_for(release_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
            await original_locked(force=force)

        self.manager._refresh_update_checks_locked = counting_locked

        background = asyncio.create_task(self.manager._refresh_update_checks(force=False))
        await asyncio.sleep(0.05)

        started, _ = await asyncio.wait_for(
            self.manager.try_refresh_update_checks_now(),
            timeout=0.5,
        )
        self.assertFalse(started)

        release_event.set()
        background_started = await background
        self.assertTrue(background_started)
        self.assertEqual(call_count["n"], 1)

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

    async def test_forced_update_check_uses_fresh_registry_lookup(self):
        from app.services import update_check

        with patch("app.services.update_check._lookup_registry_identity", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = update_check.RegistryLookupResult(
                digests=update_check.RegistryDigests(repo_digests=["sha256:new"]),
            )
            result = await update_check.check_image(
                self.host_id,
                "nginx:latest",
                ["nginx:latest@sha256:old"],
                force=True,
            )

        mock_lookup.assert_called_once()
        self.assertEqual(result.status, "updatable")
        self.assertEqual(result.registry_digest, "sha256:new")
        self.assertEqual(result.matched_field, None)

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

    async def test_update_check_accepts_single_manifest_repodigest_match(self):
        """Single-manifest tags may only match Docker-Content-Digest via RepoDigest."""
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
                if url == "https://registry-1.docker.io/v2/80x86/filebrowser/manifests/2.9.4-amd64":
                    return FakeResponse(
                        200,
                        {
                            "Content-Type": "application/vnd.docker.distribution.manifest.v2+json",
                            "Docker-Content-Digest": "sha256:manifest-digest",
                        },
                        {
                            "schemaVersion": 2,
                            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                            "config": {"digest": "sha256:config-digest"},
                        },
                    )
                return FakeResponse(404)

        with patch("app.services.update_check.httpx.AsyncClient", return_value=FakeClient()):
            result = await update_check.check_image(
                self.host_id,
                "80x86/filebrowser:2.9.4-amd64",
                ["80x86/filebrowser@sha256:manifest-digest"],
                local_image_id="sha256:local-image-id",
                platform="linux/amd64",
                force=True,
            )

        self.assertEqual(result.status, "up_to_date")
        self.assertEqual(result.registry_digest, "sha256:manifest-digest")
        self.assertEqual(result.matched_field, "repo_digest")

    async def test_digest_pinned_image_skips_registry_lookup(self):
        from app.services import update_check

        with patch("app.services.update_check._lookup_registry_identity", new_callable=AsyncMock) as mock_lookup:
            result = await update_check.check_image(
                self.host_id,
                "ghcr.io/example/app@sha256:pinned-digest",
                ["ghcr.io/example/app@sha256:pinned-digest"],
                local_image_id="sha256:local-image-id",
                force=True,
            )

        mock_lookup.assert_not_called()
        self.assertEqual(result.status, "up_to_date")
        self.assertEqual(result.registry_digest, "sha256:pinned-digest")
        self.assertEqual(result.matched_field, "pinned_digest")

    async def test_registry_rate_limit_freezes_same_registry(self):
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
                        response=update_check.httpx.Response(
                            self.status_code,
                            headers=self.headers,
                        ),
                    )

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def get(self, url, headers=None, params=None, timeout=None):
                self.calls.append(url)
                if url.startswith("https://auth.docker.io/token"):
                    return FakeResponse(429, headers={"Retry-After": "120"})
                return FakeResponse(404)

        fake_client = FakeClient()
        with patch("app.services.update_check.httpx.AsyncClient", return_value=fake_client):
            first = await update_check._lookup_registry_identity(
                "docker.io",
                "library/nginx",
                "latest",
            )
            second = await update_check._lookup_registry_identity(
                "docker.io",
                "library/nginx",
                "latest",
            )

        self.assertEqual(first.error_status, "rate_limited")
        self.assertEqual(first.retry_after, 120)
        self.assertEqual(second.error_status, "rate_limited")
        self.assertGreaterEqual(second.retry_after or 0, 1)
        self.assertEqual(len(fake_client.calls), 1)

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
        self.assertIn("sha256:cached_a", summaries[0].verdict)
        # The fresh digest is truncated to [:19] in the verdict, so check the
        # untruncated prefix "sha256:registry_C"
        self.assertIn("sha256:registry_c", summaries[0].verdict)

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
