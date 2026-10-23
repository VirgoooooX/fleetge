import asyncio
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
import json
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.gettempdir()}/fleetge_billing_test.db")

from app.auth.handler import get_current_user
from app.models import HostBillingAlertState, HostConfig, HostSubscription, HostTrafficBucket, HostTrafficDaily, Setting
from app.routers import subscriptions as subscriptions_router
from app.schemas import HostSubscriptionUpdate
from app.services import billing_service, traffic_service


@contextmanager
def notify_transport(handler):
    real_client = httpx.AsyncClient
    def with_media(request):
        if request.url.path == "/api/v1/media":
            return httpx.Response(201, json={"id": "media_test_cover"})
        return handler(request)
    transport = httpx.MockTransport(with_media)
    with patch.object(billing_service.httpx, "AsyncClient", side_effect=lambda **kwargs: real_client(transport=transport, **kwargs)), patch.object(
        billing_service, "decrypt_string", return_value="test-key",
    ):
        yield


def complete_report():
    return {
        "rxBytes": 100,
        "txBytes": 50,
        "totalBytes": 150,
        "hasGap": False,
        "start": "2026-03-01T00:00:00+00:00",
        "end": "2026-03-01T00:10:00+00:00",
        "buckets": [{"bucketStart": "2026-03-01T00:00:00+00:00", "bucketSeconds": 300}],
        "daily": [],
        "openBucket": {"bucketStart": "2026-03-01T00:05:00+00:00"},
    }


