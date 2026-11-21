import asyncio
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import AutoUpdateRun, HostBillingAlertState, HostConfig, HostSubscription


@pytest.fixture
def open_database(tmp_path, monkeypatch):
    from app.config import Settings

    # The module initializes a bootstrap engine on import. Isolate that engine too.
    with monkeypatch.context() as bootstrap:
        bootstrap.setattr(Settings, "DATABASE_URL", "sqlite://")
        from app import database

    @contextmanager
    def open_at(path):
        monkeypatch.setattr(database, "get_settings", lambda: SimpleNamespace(
            DATABASE_URL=f"sqlite:///{path.as_posix()}", LOG_LEVEL="info",
            HOST_CONFIG_PATH=str(tmp_path / "hosts.yaml"),
        ))
        engine = database.create_engine_and_tables()
        try:
            yield engine
        finally:
            engine.dispose()

    return open_at


def create_legacy_database(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE host_config (
                id INTEGER PRIMARY KEY, host_id TEXT UNIQUE NOT NULL, display_name TEXT,
                enabled BOOLEAN, sort_order INTEGER, stack_icons TEXT, status TEXT,
                last_seen TIMESTAMP, error_message TEXT, created_at TIMESTAMP, updated_at TIMESTAMP
            );
            INSERT INTO host_config (id, host_id, display_name, enabled, sort_order, status)
                VALUES (5, 'nas', 'Existing NAS', 1, 0, 'online');

            CREATE TABLE auto_update_run (
                id INTEGER PRIMARY KEY, host_id TEXT, stack_name TEXT, status TEXT, attempts INTEGER,
                stage TEXT, detail TEXT, started_at TIMESTAMP, finished_at TIMESTAMP, notify_url TEXT,
                notify_recipient TEXT, notify_payload TEXT, notify_status TEXT, notify_attempts INTEGER,
                notify_next_at TIMESTAMP, notify_expires_at TIMESTAMP, notify_error TEXT
            );
            INSERT INTO auto_update_run (id, host_id, stack_name, status, attempts, detail, notify_status)
                VALUES (8, 'nas', 'media', 'success', 2, 'Existing run', 'accepted');

            CREATE TABLE image_update_cache (id INTEGER PRIMARY KEY, host_id TEXT, image TEXT, status TEXT);
            INSERT INTO image_update_cache VALUES (11, 'nas', 'example/media:latest', 'updatable');

            CREATE TABLE enrollment_invite (id INTEGER PRIMARY KEY, invite_id TEXT, status TEXT);
            INSERT INTO enrollment_invite VALUES (14, 'existing-invite', 'active');
        """)


def test_sqlite_legacy_upgrade_preserves_records_and_can_run_twice(tmp_path, open_database):
    path = tmp_path / "legacy.db"
    create_legacy_database(path)

    for _ in range(2):
        with open_database(path) as engine, Session(engine) as session:
            host = session.get(HostConfig, 5)
            assert (host.host_id, host.display_name, host.traffic_billing_day) == ("nas", "Existing NAS", 1)
            assert host.agent_instance_id is None
            run = session.get(AutoUpdateRun, 8)
            assert (run.stack_name, run.status, run.detail, run.notify_status) == (
                "media", "success", "Existing run", "accepted",
            )
            assert (run.request_id, run.source, run.requested_by, run.targets_json) == (None, "auto", "system", "{}")
            connection = session.connection()
            assert connection.exec_driver_sql(
                "SELECT image, status, platform FROM image_update_cache WHERE id = 11"
            ).one() == ("example/media:latest", "updatable", None)
            assert connection.exec_driver_sql(
                "SELECT invite_id, status, callback_ip FROM enrollment_invite WHERE id = 14"
            ).one() == ("existing-invite", "active", None)
            indexes = {index["name"]: index for index in inspect(connection).get_indexes("auto_update_run")}
            dedup_index = indexes["uq_auto_update_run_host_request_stack"]
            assert dedup_index["unique"]
            assert dedup_index["column_names"] == ["host_id", "request_id", "stack_name"]


def test_sqlite_upgrade_rolls_back_when_legacy_agent_ids_conflict(tmp_path, open_database):
    path = tmp_path / "conflicting.db"
    create_legacy_database(path)
    schema_query = "SELECT name, sql FROM sqlite_schema ORDER BY name"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("ALTER TABLE host_config ADD COLUMN agent_instance_id TEXT")
        db.execute("UPDATE host_config SET agent_instance_id = 'duplicate-agent'")
        db.execute("INSERT INTO host_config (id, host_id, agent_instance_id) VALUES (6, 'vps', 'duplicate-agent')")
        old_schema = db.execute(schema_query).fetchall()

    with pytest.raises(IntegrityError, match=r"UNIQUE constraint failed: host_config\.agent_instance_id"):
        with open_database(path):
            pytest.fail("An invalid legacy database unexpectedly initialized")

    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute(schema_query).fetchall() == old_schema
        assert db.execute("SELECT host_id, agent_instance_id FROM host_config ORDER BY id").fetchall() == [
            ("nas", "duplicate-agent"), ("vps", "duplicate-agent"),
        ]
        db.execute("UPDATE host_config SET agent_instance_id = 'vps-agent' WHERE id = 6")

    with open_database(path) as engine, Session(engine) as session:
        assert session.get(HostConfig, 5).agent_instance_id == "duplicate-agent"
        assert session.get(HostConfig, 6).agent_instance_id == "vps-agent"


def test_sqlite_pragmas_are_applied_to_each_connection(tmp_path, open_database):
    with open_database(tmp_path / "connections.db") as engine:
        with engine.connect() as first, engine.connect() as second:
            assert first.connection.driver_connection is not second.connection.driver_connection
            for conn in (first, second):
                assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
                assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
                assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 5000
                assert conn.exec_driver_sql("PRAGMA synchronous").scalar_one() == 1  # NORMAL


def test_notify_settings_requeue_only_live_matching_blocked_events(tmp_path, open_database, monkeypatch):
    from app.services import auto_update

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_until = now + timedelta(hours=1)
    expired_at = now - timedelta(hours=1)
    original_next_attempt = now + timedelta(minutes=20)
    url = "https://notify.example"
    recipient = "recipient-a"
    cases = {
        "matching": (url, recipient, valid_until),
        "different-url": ("https://other.example", recipient, valid_until),
        "different-recipient": (url, "recipient-b", valid_until),
        "expired": (url, recipient, expired_at),
    }
    with open_database(tmp_path / "settings.db") as engine:
        monkeypatch.setattr(auto_update, "engine", engine)
        monkeypatch.setattr(auto_update, "now_utc", lambda: now)
        with Session(engine) as session:
            for key, (destination, target, expires) in cases.items():
                session.add(AutoUpdateRun(
                    host_id="nas", stack_name=key, status="success", notify_status="blocked",
                    notify_url=destination, notify_recipient=target, notify_expires_at=expires,
                    notify_error="HTTP 401", notify_next_at=original_next_attempt,
                ))
                session.add(HostBillingAlertState(
                    host_id="nas", alert_type="billing_due", alert_key=key, status="blocked",
                    notify_url=destination, notify_recipient=target, expires_at=expires,
                    last_error="HTTP 401", next_attempt_at=original_next_attempt,
                ))
            session.commit()

        auto_update.save_notify_settings(url, recipient, "")
        with Session(engine) as session:
            assert {run.notify_status for run in session.exec(select(AutoUpdateRun))} == {"blocked"}
            assert {alert.status for alert in session.exec(select(HostBillingAlertState))} == {"blocked"}

        auto_update.save_notify_settings(f"{url}/", recipient, "nfy_replacement")
        with Session(engine) as session:
            runs = {run.stack_name: run for run in session.exec(select(AutoUpdateRun))}
            alerts = {alert.alert_key: alert for alert in session.exec(select(HostBillingAlertState))}
            for key in cases:
                run, alert = runs[key], alerts[key]
                if key == "matching":
                    expected = ("pending", "", now)
                else:
                    expected = ("blocked", "HTTP 401", original_next_attempt)
                assert (run.notify_status, run.notify_error, auto_update.utc(run.notify_next_at)) == expected
                assert (alert.status, alert.last_error, auto_update.utc(alert.next_attempt_at)) == expected


@pytest.mark.parametrize("status_code", [200, 202, 409])
def test_notify_duplicate_receipt_completes_both_outboxes(status_code, tmp_path, open_database, monkeypatch):
    from app.services import auto_update, billing_service

    now = datetime.now(timezone.utc)
    due = now.date() + timedelta(days=1)
    update_event = "fleetge:update:nas:media:request-1"
    billing_event = f"fleetge:billing:nas:{due}:1"
    url = "https://notify.example"
    recipient = "recipient-a"
    posted_event_keys = []

    def respond(request):
        assert request.method == "POST"
        assert str(request.url) == f"{url}/api/v1/events"
        assert request.headers["X-API-Key"] == "nfy_test"
        event_key = json.loads(request.content)["event_key"]
        posted_event_keys.append(event_key)
        return httpx.Response(status_code, json={"data": {"event_id": event_key, "status": "duplicate"}})

    async_client = httpx.AsyncClient

    def mock_client(**kwargs):
        return async_client(transport=httpx.MockTransport(respond), **kwargs)

    with open_database(tmp_path / "outbox.db") as engine:
        monkeypatch.setattr(auto_update, "engine", engine)
        monkeypatch.setattr(billing_service, "engine", engine)
        monkeypatch.setattr(httpx, "AsyncClient", mock_client)
        auto_update.save_notify_settings(url, recipient, "nfy_test")
        with Session(engine) as session:
            session.add(HostConfig(host_id="nas"))
            session.add(HostSubscription(host_id="nas", service_expiry_date=due, billing_timezone="UTC"))
            session.add(AutoUpdateRun(
                host_id="nas", stack_name="media", status="success", notify_status="pending",
                notify_url=url, notify_recipient=recipient, notify_expires_at=now + timedelta(hours=1),
                notify_payload=json.dumps({"event_key": update_event}),
            ))
            session.add(HostBillingAlertState(
                host_id="nas", alert_type="billing_due", alert_key=billing_event,
                notify_url=url, notify_recipient=recipient, expires_at=now + timedelta(hours=1),
                payload=json.dumps({"event_key": billing_event}),
            ))
            session.commit()

        async def dispatch_twice():
            updates = auto_update.AutoUpdateManager()
            billing = billing_service.BillingAlertManager()
            for _ in range(2):
                await updates.send_notifications()
                await billing.dispatch_pending()

        asyncio.run(dispatch_twice())

        with Session(engine) as session:
            run = session.exec(select(AutoUpdateRun)).one()
            alert = session.exec(select(HostBillingAlertState)).one()
            assert (run.notify_status, run.notify_error) == ("accepted", "")
            assert (alert.status, alert.last_error) == ("sent", "")
            assert alert.sent_at is not None
        assert posted_event_keys == [update_event, billing_event]


def test_hosts_yaml_replace_failure_preserves_original_and_removes_temporary_file(tmp_path, open_database, monkeypatch):
    from app.services import host_writer

    path = tmp_path / "hosts.yaml"
    original = b"hosts:\n- host_id: previous\n"
    path.write_bytes(original)

    def reject_replace(source, destination):
        assert destination == path
        assert source.parent == path.parent
        assert source != path.with_suffix(".yaml.tmp")
        assert yaml.safe_load(source.read_text(encoding="utf-8"))["hosts"][0]["host_id"] == "nas"
        assert path.read_bytes() == original
        raise PermissionError("simulated replacement failure")

    with open_database(tmp_path / "hosts.db") as engine:
        monkeypatch.setattr(host_writer, "engine", engine)
        monkeypatch.setattr(host_writer, "get_settings", lambda: SimpleNamespace(HOST_CONFIG_PATH=str(path)))
        with Session(engine) as session:
            session.add(HostConfig(host_id="nas", agent_url="http://agent", agent_token_encrypted="test-ciphertext"))
            session.commit()

        with monkeypatch.context() as patch_replace:
            patch_replace.setattr(host_writer.os, "replace", reject_replace)
            with pytest.raises(PermissionError, match="simulated replacement failure"):
                asyncio.run(host_writer.sync_hosts_to_yaml())

        assert path.read_bytes() == original
        assert sorted(item.name for item in tmp_path.iterdir() if item.name.startswith(("hosts.yaml", ".hosts.yaml"))) == [
            "hosts.yaml", "hosts.yaml.bak",
        ]

        asyncio.run(host_writer.sync_hosts_to_yaml())
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert config["hosts"][0]["agent"]["token"] == "[ENCRYPTED]"
        assert path.with_suffix(".yaml.bak").read_bytes() == original


def test_partial_snapshot_merges_successes_and_preserves_failed_sections(open_database):
    from app.schemas import ContainerSummary, DockerDiskUsage, DockerInfo
    from app.services.snapshot import HostSnapshot, SnapshotManager

    manager = SnapshotManager()
    snap = HostSnapshot()
    snap.host_config = HostConfig(host_id="nas", agent_url="http://agent")
    snap.status = "online"
    snap.docker_info = DockerInfo(version="26.0", operating_system="Old OS")
    disk = DockerDiskUsage(images_total=7, images_size=4096)
    snap.docker_disk = disk.model_copy()
    snap.image_count = 5
    container = ContainerSummary(
        id="existing", name="media", image="example/media:latest", image_id="sha256:old",
        state="running", status="Up", created=123,
    )
    snap.containers = [container.model_copy()]
    snap.containers_updated, snap.stacks_updated, snap.stats_updated = 10, 11, 12
    manager._snapshots["nas"] = snap
    fetch = AsyncMock(return_value={
        "errors": {"version": "version unavailable", "df": "disk unavailable",
                   "images": "images unavailable", "containers": "inventory unavailable"},
        "version": None,
        "info": {"OperatingSystem": "New OS", "Architecture": "arm64"},
        "df": None,
        "images": [],
        "containers": [],
        "stack_names": [],
        "container_details": {},
    })
    manager._agent_clients["nas"] = SimpleNamespace(fetch_snapshot=fetch)

    asyncio.run(manager.refresh_host_docker("nas"))

    fetch.assert_awaited_once_with()
    assert snap.status == "degraded"
    assert "inventory unavailable" in snap.error_message
    assert (snap.docker_info.version, snap.docker_info.operating_system, snap.docker_info.architecture) == (
        "26.0", "New OS", "arm64",
    )
    assert snap.docker_disk == disk
    assert snap.image_count == 5
    assert snap.containers == [container]
    assert (snap.containers_updated, snap.stacks_updated, snap.stats_updated) == (10, 11, 12)


@pytest.mark.parametrize("status_code", [401, 403, 429])
@pytest.mark.parametrize("legacy", [False, True], ids=["aggregate", "legacy-fallback"])
def test_snapshot_retry_stops_on_auth_or_rate_limit(status_code, legacy, open_database, monkeypatch):
    from app.services.snapshot import HostSnapshot, SnapshotManager

    def http_error(code):
        request = httpx.Request("GET", "http://agent/snapshot")
        response = httpx.Response(code, request=request)
        return httpx.HTTPStatusError(f"HTTP {code}", request=request, response=response)

    manager = SnapshotManager()
    snap = HostSnapshot()
    snap.host_config = HostConfig(host_id="nas", agent_url="http://agent")
    manager._snapshots["nas"] = snap
    error = http_error(status_code)
    agent = SimpleNamespace(
        fetch_snapshot=AsyncMock(side_effect=http_error(404) if legacy else error),
        version=AsyncMock(return_value={"Version": "26.0"}),
        info=AsyncMock(side_effect=error),
        list_images=AsyncMock(), list_containers=AsyncMock(), disk_usage=AsyncMock(),
    )
    manager._agent_clients["nas"] = agent
    refresh = AsyncMock(wraps=manager.refresh_host_docker)
    monkeypatch.setattr(manager, "refresh_host_docker", refresh)

    asyncio.run(manager.refresh_host_docker_with_retry("nas", steps=(0, 0, 0)))

    assert refresh.await_count == 1
    agent.fetch_snapshot.assert_awaited_once_with()
    assert agent.info.await_count == int(legacy)
    agent.list_images.assert_not_called()
    agent.list_containers.assert_not_called()
    agent.disk_usage.assert_not_called()
    assert snap.status == "degraded"


def test_scheduled_structure_refreshes_coalesce_and_stop(open_database, monkeypatch):
    from app.services.snapshot import SnapshotManager

    async def exercise():
        manager = SnapshotManager()
        host_started, all_started = asyncio.Event(), asyncio.Event()
        host_finished, all_finished = asyncio.Event(), asyncio.Event()

        async def wait_until_cancelled(started, finished):
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                finished.set()

        async def host_refresh(host_id):
            assert host_id == "nas"
            await wait_until_cancelled(host_started, host_finished)

        async def all_refresh():
            await wait_until_cancelled(all_started, all_finished)

        refresh_host = AsyncMock(side_effect=host_refresh)
        refresh_all = AsyncMock(side_effect=all_refresh)
        monkeypatch.setattr(manager, "refresh_host_docker_with_retry", refresh_host)
        monkeypatch.setattr(manager, "refresh_all_structure_now", refresh_all)
        for _ in range(2):
            manager.schedule_host_structure_refresh("nas")
            manager.schedule_all_structure_refresh()
        try:
            await asyncio.wait_for(asyncio.gather(host_started.wait(), all_started.wait()), timeout=2)
            manager.schedule_host_structure_refresh("nas")
            manager.schedule_all_structure_refresh()
        finally:
            await manager.stop()

        assert host_finished.is_set() and all_finished.is_set()
        assert not manager._operation_refresh_tasks
        manager.schedule_host_structure_refresh("nas")
        manager.schedule_all_structure_refresh()
        refresh_host.assert_called_once_with("nas")
        refresh_all.assert_called_once_with()

    asyncio.run(exercise())


def test_delete_host_preserves_history_and_cleans_only_its_host_data(tmp_path, open_database, monkeypatch):
    from fastapi import Request

    from app.models import AuditLog, HostTrafficBucket, HostTrafficCursor, HostTrafficDaily, ImageUpdateCache, StackAutoUpdate
    from app.routers import host_mgmt
    from app.services import host_writer, snapshot

    now = datetime.now(timezone.utc)
    yaml_path = tmp_path / "hosts.yaml"
    manager = snapshot.SnapshotManager()
    scoped_models = (HostConfig, HostSubscription, HostBillingAlertState, HostTrafficBucket,
                     HostTrafficCursor, HostTrafficDaily, ImageUpdateCache, StackAutoUpdate)

    with open_database(tmp_path / "delete.db") as engine:
        monkeypatch.setattr(host_mgmt, "snapshot_manager", manager)
        monkeypatch.setattr(snapshot, "engine", engine)
        monkeypatch.setattr(host_writer, "engine", engine)
        monkeypatch.setattr(host_writer, "get_settings", lambda: SimpleNamespace(HOST_CONFIG_PATH=str(yaml_path)))
        with Session(engine) as session:
            for host_id in ("nas", "vps"):
                session.add_all([
                    HostConfig(host_id=host_id),
                    HostSubscription(host_id=host_id, provider="Example Provider", alerts_enabled=False),
                    HostBillingAlertState(host_id=host_id, alert_type="billing_due", alert_key=host_id, expires_at=now),
                    HostTrafficBucket(host_id=host_id, ledger_id="main", agent_bucket_id=1,
                                      counter_epoch="epoch", bucket_start=now),
                    HostTrafficCursor(host_id=host_id, cursor=1),
                    HostTrafficDaily(host_id=host_id, day_utc=now.date().isoformat()),
                    ImageUpdateCache(host_id=host_id, image="example/media:latest", status="updatable"),
                    StackAutoUpdate(host_id=host_id, stack_name="media", enabled=True),
                    AutoUpdateRun(host_id=host_id, stack_name="queued-stack", status="queued"),
                    AutoUpdateRun(host_id=host_id, stack_name="media", status="success", stage="done",
                                  finished_at=now, detail="already completed"),
                    AuditLog(host_id=host_id, action="stack.update", result="success", detail="existing audit"),
                ])
            session.commit()

        async def delete_from_dashboard():
            await manager.refresh_hosts()
            request = Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": []})
            with Session(engine) as session:
                return await host_mgmt.delete_host("nas", request, session, "operator")

        assert asyncio.run(delete_from_dashboard())["success"]
        with Session(engine) as session:
            for model in scoped_models:
                assert [row.host_id for row in session.exec(select(model))] == ["vps"], model.__name__

            runs = {(row.host_id, row.stack_name): row for row in session.exec(select(AutoUpdateRun))}
            assert len(runs) == 4
            completed = runs["nas", "media"]
            assert (completed.status, completed.stage, completed.detail) == ("success", "done", "already completed")
            skipped = runs["nas", "queued-stack"]
            assert (skipped.status, skipped.stage) == ("skipped", "skipped")
            assert skipped.finished_at is not None
            assert "Host was deleted" in skipped.detail
            assert runs["vps", "queued-stack"].status == "queued"

            audits = {(row.host_id, row.action, row.user): row for row in session.exec(select(AuditLog))}
            assert audits["nas", "stack.update", ""].detail == "existing audit"
            assert audits["vps", "stack.update", ""].detail == "existing audit"
            assert audits["nas", "host.delete", "operator"].result == "success"

        config = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert [row["host_id"] for row in config["hosts"]] == ["vps"]
        assert manager.get_snapshot("nas") is None
        other_snapshot = manager.get_snapshot("vps")
        assert other_snapshot is not None
        assert manager.build_host_summary(other_snapshot).model_dump()["subscription"]["alerts_enabled"] is False
