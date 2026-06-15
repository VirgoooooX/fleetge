import asyncio
import os
import tempfile
import unittest

os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault(
    "CREDENTIALS_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
os.environ.setdefault("ADMIN_PASSWORD_HASH", "test-password-hash")
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(tempfile.gettempdir(), 'host_dashboard_test.db')}",
)

from app.schemas import UpdateCheckResult
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


if __name__ == "__main__":
    unittest.main()
