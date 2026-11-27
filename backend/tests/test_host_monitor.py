import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from app.models import HostConfig, HostMonitorState, HostStatusAlertOutbox, Setting
from app.services import auto_update
from app.services import host_monitor as hm
from app.services.crypto import encrypt_string


def _make_engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


def _seed_notify_settings(eng):
    with Session(eng) as session:
        session.add(Setting(setting_key="NOTIFYHUB_URL", setting_value="https://notify.test"))
        session.add(Setting(setting_key="NOTIFYHUB_RECIPIENT", setting_value="person_admin"))
        session.add(Setting(setting_key="NOTIFYHUB_KEY", setting_value=encrypt_string("nfy_test_key_123")))
        session.commit()


def _seed_hosts(eng):
    with Session(eng) as session:
        session.add(HostConfig(
            host_id="istoreos",
            display_name="iStoreOS",
            enabled=True,
            agent_url="http://192.168.31.100:8080/sec",
            logo="istoreos",
        ))
        session.add(HostConfig(
            host_id="lightlayer-la",
            display_name="Lightlayer LA",
            enabled=True,
            agent_url="https://agent.lightlayer.198909.xyz/sec",
            logo="lightlayer",
        ))
        session.add(HostConfig(
            host_id="oc-chicago",
            display_name="OC Chicago",
            enabled=True,
            agent_url="https://metrics.oc.198909.xyz/sec",
            logo="oracle",
        ))
        session.commit()


