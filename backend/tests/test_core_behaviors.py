import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

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
from app.services.dockge_client import DockgeClientError, DockgeConnection
from app.services.snapshot import HostSnapshot, SnapshotManager


class FakeSocket:
    def __init__(self, result):
        self.result = result

    async def call(self, *_args, **_kwargs):
        return self.result


class DockgeClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_call_unwraps_error_first_success(self):
        conn = DockgeConnection.__new__(DockgeConnection)
        conn._connected = True
        conn._sio = FakeSocket([None, {"ok": True, "value": 42}])
        conn._endpoint = ""
        conn._host_id = "test-host"

        result = await conn._agent_call("getStack", "demo")

        self.assertEqual(result, {"ok": True, "value": 42})

    async def test_agent_call_keeps_bare_single_item_list(self):
        conn = DockgeConnection.__new__(DockgeConnection)
        conn._connected = True
        conn._sio = FakeSocket([{"name": "svc"}])
        conn._endpoint = ""
        conn._host_id = "test-host"

        result = await conn._agent_call("serviceStatusList", "demo")

        self.assertEqual(result, [{"name": "svc"}])

    async def test_run_with_terminal_concurrent_reject_sends_sentinel(self):
        conn = DockgeConnection.__new__(DockgeConnection)
        conn._host_id = "test-host"
        conn._endpoint = ""
        conn._terminal_monitors = {
            "compose--demo": {"future": None, "queue": None, "buffer": []}
        }
        queue = asyncio.Queue()

        with self.assertRaises(DockgeClientError):
            await conn._run_with_terminal("demo", "updateStack", "demo", log_queue=queue)

        self.assertIsNone(await queue.get())

    async def test_save_stack_for_new_stack_sets_is_add(self):
        conn = DockgeConnection.__new__(DockgeConnection)
        calls = []

        async def fake_agent_call(event, *args, **kwargs):
            calls.append((event, args, kwargs))
            return {"ok": True}

        conn._agent_call = fake_agent_call

        result = await conn.save_stack(
            "new-stack",
            "services:\n  app:\n    image: nginx:latest\n",
            "",
            is_add=True,
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls[0][0], "saveStack")
        self.assertEqual(calls[0][1][3], True)


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
            dockge_url="http://localhost:5001",
            docker_proxy_url="http://localhost:2375",
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


if __name__ == "__main__":
    unittest.main()