class BillingCalculationTests(unittest.TestCase):
    def test_quota_directions_and_units(self):
        host = HostConfig(host_id="vps", traffic_billing_day=31)
        report = {
            "rxBytes": 6_000_000_000,
            "txBytes": 4_000_000_000,
            "hasGap": False,
            "buckets": [{"bucketStart": "2026-02-27T16:00:00+00:00", "bucketSeconds": 43200}],
            "daily": [],
            "start": "2026-02-27T16:00:00+00:00",
            "end": "2026-02-28T04:00:00+00:00",
        }
        now = datetime(2026, 2, 28, 4, tzinfo=timezone.utc)
        expected = {"upload": 4_000_000_000, "download": 6_000_000_000, "both": 10_000_000_000, "max": 6_000_000_000}
        for direction, used in expected.items():
            subscription = HostSubscription(
                host_id="vps",
                quota_enabled=True,
                traffic_quota_value=10,
                traffic_quota_unit="GB",
                traffic_direction=direction,
            )
            result = billing_service.quota_summary(host, subscription, report, now=now)
            self.assertEqual(result["usedBytes"], used)
            self.assertEqual(result["quotaBytes"], 10_000_000_000)
            self.assertEqual(result["remainingBytes"], max(0, 10_000_000_000 - used))
            self.assertEqual(result["status"], "over_quota" if used >= 10_000_000_000 else "normal")
            self.assertEqual(result["nextResetAt"], datetime(2026, 3, 31, 0, tzinfo=ZoneInfo("Asia/Shanghai")))

        subscription.traffic_quota_value = 1
        subscription.traffic_quota_unit = "TiB"
        self.assertEqual(
            billing_service.quota_summary(host, subscription, report, now=now)["quotaBytes"],
            1_099_511_627_776,
        )

    def test_missing_or_gapped_ledger_is_estimated(self):
        host = HostConfig(host_id="vps")
        subscription = HostSubscription(
            host_id="vps",
            quota_enabled=True,
            traffic_quota_value=100,
            traffic_quota_unit="GiB",
        )
        report = {
            "rxBytes": 1,
            "txBytes": 2,
            "hasGap": True,
            "buckets": [{}],
            "daily": [],
            "start": "2026-02-01T00:00:00+00:00",
            "end": "2026-02-02T00:00:00+00:00",
        }
        result = billing_service.quota_summary(host, subscription, report)
        self.assertTrue(result["estimated"])
        self.assertEqual(result["status"], "incomplete")
        report["hasGap"] = False
        report["buckets"] = []
        result = billing_service.quota_summary(host, subscription, report)
        self.assertTrue(result["estimated"])
        self.assertFalse(result["hasData"])

    def test_billing_days_month_end_and_expiry_states(self):
        subscription = HostSubscription(
            host_id="vps",
            payment_cycle="monthly",
            next_payment_date=date(2026, 3, 1),
            service_expiry_date=date(2026, 3, 30),
        )
        result = billing_service.billing_summary("vps", subscription, today=date(2026, 2, 28))
        self.assertEqual(result["status"], "expiring_soon")
        self.assertEqual(result["paymentDaysRemaining"], 1)
        self.assertEqual(result["serviceDaysRemaining"], 30)
        self.assertEqual(billing_service.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(billing_service.add_months(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(
            billing_service.billing_summary("vps", HostSubscription(host_id="vps"), today=date(2026, 2, 28))["status"],
            "unconfigured",
        )

    def test_subscription_tables_compile_for_postgres(self):
        subscription_ddl = str(CreateTable(HostSubscription.__table__).compile(dialect=postgresql.dialect()))
        alert_ddl = str(CreateTable(HostBillingAlertState.__table__).compile(dialect=postgresql.dialect()))
        self.assertIn("NUMERIC(14, 4)", subscription_ddl)
        self.assertIn("DATE", subscription_ddl)
        self.assertIn("UNIQUE (alert_key)", alert_ddl)

    def test_period_coverage_detects_missing_start_middle_and_tail(self):
        host = HostConfig(host_id="vps")
        sub = HostSubscription(host_id="vps", quota_enabled=True, traffic_quota_value=1)
        report = complete_report()
        self.assertFalse(billing_service.quota_summary(host, sub, report)["estimated"])
        for missing in ("start", "middle", "tail"):
            report = complete_report()
            if missing == "start":
                report["buckets"] = []
            elif missing == "middle":
                report["openBucket"]["bucketStart"] = "2026-03-01T00:06:00+00:00"
            else:
                report.pop("openBucket")
            with self.subTest(missing=missing):
                quota = billing_service.quota_summary(host, sub, report)
                self.assertEqual(quota["status"], "incomplete")
                self.assertTrue(quota["hasGap"])
                self.assertFalse(quota["coverageComplete"])

    def test_dst_and_timezone_reset_boundaries(self):
        # New York changes to DST on March 8: the cycle starts at UTC-5,
        # and its next reset is at UTC-4. Shanghai's same date has UTC+8.
        host = HostConfig(host_id="vps", traffic_billing_day=8)
        sub = HostSubscription(host_id="vps", quota_enabled=True, traffic_quota_value=1, billing_timezone="America/New_York")
        now = datetime(2026, 3, 8, 16, tzinfo=timezone.utc)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz or timezone.utc)
        with patch.object(traffic_service, "datetime", Clock):
            start, end, _ = traffic_service._range_bounds("month", sub.billing_timezone, None, None, 8)
        self.assertEqual(start, datetime(2026, 3, 8, 5, tzinfo=timezone.utc))
        report = complete_report()
        report["start"], report["end"] = start.isoformat(), end.isoformat()
        quota = billing_service.quota_summary(host, sub, report, now=now)
        self.assertEqual(quota["nextResetAt"].astimezone(timezone.utc), datetime(2026, 4, 8, 4, tzinfo=timezone.utc))
        sub.billing_timezone = "Asia/Shanghai"
        with patch.object(traffic_service, "datetime", Clock):
            start, _, _ = traffic_service._range_bounds("month", sub.billing_timezone, None, None, 8)
        self.assertEqual(start, datetime(2026, 3, 7, 16, tzinfo=timezone.utc))

    def test_subscription_validation(self):
        with self.assertRaises(ValueError):
            HostSubscriptionUpdate(quota_enabled=True)
        with self.assertRaises(ValueError):
            HostSubscriptionUpdate(billing_timezone="No/Such_Zone")
        with self.assertRaises(ValueError):
            HostSubscriptionUpdate(management_url="https://user:secret@example.com")


class BillingPersistenceAndApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.patches = [
            patch.object(billing_service, "engine", self.engine),
            patch.object(traffic_service, "engine", self.engine),
            patch.object(subscriptions_router, "engine", self.engine),
            patch.object(billing_service, "notify_settings", return_value={
                "NOTIFYHUB_URL": "http://notify",
                "NOTIFYHUB_RECIPIENT": "person_1",
                "NOTIFYHUB_KEY": "encrypted-key",
            }),
        ]
        for item in self.patches:
            item.start()
        self.manager = billing_service.BillingAlertManager()
        self.app = FastAPI()
        self.app.include_router(subscriptions_router.router)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        for item in self.patches:
            item.stop()
        self.engine.dispose()

    def authenticate(self):
        self.app.dependency_overrides[get_current_user] = lambda: "test-admin"

    def test_authenticated_subscription_api_and_confirmed_renewal(self):
        self.assertEqual(self.client.get("/api/hosts/vps/subscription").status_code, 401)
        self.authenticate()
        with Session(self.engine) as session:
            session.add(HostConfig(host_id="vps", display_name="Test VPS"))
            session.commit()

        payload = {
            "provider": "CloudCone",
            "plan_name": "1C VPS",
            "payment_amount": 0,
            "currency": "usd",
            "payment_cycle": "monthly",
            "next_payment_date": "2026-01-31",
            "service_expiry_date": "2026-02-28",
            "quota_enabled": True,
            "traffic_quota_value": 1.5,
            "traffic_quota_unit": "TB",
            "traffic_direction": "max",
            "billing_timezone": "Asia/Shanghai",
        }
        response = self.client.put("/api/hosts/vps/subscription", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["currency"], "USD")
        self.assertTrue(response.json()["configured"])
        self.assertEqual(self.client.get("/api/hosts/vps/billing").status_code, 200)

        renewal = self.client.post("/api/hosts/vps/renewal", json={
            "paid_on": "2026-01-31",
            "next_payment_date": "2026-02-28",
            "service_expiry_date": "2027-01-31",
        })
        self.assertEqual(renewal.status_code, 200, renewal.text)
        self.assertEqual(renewal.json()["paymentDate"], "2026-02-28")
        self.assertEqual(renewal.json()["serviceExpiryDate"], "2027-01-31")

        self.assertTrue(self.client.get("/api/admin/billing-alerts").json()["enabled"])
        changed = self.client.put("/api/admin/billing-alerts", json={"enabled": False})
        self.assertEqual(changed.json(), {"enabled": False})

    def test_expiry_check_catches_up_and_deduplicates_reminders(self):
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        with Session(self.engine) as session:
            session.add(HostConfig(host_id="vps", display_name="Test VPS"))
            session.add(HostSubscription(
                host_id="vps",
                next_payment_date=today + timedelta(days=6),
            ))
            session.commit()

        asyncio.run(self.manager.check_expiry_alerts())
        asyncio.run(self.manager.check_expiry_alerts())
        with Session(self.engine) as session:
            alerts = session.exec(select(HostBillingAlertState)).all()
            self.assertEqual(len(alerts), 1)
            self.assertTrue(alerts[0].alert_key.endswith(":7"))
            self.assertEqual(alerts[0].status, "pending")

    def test_traffic_threshold_alerts_use_persisted_cycle_keys(self):
        with Session(self.engine) as session:
            session.add(HostConfig(host_id="vps", display_name="Test VPS"))
            session.add(HostSubscription(
                host_id="vps",
                quota_enabled=True,
                traffic_quota_value=10,
                traffic_quota_unit="GB",
            ))
            session.commit()

        quota = {
            "configured": True,
            "usagePercent": 100,
            "estimated": True,
            "periodStart": "2026-02-01T08:00:00+08:00",
            "usedBytes": 11_000_000_000,
            "quotaBytes": 10_000_000_000,
        }
        with patch.object(billing_service, "sync_host_traffic", new=AsyncMock(return_value={"supported": True})), patch.object(
            billing_service, "calculate_quota", new=AsyncMock(return_value=quota),
        ) as calculate:
            asyncio.run(self.manager.check_traffic_alerts())
            asyncio.run(self.manager.check_traffic_alerts())
            self.assertEqual(calculate.await_count, 2)

        with Session(self.engine) as session:
            alerts = session.exec(select(HostBillingAlertState)).all()
            self.assertEqual(len(alerts), 4)
            self.assertTrue(all("2026-02-01T08:00:00+08:00" in alert.alert_key for alert in alerts))

    def test_alert_outbox_deduplicates_and_stops_after_finite_retries(self):
        self.manager._enqueue(
            host_id="vps",
            alert_type="traffic_quota",
            alert_key="fleetge:traffic:vps:2026-02-01:80",
            title="Quota reached",
            content="80 percent",
        )
        self.manager._enqueue(
            host_id="vps",
            alert_type="traffic_quota",
            alert_key="fleetge:traffic:vps:2026-02-01:80",
            title="Quota reached",
            content="80 percent",
        )
        with Session(self.engine) as session:
            rows = session.exec(select(HostBillingAlertState)).all()
            self.assertEqual(len(rows), 1)
            alert_id = rows[0].id
            self.assertEqual(rows[0].status, "pending")

        for _ in range(billing_service.MAX_NOTIFY_ATTEMPTS):
            self.manager._retry_delivery(alert_id, "temporary failure")
        with Session(self.engine) as session:
            alert = session.get(HostBillingAlertState, alert_id)
            self.assertEqual(alert.status, "failed")
            self.assertEqual(alert.attempts, billing_service.MAX_NOTIFY_ATTEMPTS)
    def test_current_agent_anomalies_remain_visible_in_quota(self):
        host = HostConfig(host_id="vps", agent_url="http://agent")
        sub = HostSubscription(host_id="vps", quota_enabled=True, traffic_quota_value=1)
        for flags in ({"hasGap": True}, {"persistenceAvailable": False}, {"sampleAgeSeconds": 900}):
            current = {
                "currentBucketStart": "2026-03-01T00:05:00+00:00",
                "currentBucketRxBytes": 10, "currentBucketTxBytes": 5,
                **flags,
            }
            agent = SimpleNamespace(get_traffic_current=AsyncMock(return_value=current), close=AsyncMock())
            with self.subTest(flags=flags), patch.object(billing_service, "AgentClient", return_value=agent), patch.object(
                billing_service, "build_traffic_report", side_effect=lambda *args, **kwargs: complete_report(),
            ):
                quota = asyncio.run(billing_service.calculate_quota(host, sub, sync=False))
            self.assertEqual(quota["status"], "incomplete")
            self.assertTrue(quota["collectionWarnings"])
            self.assertTrue(quota["estimated"])

    def test_renewal_confirmation_is_deterministic_and_requires_explicit_date(self):
        self.authenticate()
        with Session(self.engine) as session:
            session.add(HostConfig(host_id="vps"))
            session.add(HostSubscription(host_id="vps", payment_cycle="monthly", next_payment_date=date(2026, 1, 31)))
            session.commit()
        payload = {"paid_on": "2026-01-31", "service_expiry_date": "2027-01-31"}
        self.assertEqual(self.client.post("/api/hosts/vps/renewal", json=payload).status_code, 422)
        payload["next_payment_date"] = "2026-02-28"
        first = self.client.post("/api/hosts/vps/renewal", json=payload)
        second = self.client.post("/api/hosts/vps/renewal", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json()["paymentDate"], first.json()["paymentDate"])
        payload["next_payment_date"] = None
        self.assertIsNone(self.client.post("/api/hosts/vps/renewal", json=payload).json()["paymentDate"])

    def test_thresholds_use_exact_bytes_instead_of_display_rounding(self):
        with Session(self.engine) as session:
            session.add(HostConfig(host_id="vps"))
            session.add(HostSubscription(host_id="vps", quota_enabled=True, traffic_quota_value=1, traffic_quota_unit="GB"))
            session.commit()
        quota = {"configured": True, "usagePercent": 100.0, "estimated": False,
                 "usedBytes": 999_960_000, "quotaBytes": 1_000_000_000,
                 "periodStart": "2026-03-01T00:00:00+00:00"}
        with patch.object(billing_service, "sync_host_traffic", new=AsyncMock(return_value={"supported": True})), patch.object(
            billing_service, "calculate_quota", new=AsyncMock(return_value=quota),
        ):
            asyncio.run(self.manager.check_traffic_alerts())
        with Session(self.engine) as session:
            alerts = session.exec(select(HostBillingAlertState)).all()
            self.assertEqual(len(alerts), 3)
            self.assertFalse(any(alert.alert_key.endswith(":100") for alert in alerts))

    def test_delivery_cancels_old_date_cycle_and_disabled_quota(self):
        self.authenticate()
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        due = today + timedelta(days=1)
        with Session(self.engine) as session:
            session.add(HostConfig(host_id="vps"))
            session.add(HostSubscription(host_id="vps", payment_cycle="monthly", next_payment_date=due, service_expiry_date=due))
            session.commit()
        for kind, key in (
            ("billing_due", f"fleetge:billing:vps:{due}:1"),
            ("traffic_quota", "fleetge:traffic:vps:2000-01-01T00:00:00+00:00:80"),
            ("traffic_quota", f"fleetge:traffic:vps:{billing_service._billing_cycle_start(datetime.now(ZoneInfo('Asia/Shanghai')), 1).astimezone(timezone.utc).isoformat()}:90"),
        ):
            self.manager._enqueue(host_id="vps", alert_type=kind, alert_key=key, title="old", content="old")
        future = today + timedelta(days=90)
        response = self.client.post("/api/hosts/vps/renewal", json={
            "next_payment_date": future.isoformat(), "service_expiry_date": future.isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        sent = []
        with notify_transport(lambda request: sent.append(request) or httpx.Response(202)):
            asyncio.run(self.manager.dispatch_pending())
        self.assertEqual(sent, [])
        with Session(self.engine) as session:
            self.assertTrue(all(row.status == "cancelled" for row in session.exec(select(HostBillingAlertState)).all()))

    def test_pending_traffic_context_is_valid_only_for_current_cycle_and_rules(self):
        now = datetime.now(timezone.utc)
        host = HostConfig(host_id="vps", traffic_billing_day=1)
        sub = HostSubscription(host_id="vps", quota_enabled=True, traffic_quota_value=1, traffic_quota_unit="GB")
        period = billing_service._billing_cycle_start(now.astimezone(ZoneInfo(sub.billing_timezone)), 1).astimezone(timezone.utc).isoformat()
        key = f"fleetge:traffic:vps:{period}:80"
        context = {"quotaBytes": 1_000_000_000, "direction": "both", "usedBytes": 850_000_000}
        self.manager._enqueue(host_id="vps", alert_type="traffic_quota", alert_key=key, title="quota", content="quota", context=context)
        with Session(self.engine) as session:
            alert = session.exec(select(HostBillingAlertState)).one()
        self.assertTrue(self.manager._alert_is_current(alert, sub, host, now))
        sub.traffic_quota_value = 2
        self.assertFalse(self.manager._alert_is_current(alert, sub, host, now))
        sub.traffic_quota_value = 1
        sub.traffic_direction = "upload"
        self.assertFalse(self.manager._alert_is_current(alert, sub, host, now))
        sub.traffic_direction = "both"
        alert.alert_key = "fleetge:traffic:vps:2000-01-01T00:00:00+00:00:80"
        self.assertFalse(self.manager._alert_is_current(alert, sub, host, now))
        self.manager._finish_delivery(alert.id, "cancelled", "rules changed")
        self.manager._enqueue(host_id="vps", alert_type="traffic_quota", alert_key=key, title="quota", content="quota", context=context)
        with Session(self.engine) as session:
            revived = session.exec(select(HostBillingAlertState)).one()
            self.assertEqual((revived.status, revived.attempts), ("pending", 0))

    def test_notify_delivery_retries_same_event_and_recognizes_duplicate_acceptance(self):
        due = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)
        with Session(self.engine) as session:
            session.add(HostConfig(host_id="vps"))
            session.add(HostSubscription(host_id="vps", service_expiry_date=due))
            session.commit()
        key = f"fleetge:billing:vps:{due}:1"
        self.manager._enqueue(host_id="vps", alert_type="billing_due", alert_key=key, title="due", content="due")
        # A logo configured after enqueue is picked up before the first send.
        with Session(self.engine) as session:
            host = session.exec(select(HostConfig).where(HostConfig.host_id == "vps")).one()
            host.logo = "cloudcone"
            session.add(host)
            session.commit()
        requests = []
        def send(request):
            requests.append(json.loads(request.content))
            if len(requests) == 1:
                return httpx.Response(503)
            return httpx.Response(202, json={"data": {"status": "duplicate", "event_id": "evt"}})
        with notify_transport(send), patch.object(billing_service, "prepare_notification", wraps=billing_service.prepare_notification) as prepare:
            asyncio.run(self.manager.dispatch_pending())
            self.assertEqual(prepare.call_args.args[3]["_host_icon"], "cloudcone")
            with Session(self.engine) as session:
                alert = session.exec(select(HostBillingAlertState)).one()
                self.assertEqual(alert.status, "pending")
                alert.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                session.add(alert)
                session.commit()
            restarted = billing_service.BillingAlertManager()
            asyncio.run(restarted.dispatch_pending())
            asyncio.run(restarted.dispatch_pending())
        self.assertEqual([item["event_key"] for item in requests], [key, key])
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(requests[0]["message_type"], "article")
        self.assertNotIn("_host_icon", requests[0])
        with Session(self.engine) as session:
            alert = session.exec(select(HostBillingAlertState)).one()
            self.assertEqual(alert.status, "sent")
            self.assertEqual(alert.attempts, 2)

    def test_background_lifecycle_syncs_and_sends_without_browser_requests(self):
        from app import main
        due = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)
        now = datetime.now(timezone.utc)
        open_start = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5)
        with Session(self.engine) as session:
            session.add(HostConfig(host_id="vps", agent_url="http://agent"))
            session.add(HostSubscription(host_id="vps", service_expiry_date=due, quota_enabled=True, traffic_quota_value=1, traffic_quota_unit="GB"))
            session.commit()
        agent = SimpleNamespace(
            get_traffic_history=AsyncMock(return_value={
                "ledgerId": "ledger", "nextCursor": 1, "hasMore": False,
                "buckets": [{"id": 1, "bucketStart": (open_start - timedelta(minutes=5)).isoformat(), "rxBytes": 900_000_000, "txBytes": 0}],
            }),
            get_traffic_current=AsyncMock(return_value={
                "currentBucketStart": open_start.isoformat(), "currentBucketRxBytes": 0, "currentBucketTxBytes": 0,
                "persistenceAvailable": True,
            }),
            close=AsyncMock(),
        )
        sent = []
        async def exercise():
            received = asyncio.Event()
            def send(request):
                sent.append(json.loads(request.content))
                if {item["event_type"] for item in sent} >= {"fleetge.host.billing_due", "fleetge.host.traffic_quota"}:
                    received.set()
                return httpx.Response(202, json={"data": {"status": "accepted", "event_id": f"evt{len(sent)}"}})
            with ExitStack() as stack:
                for obj, name in ((main, "auto_update_manager"), (main, "enrollment_monitor")):
                    stack.enter_context(patch.object(obj, name, SimpleNamespace(start=AsyncMock(), stop=AsyncMock())))
                snapshot = SimpleNamespace(refresh_hosts=AsyncMock(), load_update_check_cache_from_db=lambda: None, start=AsyncMock(), stop=AsyncMock())
                stack.enter_context(patch.object(main, "snapshot_manager", snapshot))
                stack.enter_context(patch.object(main, "load_hosts_from_yaml"))
                stack.enter_context(patch("app.services.settings_service.populate_defaults_if_empty"))
                stack.enter_context(patch.object(main, "billing_alert_manager", self.manager))
                stack.enter_context(patch.object(traffic_service, "AgentClient", return_value=agent))
                stack.enter_context(patch.object(billing_service, "AgentClient", return_value=agent))
                stack.enter_context(notify_transport(send))
                async with main.lifespan(self.app):
                    await asyncio.wait_for(received.wait(), timeout=2)
            self.assertFalse(self.manager.started)
            self.assertEqual(self.manager.tasks, [])
        asyncio.run(exercise())
        agent.get_traffic_history.assert_awaited()
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(HostTrafficBucket)).all()), 1)
        self.assertTrue(any(item["event_type"] == "fleetge.host.traffic_quota" for item in sent))
        self.assertTrue(any(item["event_type"] == "fleetge.host.billing_due" for item in sent))
        self.assertTrue(all("_billing_context" not in item for item in sent))


