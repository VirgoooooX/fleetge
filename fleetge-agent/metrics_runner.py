import os
import platform
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

try:
    import psutil
except ImportError:
    print("ERROR: psutil is required. Install with: pip install psutil", file=sys.stderr)
    sys.exit(1)

# Configuration from environment
DISK_PATHS = [p.strip() for p in os.environ.get("DISK_PATHS", "/").split(",") if p.strip()]
COLLECT_INTERVAL = float(os.environ.get("COLLECT_INTERVAL", "5"))
HOSTNAME = platform.node() or "unknown"

_cache_lock = threading.Lock()
_cached_metrics: dict = {}

# History for delta rate calculation
_last_time: Optional[float] = None
_last_net_rx: Optional[int] = None
_last_net_tx: Optional[int] = None
_last_disk_read: Optional[int] = None
_last_disk_write: Optional[int] = None


def _collect_once() -> dict:
    """Perform metrics collection and rate calculation."""
    global _last_time, _last_net_rx, _last_net_tx, _last_disk_read, _last_disk_write

    current_time = time.monotonic()
    
    # 1. CPU
    cpu = psutil.cpu_percent(interval=None)

    # 2. Memory
    mem = psutil.virtual_memory()

    # 3. Disk Usage
    disk_used = 0
    disk_total = 0
    disk_failures = []
    for path in DISK_PATHS:
        try:
            usage = psutil.disk_usage(path)
            disk_used += usage.used
            disk_total += usage.total
        except FileNotFoundError:
            disk_failures.append(path)

    # 4. Network Counters
    net = psutil.net_io_counters()
    net_rx = net.bytes_recv
    net_tx = net.bytes_sent

    # 5. Disk I/O Counters
    try:
        disk_io = psutil.disk_io_counters()
        disk_read = disk_io.read_bytes
        disk_write = disk_io.write_bytes
    except Exception:
        disk_read = 0
        disk_write = 0

    # 6. Load Average & Uptime
    load_raw = psutil.getloadavg()
    load_avg = [round(x, 2) for x in load_raw]
    uptime = int(time.time() - psutil.boot_time())

    # 7. Timestamp (ISO 8601 UTC)
    now_dt = datetime.now(timezone.utc)
    timestamp = now_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now_dt.microsecond // 1000:03d}Z"

    # 8. Calculate Rates (Delta / Delta Time)
    net_rx_rate = 0.0
    net_tx_rate = 0.0
    disk_read_rate = 0.0
    disk_write_rate = 0.0

    if _last_time is not None:
        dt = current_time - _last_time
        if dt > 0:
            if _last_net_rx is not None and net_rx >= _last_net_rx:
                net_rx_rate = round((net_rx - _last_net_rx) / dt, 2)
            if _last_net_tx is not None and net_tx >= _last_net_tx:
                net_tx_rate = round((net_tx - _last_net_tx) / dt, 2)
            if _last_disk_read is not None and disk_read >= _last_disk_read:
                disk_read_rate = round((disk_read - _last_disk_read) / dt, 2)
            if _last_disk_write is not None and disk_write >= _last_disk_write:
                disk_write_rate = round((disk_write - _last_disk_write) / dt, 2)

    # Update history
    _last_time = current_time
    _last_net_rx = net_rx
    _last_net_tx = net_tx
    _last_disk_read = disk_read
    _last_disk_write = disk_write

    result = {
        "hostname": HOSTNAME,
        "timestamp": timestamp,
        "cpuPercent": round(cpu, 1),
        "memoryUsed": mem.used,
        "memoryTotal": mem.total,
        "diskUsed": disk_used,
        "diskTotal": disk_total,
        "networkRxBytes": net_rx,
        "networkTxBytes": net_tx,
        "networkRxRate": net_rx_rate,
        "networkTxRate": net_tx_rate,
        "diskReadBytes": disk_read,
        "diskWriteBytes": disk_write,
        "diskReadRate": disk_read_rate,
        "diskWriteRate": disk_write_rate,
        "loadavg": load_avg,
        "uptime": uptime,
    }

    if disk_failures:
        result["_warnings"] = {"diskPathsNotFound": disk_failures}

    return result


def _collector_loop() -> None:
    """Background collection thread."""
    global _cached_metrics
    # Initialize CPU measurement baseline
    psutil.cpu_percent(interval=None)
    
    while True:
        try:
            snapshot = _collect_once()
            with _cache_lock:
                _cached_metrics = snapshot
        except Exception as exc:
            print(f"[agent-metrics] Collection failed: {exc}", file=sys.stderr)
        time.sleep(COLLECT_INTERVAL)


def get_metrics() -> dict:
    """Fetch cached metrics immediately. Never blocks."""
    with _cache_lock:
        if not _cached_metrics:
            raise RuntimeError("Metrics not ready yet — wait for first collection cycle")
        return dict(_cached_metrics)


def start_metrics_collector() -> None:
    """Starts the background collection loop."""
    collector = threading.Thread(target=_collector_loop, daemon=True, name="agent-metrics")
    collector.start()
