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

from app.models import AutoUpdateRun, HostConfig, ImageUpdateCache, StackAutoUpdate
from app.schemas import ContainerSummary, UpdateCheckResult
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
        self.snap.containers = [ContainerSummary(id="container", name="app", stack_name="app", service_name="app",
            image="example/app:latest", image_id="sha256:old", image_config_digest="sha256:old",
            platform="linux/amd64", state="running", status="Up", created=0)]
        self.snap.update_results = {"example/app:latest": "updatable"}
        self.snap.update_check_results = [UpdateCheckResult(
            host_id="nas", image="example/app:latest", status="updatable",
            registry_config_digest="sha256:new", registry_digest="sha256:new", platform="linux/amd64",
        )]
        with Session(self.engine) as session:
            session.add(ImageUpdateCache(host_id="nas", image="example/app:latest", status="updatable",
                registry_config_digest="sha256:new", registry_digest="sha256:new", platform="linux/amd64"))
            session.commit()
        async def refresh_snapshot(*args, **kwargs):
            self.snap.containers_updated += 1

        self.snapshots = SimpleNamespace(
            get_snapshot=MagicMock(return_value=self.snap),
            refresh_host_docker=AsyncMock(side_effect=refresh_snapshot),
            verify_update_targets=AsyncMock(return_value=("success", "registry targets matched")),
        )
        self.manager.snapshots = lambda: self.snapshots
        self.conn = SimpleNamespace(get_self=AsyncMock(return_value={"stack_name": "fleetge"}), get_stack=AsyncMock(return_value={"stack": {"composeYAML": "services:\n  app:\n    image: example/app:latest\n"}}), close=AsyncMock(), _token="secret-token")
        self.agent_patch = patch.object(module, "AgentClient", return_value=self.conn)
        self.agent_patch.start()
        module.set_policy("nas", "app", True)
        self.success = {"success": True, "stage": "up", "up_executed": True, "pulled_images": [
            {"service": "app", "image": "example/app:latest", "image_id": "sha256:new", "platform": "linux/amd64"},
        ]}
        self.manager.execute = AsyncMock(return_value=(self.success, ""))
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
        from app.services.snapshot import SnapshotManager
        from app.services import snapshot as snapshot_module

        real_manager = SnapshotManager()
        real_manager._snapshots = {"nas": self.snap}
        applied = False
        events = []

        async def execute(*args, **kwargs):
            nonlocal applied
            applied = True
            events.append("up")
            return self.success, ""

        async def refresh(*args, **kwargs):
            digest = "sha256:new" if applied else "sha256:old"
            self.snap.containers[0].image_id = digest
            self.snap.containers[0].image_config_digest = digest
            self.snap.containers_updated += 1
            events.append("refresh-new" if applied else "refresh-old")

        async def verify(*args, **kwargs):
            events.append("verify")
            return await real_manager.verify_update_targets(*args, wait_timeout=0, **kwargs)

        self.manager.execute.side_effect = execute
        self.snapshots.refresh_host_docker.side_effect = refresh
        real_manager.refresh_host_docker = self.snapshots.refresh_host_docker
        self.snapshots.verify_update_targets.side_effect = verify
        result = UpdateCheckResult(host_id="nas", image="example/app:latest", status="up_to_date",
            current_digest="sha256:new", registry_digest="sha256:new", registry_config_digest="sha256:new", platform="linux/amd64")
        with patch.object(snapshot_module, "engine", self.engine), patch.object(snapshot_module, "run_update_check", new=AsyncMock(return_value=[result])):
            await self.run_update()
        self.assertEqual(events[:4], ["refresh-old", "up", "verify", "refresh-new"])
        self.assertEqual(self.run_record().status, "success")
        self.assertTrue(module.stack_policy("nas", "app").enabled)
        self.assertEqual(self.snap.update_results["example/app:latest"], "up_to_date")

    async def test_unavailable_post_update_snapshot_is_uncertain(self):
        from app.services.snapshot import SnapshotManager
        real_manager = SnapshotManager()
        real_manager._snapshots = {"nas": self.snap}
        async def refresh(*args, **kwargs):
            if not self.manager.execute.await_count:
                self.snap.containers_updated += 1
        async def verify(*args, **kwargs):
            return await real_manager.verify_update_targets(*args, wait_timeout=0, **kwargs)
        self.snapshots.refresh_host_docker.side_effect = refresh
        real_manager.refresh_host_docker = self.snapshots.refresh_host_docker
        self.snapshots.verify_update_targets.side_effect = verify
        await self.run_update()
        self.assertEqual(self.run_record().status, "uncertain")
        self.assertFalse(module.stack_policy("nas", "app").enabled)

    async def test_latest_cache_is_not_a_substitute_for_health_verification(self):
        async def verify(*args, **kwargs):
            self.snap.update_results["example/app:latest"] = "up_to_date"
            return "failed", "container is unhealthy"
        self.snapshots.verify_update_targets.side_effect = verify
        await self.run_update()
        self.assertEqual(self.run_record().status, "failed")
        self.assertFalse(module.stack_policy("nas", "app").enabled)

    async def test_incomplete_agent_evidence_cannot_report_success(self):
        for result in ({"success": True, "stage": "up", "up_executed": True},
                       {"success": True, "stage": "up", "pulled_images": self.success["pulled_images"]}):
            module.set_policy("nas", "app", True)
            self.manager.execute.return_value = (result, "")
            await self.run_update()
            self.assertEqual(self.run_record().status, "uncertain")
        self.snapshots.verify_update_targets.assert_not_awaited()

    async def test_real_compose_is_required_even_for_a_deployed_stack(self):
        for detail in (None, {"stack": {"composeYAML": ""}}):
            self.conn.get_stack.return_value = detail
            await self.run_update()
        self.manager.execute.assert_not_awaited()
        self.assertIsNone(self.run_record())
        self.assertTrue(module.stack_policy("nas", "app").enabled)

    async def test_pull_failure_replays_existing_update_once_then_verifies(self):
        self.manager.execute.side_effect = [({"success": False, "stage": "pull"}, "first failed"), (self.success, "second succeeded")]
        await self.run_update()
        self.assertEqual(self.manager.execute.await_count, 2)
        self.sleep.assert_awaited_once_with(10)
        self.assertEqual(self.run_record().status, "success")
        self.assertEqual(self.run_record().attempts, 2)
        self.assertNotIn("attempt", self.run_record().log_tail)
        self.assertEqual(self.run_record().log_tail.count("重试一次"), 1)
        self.assertTrue(module.stack_policy("nas", "app").enabled)
        self.snapshots.verify_update_targets.assert_awaited_once()
        self.assertEqual(self.snapshots.verify_update_targets.await_args.args[2]["app"]["image_id"], "sha256:new")

    async def test_live_update_keeps_terminal_frames_and_persists_logs_once(self):
        chunks = ["\x1b[32mPulling\x1b[0m\r\n", "\x1b[1A\x1b[2KDownloaded\r\n", "Container app Started secret-token\r\n"]
        async def action(name, action, log_queue, services):
            self.assertEqual(action, "updateServices")
            self.assertEqual(services, ["app"])
            for chunk in chunks:
                await log_queue.put(chunk)
            await log_queue.put(None)
            return self.success
        self.conn.stack_action = action
        self.manager.execute = module.AutoUpdateManager.execute.__get__(self.manager)
        await self.run_update()
        run = self.run_record()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.log_tail.count("attempt 1"), 0)
        self.assertNotIn("重试", run.log_tail)
        self.assertEqual(run.log_tail.count("Downloaded"), 1)
        self.assertNotIn("secret-token", run.log_tail)
        self.assertNotIn("\x1b", run.log_tail)
        frames = self.manager.read_run_output(run.id)
        raw = "".join(text for _, text in frames)
        self.assertIn("\x1b[1A\x1b[2KDownloaded", raw)
        self.assertNotIn("secret-token", raw)
        self.assertEqual(raw.count("Downloaded"), 1)
        after = frames[-1][0]
        self.assertEqual(self.manager.read_run_output(run.id, after), [])

    async def test_two_pull_failures_pause(self):
        self.manager.execute.return_value = ({"success": False, "stage": "pull"}, "registry failed")
        await self.run_update()
        self.assertEqual(self.manager.execute.await_count, 2)
        self.assertFalse(module.stack_policy("nas", "app").enabled)
        self.assertEqual(self.run_record().status, "failed")
        self.snapshots.verify_update_targets.assert_not_awaited()

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
        self.snapshots.verify_update_targets.return_value = ("failed", "container is restarting")
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

    async def test_local_image_failure_does_not_block_database_update(self):
        local = self.snap.containers[0].model_copy(update={
            "id": "local", "name": "local-app", "service_name": "local-app", "image": "family-health:local",
        })
        self.snap.containers.insert(0, local)
        self.snap.update_check_results.append(UpdateCheckResult(host_id="nas", image=local.image, status="needs_auth"))
        await self.run_update()
        self.manager.execute.assert_awaited_once()
        self.assertEqual(self.manager.execute.await_args.kwargs["services"], ["app"])
        results = json.loads(self.run_record().targets_json)["results"]
        self.assertEqual(results["local-app"]["status"], "skipped")
        self.assertEqual(results["app"]["status"], "success")
        self.assertEqual(self.run_record().status, "success")

    async def test_failed_service_does_not_block_next_service_and_reports_partial(self):
        self.snap.containers.append(self.snap.containers[0].model_copy(update={
            "id": "second", "name": "db", "service_name": "db", "image": "postgres:16-alpine",
        }))
        self.snap.update_results["postgres:16-alpine"] = "updatable"
        self.snap.update_check_results.append(UpdateCheckResult(
            host_id="nas", image="postgres:16-alpine", status="updatable",
            registry_config_digest="sha256:db-new", platform="linux/amd64",
        ))
        db_success = {"success": True, "up_executed": True, "stage": "up", "pulled_images": [
            {"service": "db", "image": "postgres:16-alpine", "image_id": "sha256:db-new", "platform": "linux/amd64"},
        ]}
        self.manager.execute.side_effect = [({"success": False, "stage": "pull"}, "")] * 2 + [(db_success, "")]
        await self.run_update()
        self.assertEqual([call.kwargs["services"] for call in self.manager.execute.await_args_list], [["app"], ["app"], ["db"]])
        run = self.run_record()
        self.assertEqual(run.status, "partial")
        results = json.loads(run.targets_json)["results"]
        self.assertEqual(results["app"]["status"], "failed")
        self.assertEqual(results["db"]["status"], "success")
        self.assertIn("部分成功", run.detail)

    async def test_no_update_or_missing_cached_identity_never_executes(self):
        self.snap.update_results.clear()
        await self.run_update()
        self.manager.execute.assert_not_awaited()
        self.snap.update_results["example/app:latest"] = "updatable"
        self.snap.update_check_results[0].registry_config_digest = None
        await self.run_update()
        self.manager.execute.assert_not_awaited()
        self.assertEqual(self.run_record().status, "skipped")

    async def test_only_old_service_is_selected_when_services_share_a_tag(self):
        self.snap.containers.append(self.snap.containers[0].model_copy(update={
            "id": "current", "name": "current", "service_name": "current", "image_config_digest": "sha256:new",
        }))
        await self.run_update()
        self.manager.execute.assert_awaited_once()
        self.assertEqual(self.manager.execute.await_args.kwargs["services"], ["app"])

    async def test_frozen_target_survives_cache_changes_during_pull(self):
        async def execute(*args, **kwargs):
            self.snap.update_check_results[0].registry_config_digest = "sha256:next"
            return self.success, ""
        self.manager.execute.side_effect = execute
        await self.run_update()
        target = self.snapshots.verify_update_targets.await_args.args[2]["app"]["cached_target"]
        self.assertEqual(target["registry_config_digest"], "sha256:new")

    async def test_control_stack_uses_cache_and_isolates_service_jobs(self):
        self.snap.containers.append(self.snap.containers[0].model_copy(update={
            "id": "agent", "name": "agent", "service_name": "agent", "image": "agent:latest",
        }))
        self.snap.update_results["agent:latest"] = "updatable"
        self.snap.update_check_results.append(UpdateCheckResult(
            host_id="nas", image="agent:latest", status="updatable",
            registry_config_digest="sha256:agent-new", platform="linux/amd64",
        ))
        with Session(self.engine) as session:
            run = AutoUpdateRun(host_id="nas", stack_name="app", source="manual", status="queued")
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id
        self.manager._run_control_service_job = AsyncMock(side_effect=[("failed", "pull failed"), ("success", "healthy")])
        await self.manager._run_self_stack_update(self.conn, run_id, self.snap, "app", {"service_name": "agent"})
        calls = self.manager._run_control_service_job.await_args_list
        self.assertEqual([call.args[4] for call in calls], ["agent", "app"])
        self.assertEqual(self.run_record().status, "partial")

    async def test_notifications_are_optional_and_not_backfilled(self):
        await self.run_update()
        self.assertEqual(self.run_record().notify_status, "none")
        module.save_notify_settings("http://notify", "person_1", "nfy_testkey")
        self.assertEqual(self.run_record().notify_status, "none")

    async def test_success_notification_keeps_host_and_check_in_one_line(self):
        module.save_notify_settings("http://notify", "person_1", "nfy_testkey")
        await self.run_update()
        payload = json.loads(self.run_record().notify_payload)
        self.assertEqual(payload["title"], "【Fleetge】更新成功｜app")
        self.assertEqual(payload["content"], "nas · 运行检查通过")

    async def test_notification_title_identifies_updated_service_in_multi_service_compose(self):
        module.save_notify_settings("http://notify", "person_1", "nfy_testkey")
        self.snap.containers[0].service_name = "web"
        for service, image in (("redis", "redis:7"), ("browser", "browserless/chrome:latest")):
            self.snap.containers.append(self.snap.containers[0].model_copy(update={
                "id": service, "name": f"app-{service}-1", "service_name": service, "image": image,
            }))
            self.snap.update_check_results.append(UpdateCheckResult(host_id="nas", image=image, status="up_to_date"))
            self.snap.update_results[image] = "up_to_date"
        self.success["pulled_images"][0]["service"] = "web"
        await self.run_update()
        payload = json.loads(self.run_record().notify_payload)
        self.assertEqual(payload["title"], "【Fleetge】更新成功｜app / web")
        self.assertEqual(payload["content"], "nas · 运行检查通过")

    async def test_partial_notification_names_attempted_services_in_title(self):
        module.save_notify_settings("http://notify", "person_1", "nfy_testkey")
        self.snap.containers.append(self.snap.containers[0].model_copy(update={
            "id": "db", "name": "app-db-1", "service_name": "db", "image": "postgres:16-alpine",
        }))
        self.snap.update_results["postgres:16-alpine"] = "updatable"
        self.snap.update_check_results.append(UpdateCheckResult(
            host_id="nas", image="postgres:16-alpine", status="updatable",
            registry_config_digest="sha256:db-new", platform="linux/amd64",
        ))
        self.manager._update_service = AsyncMock(side_effect=[("success", "healthy"), ("failed", "unhealthy")])
        await self.run_update()
        payload = json.loads(self.run_record().notify_payload)
        self.assertEqual(payload["title"], "【Fleetge】更新部分成功｜app / app + db")
        self.assertEqual(payload["content"], "nas · app 成功 / db 失败 · 自动更新已暂停，请在 Fleetge 查看记录并处理")

    async def test_multiple_successful_services_share_one_notification(self):
        module.save_notify_settings("http://notify", "person_1", "nfy_testkey")
        self.snap.containers.append(self.snap.containers[0].model_copy(update={
            "id": "db", "name": "app-db-1", "service_name": "db", "image": "postgres:16-alpine",
        }))
        self.snap.update_results["postgres:16-alpine"] = "updatable"
        self.snap.update_check_results.append(UpdateCheckResult(
            host_id="nas", image="postgres:16-alpine", status="updatable",
            registry_config_digest="sha256:db-new", platform="linux/amd64",
        ))
        self.manager._update_service = AsyncMock(return_value=("success", "healthy"))
        await self.run_update()
        payload = json.loads(self.run_record().notify_payload)
        self.assertEqual(payload["title"], "【Fleetge】更新成功｜app / app + db")
        self.assertEqual(payload["content"], "nas · 运行检查通过")
        self.assertEqual(self.manager._update_service.await_count, 2)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(AutoUpdateRun)).all()), 1)

    def test_long_service_list_keeps_all_names_in_compact_body(self):
        names = ["rsshub-web-service", "redis-cache-service", "browserless-service"]
        run = AutoUpdateRun(host_id="istoreos", stack_name="rsshub", status="success", targets_json=json.dumps({
            "services": {name: {"image": "example:latest"} for name in names},
            "results": {name: {"status": "success"} for name in names},
        }))
        title = self.manager._notification_title(run, "成功")
        self.assertEqual(title, "【Fleetge】更新成功｜rsshub（3 个服务）")
        self.assertLessEqual(len(title), 40)
        self.assertEqual(self.manager._notification_content(run),
            "istoreos · 运行检查通过 · 服务：" + " + ".join(names))

    async def test_notification_timeout_reuses_payload_and_event_key(self):
        module.save_notify_settings("http://notify", "person_1", "nfy_testkey")
        await self.run_update()
        original = json.loads(self.run_record().notify_payload)
        client = AsyncMock()
        client.post.side_effect = [
            httpx.Response(201, json={"id": "media_cover"}, request=httpx.Request("POST", "http://notify/api/v1/media")),
            httpx.ReadTimeout("timeout"),
            httpx.Response(202, json={"data": {"status": "accepted", "event_id": "evt_1", "duplicate": True}}),
        ]
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
        frozen = json.loads(self.run_record().notify_payload)
        self.assertEqual(frozen["event_key"], original["event_key"])
        self.assertEqual(frozen["message_type"], "article")
        self.assertEqual(frozen["media_asset_id"], "media_cover")
        self.assertNotIn("_stack_icon", frozen)
        calls = client.post.await_args_list
        self.assertEqual(calls[1].kwargs["json"], calls[2].kwargs["json"])
        self.assertNotIn("nfy_testkey", self.run_record().notify_payload)

    async def test_unauthorized_notification_blocks_until_config_is_saved(self):
        module.save_notify_settings("http://notify", "person_1", "nfy_testkey")
        await self.run_update()
        client = AsyncMock()
        client.post.return_value = httpx.Response(403, request=httpx.Request("POST", "http://notify/api/v1/events"))
        with patch.object(module.httpx, "AsyncClient") as factory:
            factory.return_value.__aenter__ = AsyncMock(return_value=client)
            factory.return_value.__aexit__ = AsyncMock()
            await self.manager.send_notifications()
            await self.manager.send_notifications()
        # A media permission failure falls back to text, then event permission blocks.
        self.assertEqual(client.post.await_count, 2)
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
                ({"type": "error", "stage": "target", "up_executed": False, "message": "env file is not accessible"}, False),
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
        self.snap.update_check_results = [UpdateCheckResult(
            host_id="nas", image=f"img{index}:latest", status="updatable",
            registry_config_digest="sha256:new", registry_digest="sha256:new", platform="linux/amd64",
        ) for index in (1, 2, 3)]
        for container in self.snap.containers:
            container.platform = "linux/amd64"
            container.image_config_digest = "sha256:old"
        async def refresh_snapshot(*args, **kwargs):
            self.snap.containers_updated += 1

        self.snapshots = SimpleNamespace(
            get_snapshot=MagicMock(return_value=self.snap),
            refresh_host_docker=AsyncMock(side_effect=refresh_snapshot),
            verify_update_targets=AsyncMock(return_value=("success", "registry targets matched")),
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

    async def test_bulk_continues_after_failure_and_uncertain(self):
        # Unrelated Stacks continue even when one service result is uncertain.
        async def fake_execute(conn, stack_name, run_id=None, *, services):
            if stack_name == "s1":
                return {"success": False, "stage": "up"}, ""
            if stack_name == "s2":
                return {"success": False, "interrupted": True}, ""
            return {"success": True, "stage": "up", "up_executed": True, "pulled_images": [
                {"service": "app3", "image": "img3:latest", "image_id": "sha256:new", "platform": "linux/amd64"},
            ]}, ""

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
        self.assertEqual(items["s3"]["status"], "success")

    async def test_bulk_continues_and_succeeds_when_second_is_success(self):
        # s1 fails, s2 succeeds, s3 succeeds
        async def fake_execute(conn, stack_name, run_id=None, *, services):
            if stack_name == "s1":
                return {"success": False, "stage": "up"}, ""
            suffix = stack_name[1:]
            return {"success": True, "stage": "up", "up_executed": True, "pulled_images": [
                {"service": "app" + suffix, "image": "img" + suffix + ":latest", "image_id": "sha256:new", "platform": "linux/amd64"},
            ]}, ""

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