class HostMonitorTests(unittest.TestCase):
    def setUp(self):
        self.eng = _make_engine()
        _seed_notify_settings(self.eng)
        _seed_hosts(self.eng)
        self.manager = hm.HostMonitorManager()
        self.manager.retry_count = 2
        self.manager.retry_delay_seconds = 0.0
        self.manager.startup_grace_seconds = 0.0

    def _outbox_rows(self):
        with Session(self.eng) as session:
            return list(session.exec(select(HostStatusAlertOutbox).order_by(HostStatusAlertOutbox.id)).all())

    def test_debounce_ignores_transient_failure(self):
        calls = [
            hm.DirectProbeResult(ok=False, failed_stage="tls", tcp_ok=True, error="ReadTimeout"),
            hm.DirectProbeResult(ok=True, http_status=200, latency_ms=120, boot_id="boot-a", uptime_seconds=500),
        ]

        async def fake_direct(_host):
            return calls.pop(0)

        with patch.object(hm, "engine", self.eng), patch.object(auto_update, "engine", self.eng):
            with patch.object(self.manager, "_probe_direct_once", side_effect=fake_direct):
                summary = asyncio.run(self.manager.probe_host("lightlayer-la"))
        self.assertEqual(summary.state, "online")
        self.assertEqual(self._outbox_rows(), [])

    def test_blocked_detected_when_direct_fails_and_peer_succeeds(self):
        async def exercise():
            # Seed online state first
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(ok=True, http_status=200, latency_ms=140, boot_id="boot-ll", uptime_seconds=1000)),
            ):
                s1 = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s1.state, "online")
                self.assertEqual(self._outbox_rows(), [])

            # Now direct fails with TCP fake-open (tcp_ok=True, failed_stage="tls"), WAN ok, peer oc-chicago ok
            fail_res = hm.DirectProbeResult(
                ok=False,
                failed_stage="tls",
                tcp_ok=True,
                icmp_reachable=True,
                error="ConnectTimeout",
            )
            with (
                patch.object(self.manager, "_probe_direct_once", AsyncMock(return_value=fail_res)),
                patch.object(self.manager, "_check_local_wan_egress", AsyncMock(return_value=True)),
                patch.object(
                    self.manager,
                    "_call_peer_probe",
                    AsyncMock(return_value={"reachable": True, "http_status": 404, "upstream_error": False}),
                ),
            ):
                s2 = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s2.state, "blocked")
                self.assertIn("TCP 假通", s2.reason)
                self.assertIn("ICMP 可达", s2.reason)
                self.assertIn("OC Chicago", s2.reason)

            rows = self._outbox_rows()
            self.assertEqual(len(rows), 1)
            payload = json.loads(rows[0].payload)
            self.assertEqual(payload["event_type"], hm.ALERT_EVENT_TYPE)
            self.assertEqual(payload["level"], "warning")
            self.assertIn("疑似被墙", payload["title"])
            self.assertLessEqual(len(payload["title"]), 40)
            self.assertLessEqual(len(payload["content"].encode("utf-8")), 512)

            # Recovery with SAME boot_id -> recovered without reboot
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(ok=True, http_status=200, latency_ms=130, boot_id="boot-ll", uptime_seconds=2000)),
            ):
                s3 = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s3.state, "online")

            rows = self._outbox_rows()
            self.assertEqual(len(rows), 2)
            rec_payload = json.loads(rows[1].payload)
            self.assertEqual(rec_payload["event_type"], hm.RECOVERED_EVENT_TYPE)
            self.assertEqual(rec_payload["level"], "info")
            self.assertIn("主机未重启", rec_payload["content"])

        with patch.object(hm, "engine", self.eng), patch.object(auto_update, "engine", self.eng):
            asyncio.run(exercise())

    def test_offline_when_both_direct_and_peer_fail_and_escalates_from_blocked(self):
        async def exercise():
            # Start online
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(ok=True, http_status=200, latency_ms=150, boot_id="boot-1", uptime_seconds=500)),
            ):
                await self.manager.probe_host("lightlayer-la")

            # Blocked first
            fail_res = hm.DirectProbeResult(ok=False, failed_stage="tcp", tcp_ok=False, error="Timeout")
            with (
                patch.object(self.manager, "_probe_direct_once", AsyncMock(return_value=fail_res)),
                patch.object(self.manager, "_check_local_wan_egress", AsyncMock(return_value=True)),
                patch.object(self.manager, "_call_peer_probe", AsyncMock(return_value={"reachable": True, "http_status": 404})),
            ):
                s_blocked = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s_blocked.state, "blocked")

            # Then peer also fails -> escalates to offline
            with (
                patch.object(self.manager, "_probe_direct_once", AsyncMock(return_value=fail_res)),
                patch.object(self.manager, "_check_local_wan_egress", AsyncMock(return_value=True)),
                patch.object(self.manager, "_call_peer_probe", AsyncMock(return_value={"reachable": False, "failed_stage": "tcp"})),
            ):
                s_off = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s_off.state, "offline")

            rows = self._outbox_rows()
            self.assertEqual(len(rows), 2)
            self.assertIn("疑似被墙", json.loads(rows[0].payload)["title"])
            self.assertIn("主机失联", json.loads(rows[1].payload)["title"])

            # Recovers with NEW boot_id and clean=False -> single merged unclean-reboot recovery alert
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(
                    ok=True, http_status=200, latency_ms=160, boot_id="boot-2", uptime_seconds=90, last_boot_shutdown_clean=False,
                )),
            ):
                s_rec = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s_rec.state, "online")
                self.assertEqual(s_rec.last_reboot_type, "unclean")

            rows = self._outbox_rows()
            self.assertEqual(len(rows), 3)
            merged = json.loads(rows[2].payload)
            self.assertEqual(merged["event_type"], hm.ALERT_EVENT_TYPE)
            self.assertIn("异常重启恢复", merged["title"])

        with patch.object(hm, "engine", self.eng), patch.object(auto_update, "engine", self.eng):
            asyncio.run(exercise())

    def test_local_wan_outage_suppresses_public_alerts_but_not_lan(self):
        async def exercise():
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(ok=True, http_status=200, latency_ms=5, boot_id="b1")),
            ):
                await self.manager.probe_host("lightlayer-la")
                await self.manager.probe_host("istoreos")

            fail_res = hm.DirectProbeResult(ok=False, failed_stage="tcp", tcp_ok=False, error="NetworkError")
            with (
                patch.object(self.manager, "_probe_direct_once", AsyncMock(return_value=fail_res)),
                patch.object(self.manager, "_check_local_wan_egress", AsyncMock(return_value=False)),
                patch.object(self.manager, "_call_peer_probe", AsyncMock()) as peer_mock,
            ):
                s_pub = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s_pub.state, "online")  # suppressed!
                peer_mock.assert_not_called()

                s_lan = await self.manager.probe_host("istoreos")
                self.assertEqual(s_lan.state, "offline")  # LAN still transitions!
                peer_mock.assert_not_called()

            rows = self._outbox_rows()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].host_id, "istoreos")

        with patch.object(hm, "engine", self.eng), patch.object(auto_update, "engine", self.eng):
            asyncio.run(exercise())

    def test_agent_error_502_does_not_call_peers(self):
        async def exercise():
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(ok=True, http_status=200, latency_ms=100, boot_id="b1")),
            ):
                await self.manager.probe_host("lightlayer-la")

            err_502 = hm.DirectProbeResult(ok=False, agent_error=True, http_status=502, failed_stage="http", tcp_ok=True, error="HTTP 502")
            with (
                patch.object(self.manager, "_probe_direct_once", AsyncMock(return_value=err_502)),
                patch.object(self.manager, "_call_peer_probe", AsyncMock()) as peer_mock,
            ):
                s = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s.state, "agent_error")
                peer_mock.assert_not_called()

            rows = self._outbox_rows()
            self.assertEqual(len(rows), 1)
            self.assertIn("Agent异常", json.loads(rows[0].payload)["title"])

        with patch.object(hm, "engine", self.eng), patch.object(auto_update, "engine", self.eng):
            asyncio.run(exercise())

    def test_online_clean_and_unclean_reboot_notifications(self):
        async def exercise():
            # Seed online with boot-1
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(ok=True, http_status=200, latency_ms=80, boot_id="boot-1", uptime_seconds=3600)),
            ):
                await self.manager.probe_host("oc-chicago")

            # Clean reboot -> boot-2 (default notify_clean_reboot=True)
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(
                    ok=True, http_status=200, latency_ms=80, boot_id="boot-2", uptime_seconds=120, last_boot_shutdown_clean=True,
                )),
            ):
                s_clean = await self.manager.probe_host("oc-chicago")
                self.assertEqual(s_clean.last_reboot_type, "clean")

            rows = self._outbox_rows()
            self.assertEqual(len(rows), 1)
            p1 = json.loads(rows[0].payload)
            self.assertEqual(p1["event_type"], hm.RECOVERED_EVENT_TYPE)
            self.assertEqual(p1["level"], "info")
            self.assertIn("正常重启", p1["title"])

            # Disable clean reboot notifications -> boot-3 clean should NOT enqueue
            hm.set_host_monitor_alert_settings(enabled=True, notify_clean_reboot=False)
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(
                    ok=True, http_status=200, latency_ms=80, boot_id="boot-3", uptime_seconds=60, last_boot_shutdown_clean=True,
                )),
            ):
                await self.manager.probe_host("oc-chicago")
            self.assertEqual(len(self._outbox_rows()), 1)

            # Unclean reboot -> boot-4 ALWAYS notifies
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(
                    ok=True, http_status=200, latency_ms=80, boot_id="boot-4", uptime_seconds=90, last_boot_shutdown_clean=False,
                )),
            ):
                await self.manager.probe_host("oc-chicago")
            rows = self._outbox_rows()
            self.assertEqual(len(rows), 2)
            p2 = json.loads(rows[1].payload)
            self.assertEqual(p2["event_type"], hm.ALERT_EVENT_TYPE)
            self.assertEqual(p2["level"], "warning")
            self.assertIn("异常重启", p2["title"])

        with patch.object(hm, "engine", self.eng), patch.object(auto_update, "engine", self.eng):
            asyncio.run(exercise())

    def test_save_notify_settings_unblocks_host_status_outbox(self):
        now = datetime.now(timezone.utc)
        with Session(self.eng) as session:
            session.add(HostStatusAlertOutbox(
                alert_key="fleetge:host-status:oc-chicago:inc-1:offline",
                host_id="oc-chicago",
                event_type=hm.ALERT_EVENT_TYPE,
                status="blocked",
                notify_url="https://notify.test",
                notify_recipient="person_admin",
                payload="{}",
                expires_at=now + timedelta(hours=12),
                last_error="HTTP 403",
            ))
            session.commit()

        with patch.object(auto_update, "engine", self.eng):
            auto_update.save_notify_settings("https://notify.test", "person_admin", "nfy_new_key_456")

        rows = self._outbox_rows()
        self.assertEqual(rows[0].status, "pending")
        self.assertEqual(rows[0].last_error, "")

    def test_metrics_payload_serializes_monitor_datetimes_for_sse(self):
        from app.schemas import HostMonitorSummary, HostSummary
        from app.services.metrics_broadcaster import metrics_payload

        now = datetime.now(timezone.utc)
        summary = HostSummary(
            host_id="lightlayer-la",
            display_name="Lightlayer LA",
            status="online",
            monitor=HostMonitorSummary(
                state="online",
                state_since=now,
                last_checked_at=now,
                last_ok_at=now,
                last_reboot_at=now,
                latency_ms=120,
            ),
        )
        encoded = json.dumps(metrics_payload([summary]), ensure_ascii=False)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["hosts"][0]["monitor"]["state"], "online")
        self.assertIsInstance(decoded["hosts"][0]["monitor"]["state_since"], str)

    def test_blocked_extra_confirm_suppresses_short_cross_border_jitter(self):
        """WAN host fails 3 times (initial + 2 retries), peer succeeds, then 4th confirmation probe succeeds -> stays online with 0 alerts."""
        async def exercise():
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(ok=True, http_status=200, latency_ms=140, boot_id="boot-z")),
            ):
                await self.manager.probe_host("lightlayer-la")

            fail_res = hm.DirectProbeResult(
                ok=False, failed_stage="tls", tls_error_kind="timeout", tcp_ok=True, icmp_reachable=False, error="Timeout"
            )
            ok_res = hm.DirectProbeResult(ok=True, http_status=200, latency_ms=150, boot_id="boot-z")
            calls = [fail_res, fail_res, fail_res, ok_res]

            async def fake_direct(_host):
                return calls.pop(0)

            with (
                patch.object(self.manager, "_probe_direct_once", side_effect=fake_direct),
                patch.object(self.manager, "_check_local_wan_egress", AsyncMock(return_value=True)),
                patch.object(self.manager, "_call_peer_probe", AsyncMock(return_value={"reachable": True, "http_status": 404})),
            ):
                s = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s.state, "online")
                self.assertEqual(calls, [])

            self.assertEqual(self._outbox_rows(), [])

        with patch.object(hm, "engine", self.eng), patch.object(auto_update, "engine", self.eng):
            asyncio.run(exercise())

    def test_wan_recovery_hysteresis_ignores_single_flash_success(self):
        """A WAN host in blocked state must succeed twice consecutively before transitioning back to online."""
        async def exercise():
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(ok=True, http_status=200, latency_ms=120, boot_id="boot-1")),
            ):
                await self.manager.probe_host("lightlayer-la")

            fail_res = hm.DirectProbeResult(
                ok=False, failed_stage="tls", tls_error_kind="reset", tcp_ok=True, icmp_reachable=True, error="ConnectionResetError"
            )
            with (
                patch.object(self.manager, "_probe_direct_once", AsyncMock(return_value=fail_res)),
                patch.object(self.manager, "_check_local_wan_egress", AsyncMock(return_value=True)),
                patch.object(self.manager, "_call_peer_probe", AsyncMock(return_value={"reachable": True, "http_status": 404})),
            ):
                s_blk = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s_blk.state, "blocked")
                self.assertIn("TLS 连接被重置", s_blk.reason)

            # Flash success once then fail on recovery confirmation -> stays blocked, no recovery alert
            ok_res = hm.DirectProbeResult(ok=True, http_status=200, latency_ms=130, boot_id="boot-1")
            flash_calls = [ok_res, fail_res]

            async def fake_flash(_host):
                return flash_calls.pop(0)

            with patch.object(self.manager, "_probe_direct_once", side_effect=fake_flash):
                s_hold = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s_hold.state, "blocked")
            self.assertEqual(len(self._outbox_rows()), 1)

            # Two consecutive successes -> transitions to online and enqueues recovery
            with patch.object(self.manager, "_probe_direct_once", AsyncMock(return_value=ok_res)):
                s_ok = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s_ok.state, "online")
            self.assertEqual(len(self._outbox_rows()), 2)

        with patch.object(hm, "engine", self.eng), patch.object(auto_update, "engine", self.eng):
            asyncio.run(exercise())

    def test_tls_timeout_vs_reset_reason_and_tiered_defaults(self):
        fresh = hm.HostMonitorManager()
        self.assertEqual(fresh._effective_retry_delays(is_lan=True, skip_retry_delay=False), [15.0, 30.0])
        self.assertEqual(fresh._effective_retry_delays(is_lan=False, skip_retry_delay=False), [30.0, 60.0])
        self.assertEqual(fresh.wan_blocked_extra_delay, 90.0)
        self.assertEqual(fresh.wan_recovery_confirm_delay, 30.0)

        timeout_res = hm.DirectProbeResult(ok=False, failed_stage="tls", tls_error_kind="timeout", tcp_ok=True, icmp_reachable=False)
        reset_res = hm.DirectProbeResult(ok=False, failed_stage="tls", tls_error_kind="reset", tcp_ok=True, icmp_reachable=True)
        peer = {"peer_name": "OC Chicago"}
        self.assertIn("TLS 握手超时", fresh._build_failure_reason("blocked", timeout_res, peer, is_lan=False))
        self.assertIn("TLS 连接被重置", fresh._build_failure_reason("blocked", reset_res, peer, is_lan=False))
        self.assertIn("近期线路频繁波动", fresh._build_failure_reason("blocked", timeout_res, peer, is_lan=False, is_flapping=True))

    def test_recovery_cancels_retrying_unsent_alert_outbox(self):
        async def exercise():
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(ok=True, http_status=200, latency_ms=100, boot_id="boot-c")),
            ):
                await self.manager.probe_host("lightlayer-la")

            fail_res = hm.DirectProbeResult(ok=False, failed_stage="tcp", tcp_ok=False, error="Timeout")
            with (
                patch.object(self.manager, "_probe_direct_once", AsyncMock(return_value=fail_res)),
                patch.object(self.manager, "_check_local_wan_egress", AsyncMock(return_value=True)),
                patch.object(self.manager, "_call_peer_probe", AsyncMock(return_value={"reachable": False})),
            ):
                s_off = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s_off.state, "offline")

            # Simulate Notify Hub temporary outage: alert attempted twice and still pending retry
            with Session(self.eng) as session:
                alert = session.exec(select(HostStatusAlertOutbox)).first()
                alert.attempts = 2
                session.add(alert)
                session.commit()

            # Host recovers -> pending retrying alert is cancelled and no redundant recovery alert is enqueued
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(ok=True, http_status=200, latency_ms=100, boot_id="boot-c")),
            ):
                s_rec = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s_rec.state, "online")

            rows = self._outbox_rows()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "cancelled")

        with patch.object(hm, "engine", self.eng), patch.object(auto_update, "engine", self.eng):
            asyncio.run(exercise())

    def test_flapping_or_multi_wan_extends_blocked_confirmation_rounds(self):
        async def exercise():
            with patch.object(
                self.manager,
                "_probe_direct_once",
                AsyncMock(return_value=hm.DirectProbeResult(ok=True, http_status=200, latency_ms=100, boot_id="boot-f")),
            ):
                await self.manager.probe_host("lightlayer-la")

            # Pre-seed 2 recent recoveries -> flapping=True, expects 1 initial + 2 retries + 2 extra blocked confirms = 5 calls
            now = hm.utc_now()
            self.manager._flap_history["lightlayer-la"] = [now - timedelta(minutes=10), now - timedelta(minutes=5)]

            fail_res = hm.DirectProbeResult(ok=False, failed_stage="tls", tls_error_kind="timeout", tcp_ok=True, icmp_reachable=False)
            probe_mock = AsyncMock(return_value=fail_res)
            with (
                patch.object(self.manager, "_probe_direct_once", probe_mock),
                patch.object(self.manager, "_check_local_wan_egress", AsyncMock(return_value=True)),
                patch.object(self.manager, "_call_peer_probe", AsyncMock(return_value={"reachable": True, "http_status": 404})),
            ):
                s = await self.manager.probe_host("lightlayer-la")
                self.assertEqual(s.state, "blocked")
                self.assertEqual(probe_mock.await_count, 5)
                self.assertTrue(s.diagnostics["flapping"])
                self.assertIn("近期线路频繁波动", s.reason)

        with patch.object(hm, "engine", self.eng), patch.object(auto_update, "engine", self.eng):
            asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
