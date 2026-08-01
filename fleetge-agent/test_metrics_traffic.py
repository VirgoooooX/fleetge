import asyncio
import time
from types import SimpleNamespace

import metrics_runner
import network_identity
import traffic_accountant


def _counter(rx: int, tx: int):
    return SimpleNamespace(bytes_recv=rx, bytes_sent=tx)


def test_traffic_accountant_persists_delta_and_completed_bucket(monkeypatch, tmp_path):
    values = {"eth0": _counter(1000, 2000)}
    monkeypatch.setattr(traffic_accountant, "_boot_id", lambda: "boot-a")
    monkeypatch.setattr(traffic_accountant.psutil, "net_io_counters", lambda pernic=True: values)
    monkeypatch.setattr(traffic_accountant, "_interface_index", lambda name: 2)
    accountant = traffic_accountant.TrafficAccountant(str(tmp_path), "eth0")

    first = accountant.sample(active=False)
    assert first["networkScope"] == "host_wan"
    assert first["networkRxTotalBytes"] == 0

    # Force the next delta across a UTC five-minute boundary.
    now = time.time()
    accountant._last_wall = int(now // 300) * 300 - 1
    values["eth0"] = _counter(1600, 2900)
    second = accountant.sample(active=True)
    assert second["networkRxTotalBytes"] == 600
    assert second["networkTxTotalBytes"] == 900
    accountant.close()

    history = accountant.history()
    assert history["ledgerId"]
    assert history["buckets"]
    assert sum(row["rxBytes"] for row in history["buckets"]) <= 600


def test_traffic_counter_reset_starts_new_epoch_and_marks_gap(monkeypatch, tmp_path):
    values = {"pppoe-wan": _counter(5000, 8000)}
    monkeypatch.setattr(traffic_accountant, "_boot_id", lambda: "boot-a")
    monkeypatch.setattr(traffic_accountant.psutil, "net_io_counters", lambda pernic=True: values)
    monkeypatch.setattr(traffic_accountant, "_interface_index", lambda name: 9)
    accountant = traffic_accountant.TrafficAccountant(str(tmp_path), "pppoe-wan")
    first = accountant.sample(active=False)
    values["pppoe-wan"] = _counter(100, 200)
    second = accountant.sample(active=False)
    assert second["networkCounterEpoch"] != first["networkCounterEpoch"]
    assert second["counterReset"] is True
    assert second["hasGap"] is True


def test_metrics_coordinator_stops_telemetry_after_idle_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics_runner, "METRICS_ACTIVE_INTERVAL", 0.05)
    monkeypatch.setattr(metrics_runner, "METRICS_IDLE_TIMEOUT", 0.1)
    monkeypatch.setattr(metrics_runner, "TRAFFIC_IDLE_INTERVAL", 0.2)
    traffic = traffic_accountant.TrafficAccountant(str(tmp_path), "missing0")
    coordinator = metrics_runner.MetricsCoordinator(traffic)
    calls = 0
    original = coordinator._collect_telemetry

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(coordinator, "_collect_telemetry", counted)
    coordinator.start()
    try:
        snapshot = coordinator.metrics(wait_timeout=1.0)
        assert snapshot["collectorState"] in {"warming", "active"}
        time.sleep(0.22)
        after_idle = calls
        time.sleep(0.14)
        assert calls == after_idle
    finally:
        coordinator.stop()


def test_network_identity_requires_two_matching_providers(monkeypatch):
    async def fake_fetch(provider, url, family):
        if family == 4:
            address = "203.0.113.10" if provider != "cloudflare" else "203.0.113.11"
        else:
            return {"provider": provider, "status": "error", "error": "ConnectError"}
        return {"provider": provider, "status": "ok", "address": address}

    monkeypatch.setattr(network_identity, "_fetch_provider", fake_fetch)
    family = asyncio.run(network_identity._probe_family(4))
    assert family["trusted"] is True
    assert family["agreementCount"] == 2
    assert family["address"] == "203.0.113.10"