class BillingUpgradeTests(unittest.TestCase):
    def test_upgrade_preserves_v168_data_and_reopens_subscription_and_outbox(self):
        from app import database
        from app.services import auto_update
        due = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)
        with tempfile.TemporaryDirectory() as directory:
            url = f"sqlite:///{directory}/upgrade.db"
            old = create_engine(url)
            # v1.6.8 has all existing tables, but neither billing table.
            old_tables = [table for name, table in SQLModel.metadata.tables.items()
                          if name not in {"host_subscription", "host_billing_alert_state"}]
            SQLModel.metadata.create_all(old, tables=old_tables)
            with Session(old) as session:
                session.add(HostConfig(host_id="vps", display_name="Existing VPS", traffic_billing_day=31))
                session.add(HostTrafficBucket(host_id="vps", ledger_id="old", agent_bucket_id=1,
                                            bucket_start=datetime.now(timezone.utc), counter_epoch="old", rx_bytes=123, tx_bytes=456))
                session.add(HostTrafficDaily(host_id="vps", day_utc="2026-01-01", rx_bytes=321))
                for key, value in {"NOTIFYHUB_URL": "http://notify", "NOTIFYHUB_KEY": "encrypted-test-key", "NOTIFYHUB_RECIPIENT": "person_1"}.items():
                    session.add(Setting(setting_key=key, setting_value=value))
                session.commit()
            old.dispose()
            settings = SimpleNamespace(DATABASE_URL=url, LOG_LEVEL="info")
            with patch.object(database, "get_settings", return_value=settings):
                upgraded = database.create_engine_and_tables()
            key = f"fleetge:billing:vps:{due}:1"
            with patch.object(billing_service, "engine", upgraded), patch.object(auto_update, "engine", upgraded):
                with Session(upgraded) as session:
                    session.add(HostSubscription(host_id="vps", provider="Existing provider", payment_amount=0,
                                                 service_expiry_date=due, quota_enabled=True, traffic_quota_value=1))
                    session.commit()
                manager = billing_service.BillingAlertManager()
                manager._enqueue(host_id="vps", alert_type="billing_due", alert_key=key, title="due", content="due")
                with notify_transport(lambda request: httpx.Response(503)):
                    asyncio.run(manager.dispatch_pending())
            upgraded.dispose()
            with patch.object(database, "get_settings", return_value=settings):
                reopened = database.create_engine_and_tables()
            try:
                with patch.object(billing_service, "engine", reopened), patch.object(auto_update, "engine", reopened):
                    with Session(reopened) as session:
                        self.assertEqual(session.exec(select(HostConfig)).one().display_name, "Existing VPS")
                        self.assertEqual(session.exec(select(HostTrafficBucket)).one().rx_bytes, 123)
                        self.assertEqual(session.exec(select(HostTrafficDaily)).one().rx_bytes, 321)
                        self.assertEqual(session.exec(select(HostSubscription)).one().payment_amount, 0)
                        self.assertEqual(session.exec(select(HostSubscription)).one().provider, "Existing provider")
                        alert = session.exec(select(HostBillingAlertState)).one()
                        self.assertEqual((alert.status, alert.attempts), ("pending", 1))
                        alert.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                        session.add(alert)
                        session.commit()
                    sent = []
                    def send(request):
                        sent.append(json.loads(request.content)["event_key"])
                        return httpx.Response(202, json={"data": {"status": "accepted", "event_id": "evt"}})
                    restarted = billing_service.BillingAlertManager()
                    with notify_transport(send):
                        asyncio.run(restarted.dispatch_pending())
                        restarted._enqueue(host_id="vps", alert_type="billing_due", alert_key=key, title="due", content="due")
                        asyncio.run(restarted.dispatch_pending())
                    self.assertEqual(sent, [key])
                    with Session(reopened) as session:
                        alert = session.exec(select(HostBillingAlertState)).one()
                        self.assertEqual((alert.status, alert.attempts), ("sent", 2))
            finally:
                reopened.dispose()


if __name__ == "__main__":
    unittest.main()
