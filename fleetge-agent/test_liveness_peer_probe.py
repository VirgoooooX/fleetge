import asyncio
import json
import os
import pytest
from fastapi.testclient import TestClient

os.environ["AGENT_TOKEN"] = "test-secret-token-0123456789abcdef"
os.environ["STACKS_BASE_DIR"] = "/tmp/test-stacks"

import liveness
import metrics_runner
import peer_probe
from main import app

AUTH_HEADERS = {"Authorization": "Bearer test-secret-token-0123456789abcdef"}


def test_lifecycle_tracker_distinguishes_clean_unclean_and_container_restart(tmp_path):
    boot_file = tmp_path / "boot_id"
    state_dir = tmp_path / "state"

    # 1. First boot ever
    boot_file.write_text("boot-1\n", encoding="utf-8")
    t1 = liveness.LifecycleTracker(state_dir=str(state_dir), boot_id_path=str(boot_file))
    t1.record_startup()
    p1 = t1.payload()
    assert p1["boot_id"] == "boot-1"
    assert p1["last_boot_shutdown_clean"] is None
    assert p1["previous_boot_id"] is None

    # 2. Agent container restarts gracefully on SAME host boot -> preserve None, NOT a reboot
    t1.record_graceful_shutdown()
    t2 = liveness.LifecycleTracker(state_dir=str(state_dir), boot_id_path=str(boot_file))
    t2.record_startup()
    p2 = t2.payload()
    assert p2["boot_id"] == "boot-1"
    assert p2["previous_boot_id"] is None
    assert p2["last_boot_shutdown_clean"] is None

    # 3. Clean host reboot -> new boot_id, last_boot_shutdown_clean=True
    t2.record_graceful_shutdown()
    boot_file.write_text("boot-2\n", encoding="utf-8")
    t3 = liveness.LifecycleTracker(state_dir=str(state_dir), boot_id_path=str(boot_file))
    t3.record_startup()
    p3 = t3.payload()
    assert p3["boot_id"] == "boot-2"
    assert p3["previous_boot_id"] == "boot-1"
    assert p3["last_boot_shutdown_clean"] is True

    # 4. Unclean crash/power-loss (NO record_graceful_shutdown called!) -> new boot_id, clean=False
    boot_file.write_text("boot-3\n", encoding="utf-8")
    t4 = liveness.LifecycleTracker(state_dir=str(state_dir), boot_id_path=str(boot_file))
    t4.record_startup()
    p4 = t4.payload()
    assert p4["boot_id"] == "boot-3"
    assert p4["previous_boot_id"] == "boot-2"
    assert p4["last_boot_shutdown_clean"] is False

    # 5. Agent container restart after unclean host boot still preserves last_boot_shutdown_clean=False
    t4.record_graceful_shutdown()
    t5 = liveness.LifecycleTracker(state_dir=str(state_dir), boot_id_path=str(boot_file))
    t5.record_startup()
    p5 = t5.payload()
    assert p5["boot_id"] == "boot-3"
    assert p5["previous_boot_id"] == "boot-2"
    assert p5["last_boot_shutdown_clean"] is False


def test_liveness_endpoint_requires_token_and_does_not_wake_telemetry(monkeypatch):
    woken = []
    monkeypatch.setattr(metrics_runner._coordinator, "mark_demand", lambda: woken.append(True))

    client = TestClient(app)
    assert client.get("/api/agent/liveness").status_code == 401
    resp = client.get("/api/agent/liveness", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert woken == []


def test_peer_probe_rejects_private_and_metadata_targets():
    client = TestClient(app)
    for bad_host in ("127.0.0.1", "192.168.31.100", "10.0.0.1", "169.254.169.254", "localhost", "metadata.google.internal"):
        resp = client.post(
            "/api/agent/peer-probe",
            json={"host": bad_host, "port": 443, "scheme": "https"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code in (400, 422), f"Expected 400/422 for {bad_host}, got {resp.status_code}"


def test_peer_probe_layered_http_reachability():
    async def exercise():
        async def handle_client(reader, writer):
            await reader.read(512)
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            res = await peer_probe.run_peer_probe(
                peer_probe.PeerProbeRequest(host="127.0.0.1", port=port, scheme="http", timeout_seconds=3.0),
                allow_private_for_tests=True,
            )
            assert res["reachable"] is True
            assert res["tcp_ok"] is True
            assert res["http_ok"] is True
            assert res["http_status"] == 404
            assert res["upstream_error"] is False
            assert res["failed_stage"] is None
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(exercise())


def test_peer_probe_detects_tcp_hang_at_http_stage():
    async def exercise():
        stop_event = asyncio.Event()

        async def hang_client(reader, writer):
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            finally:
                writer.close()

        server = await asyncio.start_server(hang_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            res = await peer_probe.run_peer_probe(
                peer_probe.PeerProbeRequest(host="127.0.0.1", port=port, scheme="http", timeout_seconds=1.0),
                allow_private_for_tests=True,
            )
            assert res["reachable"] is False
            assert res["tcp_ok"] is True
            assert res["http_ok"] is False
            assert res["failed_stage"] == "http"
        finally:
            stop_event.set()
            server.close()
            await server.wait_closed()

    asyncio.run(exercise())
