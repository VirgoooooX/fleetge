#!/usr/bin/env python3
"""
host-metrics-exporter

Minimal read-only HTTP metrics exporter for Docker Dashboard.
One endpoint: GET /metrics/json → host CPU/memory/disk/network/load/uptime.

Environment:
  PORT          - listen port (default: 8000)
  DISK_PATHS    - comma-separated mount points to monitor (default: /)
  METRICS_USER  - optional Basic Auth username (omit = no auth)
  METRICS_PASS  - optional Basic Auth password

Usage:
  python exporter.py
"""

import json
import os
import platform
import signal
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from typing import NoReturn

try:
    import psutil
except ImportError:
    print("ERROR: psutil is required. Install with: pip install psutil", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT = int(os.environ.get("PORT", "8000"))
DISK_PATHS = [p.strip() for p in os.environ.get("DISK_PATHS", "/").split(",") if p.strip()]
METRICS_USER = os.environ.get("METRICS_USER", "")
METRICS_PASS = os.environ.get("METRICS_PASS", "")
HOSTNAME = platform.node() or "unknown"

# ---------------------------------------------------------------------------
# Rate tracking — prev values for network & disk I/O rate calculation
# ---------------------------------------------------------------------------

_prev_net: tuple | None = None
_prev_disk: tuple | None = None
_prev_time: float = 0.0


def _safe_float(val, default=0.0) -> float:
    """Return val as float, or default on any error."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Metrics collection
# ---------------------------------------------------------------------------


def collect() -> dict:
    """Return a snapshot of host metrics, including network and disk I/O rates."""
    now = time.monotonic()
    global _prev_net, _prev_disk, _prev_time

    # CPU
    cpu = psutil.cpu_percent(interval=1)

    # Memory
    mem = psutil.virtual_memory()

    # Disk — sum usage across configured mount points
    disk_used: int = 0
    disk_total: int = 0
    disk_failures: list[str] = []
    for path in DISK_PATHS:
        try:
            usage = psutil.disk_usage(path)
            disk_used += usage.used
            disk_total += usage.total
        except FileNotFoundError:
            disk_failures.append(path)

    # Network — cumulative counters since boot (sum of all NICs)
    net = psutil.net_io_counters()

    # Disk I/O — cumulative counters since boot
    try:
        disk_io = psutil.disk_io_counters()
        disk_read_bytes = disk_io.read_bytes
        disk_write_bytes = disk_io.write_bytes
    except Exception:
        disk_io = None
        disk_read_bytes = 0
        disk_write_bytes = 0

    # Compute rates from deltas
    dt = now - _prev_time if _prev_time > 0 else 0
    network_rx_rate = 0.0
    network_tx_rate = 0.0
    disk_read_rate = 0.0
    disk_write_rate = 0.0

    if dt > 0 and _prev_net is not None:
        drx = net.bytes_recv - _prev_net[0]
        dtx = net.bytes_sent - _prev_net[1]
        network_rx_rate = round(drx / dt, 1) if drx >= 0 else 0.0
        network_tx_rate = round(dtx / dt, 1) if dtx >= 0 else 0.0

    if dt > 0 and _prev_disk is not None:
        drb = disk_read_bytes - _prev_disk[0]
        dwb = disk_write_bytes - _prev_disk[1]
        disk_read_rate = round(drb / dt, 1) if drb >= 0 else 0.0
        disk_write_rate = round(dwb / dt, 1) if dwb >= 0 else 0.0

    # Update state for next call
    _prev_net = (net.bytes_recv, net.bytes_sent)
    _prev_disk = (disk_read_bytes, disk_write_bytes)
    _prev_time = now

    # Load average
    load_raw = psutil.getloadavg()
    load_avg = [round(x, 2) for x in load_raw]

    # Uptime (seconds since boot)
    uptime = int(time.time() - psutil.boot_time())

    # Timestamp (ISO 8601 with milliseconds)
    now_dt = datetime.now(timezone.utc)
    timestamp = now_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now_dt.microsecond // 1000:03d}Z"

    result: dict = {
        "hostname": HOSTNAME,
        "timestamp": timestamp,
        "cpuPercent": round(cpu, 1),
        "memoryUsed": mem.used,
        "memoryTotal": mem.total,
        "diskUsed": disk_used,
        "diskTotal": disk_total,
        "networkRxBytes": net.bytes_recv,
        "networkTxBytes": net.bytes_sent,
        "networkRxRate": network_rx_rate,
        "networkTxRate": network_tx_rate,
        "diskReadBytes": disk_read_bytes,
        "diskWriteBytes": disk_write_bytes,
        "diskReadRate": disk_read_rate,
        "diskWriteRate": disk_write_rate,
        "loadavg": load_avg,
        "uptime": uptime,
    }

    if disk_failures:
        result["_warnings"] = {"diskPathsNotFound": disk_failures}

    return result


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class MetricsHandler(BaseHTTPRequestHandler):
    """Single-endpoint HTTP server returning JSON metrics."""

    def do_GET(self) -> None:
        if self.path != "/metrics/json":
            self._send_json(404, {"error": "not_found", "message": f"Unknown path: {self.path}"})
            return

        # Basic Auth check
        if METRICS_USER or METRICS_PASS:
            if not self._check_auth():
                self._send_auth_required()
                return

        try:
            data = collect()
            self._send_json(200, data)
        except Exception as exc:
            self._send_json(500, {"error": "collection_failed", "message": str(exc)})

    def do_HEAD(self) -> None:
        """Health-check via HEAD /metrics/json — returns only headers."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    # -- helpers -----------------------------------------------------------

    def _check_auth(self) -> bool:
        """Validate Basic Auth header against METRICS_USER / METRICS_PASS."""
        import base64

        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            user, _, pw = decoded.partition(":")
            return user == METRICS_USER and pw == METRICS_PASS
        except Exception:
            return False

    def _send_auth_required(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="metrics"')
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "unauthorized"}).encode())

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body.encode())

    # -- silence default logging (too noisy) -------------------------------

    def log_message(self, fmt: str, *args) -> None:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> NoReturn:
    server = HTTPServer(("0.0.0.0", PORT), MetricsHandler)

    # Graceful shutdown
    def shutdown(sig, frame) -> None:
        print(f"\n[exporter] Received signal {sig}, shutting down.", file=sys.stderr)
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    print(
        f"[exporter] host={HOSTNAME} listening on 0.0.0.0:{PORT} "
        f"disk_paths={DISK_PATHS} auth={'yes' if METRICS_USER else 'no'}",
        file=sys.stderr,
    )

    server.serve_forever()


if __name__ == "__main__":
    main()
