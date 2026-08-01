"""Adaptive Host telemetry coordinator.

Telemetry sleeps when there is no authenticated metrics demand. WAN counters keep
their own low-frequency accounting cycle so traffic totals do not depend on a UI.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("fleetge-agent.metrics")

try:
    import psutil
except ImportError:
    logger.error("psutil is required. Install with: pip install psutil")
    sys.exit(1)

from traffic_accountant import TrafficAccountant

DISK_PATHS = [path.strip() for path in os.environ.get("DISK_PATHS", "/").split(",") if path.strip()]
METRICS_ACTIVE_INTERVAL = max(
    0.5,
    float(os.environ.get("METRICS_ACTIVE_INTERVAL", os.environ.get("COLLECT_INTERVAL", "2"))),
)
TRAFFIC_IDLE_INTERVAL = max(10.0, float(os.environ.get("TRAFFIC_IDLE_INTERVAL", "60")))
METRICS_IDLE_TIMEOUT = max(2.0, float(os.environ.get("METRICS_IDLE_TIMEOUT", "15")))
HOSTNAME = platform.node() or "unknown"


def _utc_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MetricsCoordinator:
    def __init__(self, traffic: TrafficAccountant | None = None) -> None:
        self.traffic = traffic or TrafficAccountant()
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cached_metrics: dict[str, Any] = {}
        self._snapshot_mono = 0.0
        self._last_demand_mono = float("-inf")
        self._last_telemetry_mono = 0.0
        self._last_traffic_mono = 0.0
        self._last_disk_mono: float | None = None
        self._last_disk_read: int | None = None
        self._last_disk_write: int | None = None
        self._collector_state = "idle"

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            psutil.cpu_percent(interval=None)
            self._thread = threading.Thread(target=self._run, daemon=True, name="agent-metrics")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5.0)
        self.traffic.close()

    def mark_demand(self) -> float:
        requested_at = time.monotonic()
        with self._lock:
            self._last_demand_mono = requested_at
        self._wake.set()
        return requested_at

    def _is_active(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            return current - self._last_demand_mono <= METRICS_IDLE_TIMEOUT

    def _collect_telemetry(self, now_mono: float, traffic: dict[str, Any]) -> dict[str, Any]:
        elapsed = now_mono - self._last_telemetry_mono if self._last_telemetry_mono else None
        warming = elapsed is None or elapsed > METRICS_ACTIVE_INTERVAL * 3
        # After a long idle, interval=None would average the entire sleep window.
        # A short blocking sample keeps the first visible CPU value current while
        # disk/network rates remain explicitly warming until their second point.
        cpu = psutil.cpu_percent(interval=0.25 if warming else None)
        memory = psutil.virtual_memory()

        disk_used = 0
        disk_total = 0
        disk_failures: list[str] = []
        for path in DISK_PATHS:
            try:
                usage = psutil.disk_usage(path)
                disk_used += int(usage.used)
                disk_total += int(usage.total)
            except (FileNotFoundError, OSError):
                disk_failures.append(path)

        try:
            disk_io = psutil.disk_io_counters()
            disk_read = int(disk_io.read_bytes) if disk_io else 0
            disk_write = int(disk_io.write_bytes) if disk_io else 0
        except Exception:
            disk_read = disk_write = 0

        disk_read_rate: float | None = None
        disk_write_rate: float | None = None
        if (
            not warming
            and self._last_disk_mono is not None
            and self._last_disk_read is not None
            and self._last_disk_write is not None
            and disk_read >= self._last_disk_read
            and disk_write >= self._last_disk_write
        ):
            dt = now_mono - self._last_disk_mono
            if dt > 0:
                disk_read_rate = round((disk_read - self._last_disk_read) / dt, 2)
                disk_write_rate = round((disk_write - self._last_disk_write) / dt, 2)

        self._last_disk_mono = now_mono
        self._last_disk_read = disk_read
        self._last_disk_write = disk_write
        try:
            load_avg = [round(value, 2) for value in psutil.getloadavg()]
        except (AttributeError, OSError):
            load_avg = [0.0, 0.0, 0.0]

        result: dict[str, Any] = {
            "hostname": HOSTNAME,
            "timestamp": _utc_timestamp(),
            "cpuPercent": round(cpu, 1),
            "memoryUsed": int(memory.used),
            "memoryTotal": int(memory.total),
            "diskUsed": disk_used,
            "diskTotal": disk_total,
            "diskReadBytes": disk_read,
            "diskWriteBytes": disk_write,
            "diskReadRate": disk_read_rate,
            "diskWriteRate": disk_write_rate,
            "loadavg": load_avg,
            "uptime": int(time.time() - psutil.boot_time()),
            "collectorState": "warming" if warming else "active",
            "sampleAgeSeconds": 0.0,
            "metricsActiveInterval": METRICS_ACTIVE_INTERVAL,
            "trafficIdleInterval": TRAFFIC_IDLE_INTERVAL,
            **traffic,
        }
        # Traffic has its own timestamp; the telemetry timestamp remains canonical.
        result.pop("timestamp", None)
        result["timestamp"] = _utc_timestamp()
        if disk_failures:
            result["_warnings"] = {"diskPathsNotFound": disk_failures}
        return result

    def _run(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            active = self._is_active(now)
            traffic_interval = METRICS_ACTIVE_INTERVAL if active else TRAFFIC_IDLE_INTERVAL
            traffic_due = not self._last_traffic_mono or now - self._last_traffic_mono >= traffic_interval
            telemetry_due = active and (
                not self._last_telemetry_mono or now - self._last_telemetry_mono >= METRICS_ACTIVE_INTERVAL
            )
            traffic = self.traffic.current()
            if traffic_due:
                try:
                    traffic = self.traffic.sample(active=active)
                    self._last_traffic_mono = time.monotonic()
                except Exception as exc:
                    logger.error("WAN traffic collection failed: %s", exc)

            if telemetry_due:
                try:
                    collected_at = time.monotonic()
                    snapshot = self._collect_telemetry(collected_at, traffic)
                    with self._condition:
                        self._cached_metrics = snapshot
                        self._snapshot_mono = time.monotonic()
                        self._last_telemetry_mono = collected_at
                        self._collector_state = snapshot["collectorState"]
                        self._condition.notify_all()
                except Exception as exc:
                    logger.error("Host telemetry collection failed: %s", exc)
            elif not active:
                with self._lock:
                    self._collector_state = "idle"

            now = time.monotonic()
            if active:
                due_in = min(
                    max(0.05, METRICS_ACTIVE_INTERVAL - (now - self._last_telemetry_mono)),
                    max(0.05, METRICS_ACTIVE_INTERVAL - (now - self._last_traffic_mono)),
                    max(0.05, METRICS_IDLE_TIMEOUT - (now - self._last_demand_mono)),
                )
            else:
                due_in = max(0.05, TRAFFIC_IDLE_INTERVAL - (now - self._last_traffic_mono))
            self._wake.wait(timeout=due_in)
            self._wake.clear()

    def metrics(self, wait_timeout: float = 1.0) -> dict[str, Any]:
        requested_at = self.mark_demand()
        with self._condition:
            fresh_enough = self._cached_metrics and requested_at - self._snapshot_mono <= METRICS_ACTIVE_INTERVAL * 1.5
            if not fresh_enough:
                self._condition.wait_for(
                    lambda: self._snapshot_mono >= requested_at or self._stop.is_set(),
                    timeout=max(0.0, wait_timeout),
                )
            if not self._cached_metrics:
                raise RuntimeError("Metrics not ready yet — wait for first collection cycle")
            result = dict(self._cached_metrics)
            result["sampleAgeSeconds"] = round(max(0.0, time.monotonic() - self._snapshot_mono), 3)
            return result

    def traffic_current(self, *, activate: bool = False) -> dict[str, Any]:
        if activate:
            self.mark_demand()
        result = self.traffic.current()
        result["collectorState"] = "active" if self._is_active() else "idle"
        return result


_coordinator = MetricsCoordinator()


def get_metrics(wait_timeout: float = 1.0) -> dict[str, Any]:
    return _coordinator.metrics(wait_timeout=wait_timeout)


def get_traffic_current(activate: bool = False) -> dict[str, Any]:
    return _coordinator.traffic_current(activate=activate)


def get_traffic_history(cursor: int = 0, limit: int = 1000) -> dict[str, Any]:
    return _coordinator.traffic.history(cursor=cursor, limit=limit)


def start_metrics_collector() -> None:
    _coordinator.start()


def stop_metrics_collector() -> None:
    _coordinator.stop()
