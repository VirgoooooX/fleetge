import asyncio
import json
import os
import tempfile
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("CREDENTIALS_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_PASSWORD", "test-password")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.gettempdir()}/host_dashboard_test.db")

from app.models import AutoUpdateRun, HostConfig, StackAutoUpdate
from app.services import auto_update as module
from app.services.agent_client import AgentClient
from app.services.snapshot import HostSnapshot


class AutoUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch.object(module, "engine", self.engine)
        self.engine_patch.start()
        self.manager = module.AutoUpdateManager()
        self.snap = HostSnapshot()
        self.snap.host_config = HostConfig(host_id="nas", agent_url="http://agent", enabled=True)
        self.snap.status = "online"
        self.snap.stacks = [SimpleNamespace(name="app", status="running", compose_file=None, management_status="deployed")]
        self.snap.containers = [SimpleNamespace(stack_name="app", image="example/app:latest")]
        self.snap.update_results = {"example/app:latest": "updatable"}
        self.snap.update_check_results = [SimpleNamespace(image="example/app:latest", status="updatable", last_failure_status=None)]
        async def refresh_snapshot(*args, **kwargs):
            self.snap.containers_updated += 1

        self.snapshots = SimpleNamespace(
            get_snapshot=MagicMock(return_value=self.snap),
            refresh_host_docker=AsyncMock(side_effect=refresh_snapshot),
            finalize_stack_update=AsyncMock(return_value=[SimpleNamespace(image="example/app:latest", cleared=True, verified=True, verdict="digest matched")]),
        )
        self.manager.snapshots = lambda: self.snapshots
        self.conn = SimpleNamespace(get_self=AsyncMock(return_value={"stack_name": "fleetge"}), get_stack=AsyncMock(return_value={"stack": {"composeYAML": "services:\n  app:\n    image: example/app:latest\n"}}), close=AsyncMock(), _token="secret-token")
        self.agent_patch = patch.object(module, "AgentClient", return_value=self.conn)
        self.agent_patch.start()
        module.set_policy("nas", "app", True)
        self.manager.execute = AsyncMock(return_value=({"success": True, "stage": "up", "up_executed": True}, ""))
        self.sleep_patch = patch.object(module.asyncio, "sleep", new=AsyncMock())
        self.sleep = self.sleep_patch.start()

    async def asyncTearDown(self):
        self.sleep_patch.stop()
        self.agent_patch.stop()
        self.engine_patch.stop()
        self.engine.dispose()

    def run_record(self):
        with Session(self.engine) as session:
            return session.exec(select(AutoUpdateRun).order_by(AutoUpdateRun.id.desc())).first()

    async def run_update(self):
        await self.manager.run_stack("nas", "app", ["example/app:latest"])

    async def test_up_refreshes_old_healthy_snapshot_before_real_verification(self):
        from app.models import ImageUpdateCache
        from app.schemas import ContainerSummary
        from app.services.snapshot import SnapshotManager
        from app.services import snapshot as snapshot_module

        real_manager = SnapshotManager()
        real_manager._snapshots = {"nas": self.snap}
        with Session(self.engine) as session:
            session.add(ImageUpdateCache(host_id="nas", image="example/app:latest", current_digest="sha256:old", registry_digest="sha256:new", status="updatable"))
            session.commit()
        applied = False
        events = []

        async def execute(*args):
            nonlocal applied
            applied = True
            events.append("up")
            return {"success": True, "stage": "up", "up_executed": True}, ""

        async def refresh(*args, **kwargs):
            digest = "sha256:new" if applied else "sha256:old"
            self.snap.containers = [ContainerSummary(id="container", name="app", image="example/app:latest", image_id=digest, tag_image_id=digest, repo_digests=["example/app@" + digest], state="running", status="Up", created=0, stack_name="app", health={"Status": "healthy"})]
            self.snap.containers_updated += 1
            events.append("refresh-new" if applied else "refresh-old")

        async def finalize(*args, **kwargs):
            events.append("verify")
            return await real_manager.finalize_stack_update(*args, wait_timeout=0)

        self.manager.execute.side_effect = execute
        self.snapshots.refresh_host_docker.side_effect = refresh
        self.snapshots.finalize_stack_update.side_effect = finalize
        with patch.object(snapshot_module, "engine", self.engine):
            await self.run_update()
        self.assertEqual(events[:4], ["refresh-old", "up", "refresh-new", "verify"])
        self.assertEqual(self.run_record().status, "success")
        self.assertTrue(module.stack_policy("nas", "app").enabled)
        self.assertEqual(self.snap.update_results["example/app:latest"], "up_to_date")

    async def test_unavailable_post_update_snapshot_is_uncertain(self):
        async def refresh(*args, **kwargs):
            if not self.manager.execute.await_count:
                self.snap.containers_updated += 1
        self.snapshots.refresh_host_docker.side_effect = refresh
        await self.run_update()
        self.assertEqual(self.run_record().status, "uncertain")
        self.assertFalse(module.stack_policy("nas", "app").enabled)
        self.snapshots.finalize_stack_update.assert_not_awaited()

    async def test_latest_cache_is_not_a_substitute_for_health_verification(self):
        self.snap.update_results["example/app:latest"] = "updatable"
        async def finalize(*args, **kwargs):
            self.snap.update_results["example/app:latest"] = "up_to_date"
            return [SimpleNamespace(image="example/app:latest", cleared=False, verified=False, verdict="container is unhealthy")]
        self.snapshots.finalize_stack_update.side_effect = finalize
        await self.run_update()
        self.assertEqual(self.run_record().status, "failed")
        self.assertFalse(module.stack_policy("nas", "app").enabled)

    async def test_real_compose_is_required_even_for_a_deployed_stack(self):
        for detail in (None, {"stack": {"composeYAML": ""}}):
            self.conn.get_stack.return_value = detail
            await self.run_update()
        self.manager.execute.assert_not_awaited()
        self.assertIsNone(self.run_record())
        self.assertTrue(module.stack_policy("nas", "app").enabled)

    async def test_pull_failure_replays_existing_update_once_then_verifies(self):
        self.manager.execute.side_effect = [({"success": False, "stage": "pull"}, "first failed"), ({"success": True, "stage": "up", "up_executed": True}, "second succeeded")]
        await self.run_update()
        self.assertEqual(self.manager.execute.await_count, 2)
        self.sleep.assert_awaited_once_with(10)
        self.assertEqual(self.run_record().status, "success")
        self.assertEqual(self.run_record().attempts, 2)
        self.assertTrue(module.stack_policy("nas", "app").enabled)
        self.snapshots.finalize_stack_update.assert_awaited_once_with("nas", "app", ["example/app:latest"], wait_timeout=45.0)

    async def test_two_pull_failures_pause(self):
        self.manager.execute.return_value = ({"success": False, "stage": "pull"}, "registry failed")
        await self.run_update()
        self.assertEqual(self.manager.execute.await_count, 2)
        self.assertFalse(module.stack_policy("nas", "app").enabled)
        self.assertEqual(self.run_record().status, "failed")
        self.snapshots.finalize_stack_update.assert_not_awaited()

    async def test_up_failure_is_not_retried(self):
        self.manager.execute.return_value = ({"success": False, "stage": "up"}, "up failed")
        await self.run_update()
        self.manager.execute.assert_awaited_once()
        self.sleep.assert_not_awaited()
        self.assertFalse(module.stack_policy("nas", "app").enabled)

    async def test_legacy_failure_without_stage_is_not_retried(self):
        self.manager.execute.return_value = ({"success": False}, "unknown")
        await self.run_update()
        self.manager.execute.assert_awaited_once()
        self.assertEqual(self.run_record().status, "failed")

    async def test_connection_loss_pauses_as_uncertain_without_replay(self):
        self.manager.execute.return_value = ({"success": False, "interrupted": True}, "")
        await self.run_update()
        self.manager.execute.assert_awaited_once()
        self.assertEqual(self.run_record().status, "uncertain")
        self.assertFalse(module.stack_policy("nas", "app").enabled)

    async def test_failed_verification_pauses_despite_command_success(self):
        self.snapshots.finalize_stack_update.return_value = [SimpleNamespace(image="example/app:latest", cleared=False, verified=False, verdict="container is restarting")]
        await self.run_update()
        self.assertEqual(self.run_record().status, "failed")
        self.assertIn("restarting", module.stack_policy("nas", "app").reason)

    async def test_busy_and_skipped_up_do_not_disable(self):
        for result in ({"success": False, "error_code": "stack_busy"}, {"success": True, "up_executed": False}):
            self.manager.execute.return_value = (result, "")
            await self.run_update()
            self.assertEqual(self.run_record().status, "skipped")
            self.assertTrue(module.stack_policy("nas", "app").enabled)
            self.assertEqual(self.run_record().notify_status, "none")

    async def test_disabling_during_retry_wait_cancels_second_call(self):
        self.manager.execute.return_value = ({"success": False, "stage": "pull"}, "")
        async def disable(_):
            module.set_policy("nas", "app", False)
        self.sleep.side_effect = disable
        await self.run_update()
        self.manager.execute.assert_awaited_once()
        self.assertEqual(self.run_record().status, "skipped")

    async def test_stopped_partial_unmanaged_and_control_stacks_are_not_updated(self):
        for status in ("stopped", "partially running"):
            self.snap.stacks[0].status = status
            await self.run_update()
        self.snap.stacks[0].status = "running"
        self.snap.stacks[0].management_status = "unmanaged"
        await self.run_update()
        self.snap.stacks[0].management_status = "managed"
        self.snap.containers[0].image = "ghcr.io/virgooooox/fleetge:latest"
        await self.run_update()
        self.manager.execute.assert_not_awaited()
        self.assertIsNone(self.run_record())

    async def test_restart_does_not_replay_running_updates(self):
        with Session(self.engine) as session:
            session.add(AutoUpdateRun(host_id="nas", stack_name="app"))
            session.commit()
        self.manager.notification_loop = AsyncMock()
        await self.manager.start()
        await self.manager.stop()
        self.assertEqual(self.run_record().status, "uncertain")
        self.assertFalse(module.stack_policy("nas", "app").enabled)
        self.manager.execute.assert_not_awaited()

    async def test_notifications_are_optional_and_not_backfilled(self):
        await self.run_update()
        self.assertEqual(self.run_record().notify_status, "none")
        module.save_notify_settings("http://notify", "person_1", "nfy_testkey")
        self.assertEqual(self.run_record().notify_status, "none")

    async def test_notification_timeout_reuses_payload_and_event_key(self):
        module.save_notify_settings("http://notify", "person_1", "nfy_testkey")
        await self.run_update()
        original = self.run_record().notify_payload
        client = AsyncMock()
        client.post.side_effect = [httpx.ReadTimeout("timeout"), httpx.Response(202, json={"data": {"status": "accepted", "event_id": "evt_1", "duplicate": True}})]
        with patch.object(module.httpx, "AsyncClient") as factory:
            factory.return_value.__aenter__ = AsyncMock(return_value=client)
            factory.return_value.__aexit__ = AsyncMock()
            await self.manager.send_notifications()
            self.assertEqual(self.run_record().notify_status, "pending")
            with Session(self.engine) as session:
                row = session.get(AutoUpdateRun, self.run_record().id)
                row.notify_next_at = module.now_utc() - timedelta(seconds=1)
                session.add(row)
                session.commit()
            await self.manager.send_notifications()
        self.assertEqual(self.run_record().notify_status, "accepted")
        self.assertEqual(self.run_record().notify_payload, original)
        calls = client.post.await_args_list
        self.assertEqual(calls[0].kwargs["json"], calls[1].kwargs["json"])
        self.assertNotIn("nfy_testkey", original)

    async def test_unauthorized_notification_blocks_until_config_is_saved(self):
        module.save_notify_settings("http://notify", "person_1", "nfy_testkey")
        await self.run_update()
        client = AsyncMock()
        client.post.return_value = httpx.Response(403)
        with patch.object(module.httpx, "AsyncClient") as factory:
            factory.return_value.__aenter__ = AsyncMock(return_value=client)
            factory.return_value.__aexit__ = AsyncMock()
            await self.manager.send_notifications()
            await self.manager.send_notifications()
        self.assertEqual(client.post.await_count, 1)
        self.assertEqual(self.run_record().notify_status, "blocked")
        module.save_notify_settings("http://notify", "person_1", "nfy_fixed")
        self.assertEqual(self.run_record().notify_status, "pending")

    async def test_expired_notification_is_not_sent(self):
        module.save_notify_settings("http://notify", "person_1", "nfy_testkey")
        await self.run_update()
        with Session(self.engine) as session:
            row = session.get(AutoUpdateRun, self.run_record().id)
            row.notify_expires_at = module.now_utc() - timedelta(seconds=1)
            session.add(row)
            session.commit()
        client = AsyncMock()
        with patch.object(module.httpx, "AsyncClient") as factory:
            factory.return_value.__aenter__ = AsyncMock(return_value=client)
            factory.return_value.__aexit__ = AsyncMock()
            await self.manager.send_notifications()
        client.post.assert_not_awaited()
        self.assertEqual(self.run_record().notify_status, "expired")

    async def test_enqueue_deduplicates_and_ignores_failed_or_cached_checks(self):
        self.manager.started = True
        self.manager.run_host = AsyncMock()
        self.manager.enqueue("nas", [])
        self.assertFalse(self.manager.workers)
        self.snap.update_check_results[0].last_failure_status = "rate_limited"
        self.manager.enqueue("nas", ["example/app:latest"])
        self.assertFalse(self.manager.workers)
        self.snap.update_check_results[0].last_failure_status = None
        self.manager.active.add(("nas", "app"))
        self.manager.enqueue("nas", ["example/app:latest"])
        self.assertFalse(self.manager.workers)
        self.manager.active.clear()
        self.manager.enqueue("nas", ["example/app:latest"])
        self.manager.enqueue("nas", ["example/app:latest"])
        self.assertEqual(len(self.manager.pending["nas"]), 1)
        self.assertEqual(len(self.manager.workers), 1)
        await asyncio.gather(*self.manager.workers.values())

    async def test_notify_settings_encrypt_key_and_clear_explicitly(self):
        module.save_notify_settings("http://notify/", "person_1", "nfy_testkey")
        config = module.notify_settings()
        self.assertEqual(config["NOTIFYHUB_URL"], "http://notify")
        self.assertNotIn("nfy_testkey", config["NOTIFYHUB_KEY"])
        module.save_notify_settings("http://notify", "person_1", None)
        self.assertEqual(config["NOTIFYHUB_KEY"], module.notify_settings()["NOTIFYHUB_KEY"])
        module.save_notify_settings("http://notify", "person_1", "")
        self.assertFalse(module.notify_settings()["NOTIFYHUB_KEY"])
        for url in ("file:///tmp", "http://user:password@notify", "http://notify?token=secret"):
            with self.assertRaises(ValueError):
                module.save_notify_settings(url, "person_1", None)


class AgentUpdateResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_preserves_phase_and_does_not_treat_eof_as_success(self):
        import websockets
        conn = AgentClient(HostConfig(host_id="h", agent_url="http://agent"))
        try:
            for message, expected in [
                ({"type": "exit", "code": 1, "stage": "pull", "up_executed": False}, False),
                ({"type": "exit", "code": 0, "stage": "up", "up_executed": True}, True),
                (None, False),
            ]:
                ws = AsyncMock()
                if message is None:
                    ws.recv.side_effect = websockets.ConnectionClosed(None, None)
                else:
                    ws.recv.return_value = json.dumps(message)
                context = MagicMock()
                context.__aenter__ = AsyncMock(return_value=ws)
                context.__aexit__ = AsyncMock()
                with patch.object(conn, "_connect_websocket", return_value=context):
                    result = await conn.stack_action("app", "updateStack")
                self.assertEqual(result["success"], expected)
                if message:
                    self.assertEqual(result["stage"], message["stage"])
                else:
                    self.assertTrue(result["interrupted"])
        finally:
            await conn.close()


class BulkUpdateExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch.object(module, "engine", self.engine)
        self.engine_patch.start()
        self.manager = module.AutoUpdateManager()
        self.manager.started = True
        self.snap = HostSnapshot()
        self.snap.host_config = HostConfig(host_id="nas", agent_url="http://agent", enabled=True)
        self.snap.status = "online"
        self.snap.stacks = [
            SimpleNamespace(name="s1", status="running", compose_file=None, management_status="managed"),
            SimpleNamespace(name="s2", status="running", compose_file=None, management_status="managed"),
            SimpleNamespace(name="s3", status="running", compose_file=None, management_status="managed"),
        ]
        self.snap.containers = [
            SimpleNamespace(stack_name="s1", image="img1:latest", state="running", service_name="app1"),
            SimpleNamespace(stack_name="s2", image="img2:latest", state="running", service_name="app2"),
            SimpleNamespace(stack_name="s3", image="img3:latest", state="running", service_name="app3"),
        ]
        self.snap.update_results = {"img1:latest": "updatable", "img2:latest": "updatable", "img3:latest": "updatable"}
        self.snap.update_check_results = []
        async def refresh_snapshot(*args, **kwargs):
            self.snap.containers_updated += 1

        self.snapshots = SimpleNamespace(
            get_snapshot=MagicMock(return_value=self.snap),
            refresh_host_docker=AsyncMock(side_effect=refresh_snapshot),
            finalize_stack_update=AsyncMock(),
        )
        self.manager.snapshots = lambda: self.snapshots
        self.conn = SimpleNamespace(
            get_self=AsyncMock(return_value={"stack_name": "fleetge"}),
            get_stack=AsyncMock(return_value={"stack": {"composeYAML": "services:\n  app:\n    image: test\n"}}),
            close=AsyncMock(),
            _token="token",
        )
        self.agent_patch = patch.object(module, "AgentClient", return_value=self.conn)
        self.agent_patch.start()

    async def asyncTearDown(self):
        await self.manager.stop()
        self.agent_patch.stop()
        self.engine_patch.stop()
        self.engine.dispose()

    async def test_bulk_continues_after_failure_and_stops_after_uncertain(self):
        # s1 fails (not retryable up failure), s2 is uncertain (interrupted), s3 should be skipped
        async def fake_execute(conn, stack_name, run_id=None):
            if stack_name == "s1":
                return {"success": False, "stage": "up"}, ""
            if stack_name == "s2":
                return {"success": False, "interrupted": True}, ""
            return {"success": True, "stage": "up", "up_executed": True}, ""

        self.manager.execute = fake_execute

        req_id = "22222222-2222-2222-2222-222222222222"
        await self.manager.submit("nas", req_id, "bulk", ["s1", "s2", "s3"], "admin")

        # Wait for worker to finish
        worker = self.manager.workers.get("nas")
        if worker:
            await worker

        batch = self.manager.get_batch("nas", req_id)
        self.assertTrue(batch["finished"])
        items = {item["stack_name"]: item for item in batch["items"]}
        self.assertEqual(items["s1"]["status"], "failed")
        self.assertEqual(items["s2"]["status"], "uncertain")
        self.assertEqual(items["s3"]["status"], "skipped")
        self.assertIn("结果未确认", items["s3"]["detail"])

    async def test_bulk_continues_and_succeeds_when_second_is_success(self):
        # s1 fails, s2 succeeds, s3 succeeds
        async def fake_execute(conn, stack_name, run_id=None):
            if stack_name == "s1":
                return {"success": False, "stage": "up"}, ""
            return {"success": True, "stage": "up", "up_executed": True}, ""

        self.snapshots.finalize_stack_update.return_value = [
            SimpleNamespace(image="img", cleared=True, verified=True, verdict="ok")
        ]
        self.manager.execute = fake_execute

        req_id = "33333333-3333-3333-3333-333333333333"
        await self.manager.submit("nas", req_id, "bulk", ["s1", "s2", "s3"], "admin")

        worker = self.manager.workers.get("nas")
        if worker:
            await worker

        batch = self.manager.get_batch("nas", req_id)
        self.assertTrue(batch["finished"])
        items = {item["stack_name"]: item for item in batch["items"]}
        self.assertEqual(items["s1"]["status"], "failed")
        self.assertEqual(items["s2"]["status"], "success")
        self.assertEqual(items["s3"]["status"], "success")
