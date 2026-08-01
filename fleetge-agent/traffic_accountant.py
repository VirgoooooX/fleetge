"""Host WAN traffic accounting with a small durable five-minute ledger."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import secrets
import socket
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

logger = logging.getLogger("fleetge-agent.traffic")

BUCKET_SECONDS = 300
RETENTION_SECONDS = 90 * 24 * 60 * 60
_EXCLUDED_PREFIXES = ("lo", "docker", "veth", "br-", "virbr", "ifb")


def _utc_iso(epoch: float | None = None) -> str:
    value = datetime.fromtimestamp(epoch if epoch is not None else time.time(), timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except Exception:
        return f"boot-{int(psutil.boot_time())}"


def _is_usable_interface(name: str) -> bool:
    lowered = name.lower()
    return not any(lowered == prefix or lowered.startswith(prefix) for prefix in _EXCLUDED_PREFIXES)


def _default_route_interfaces() -> list[str]:
    """Return the lowest-metric IPv4/IPv6 default-route interfaces."""
    selected: list[tuple[int, str]] = []
    try:
        rows = Path("/proc/net/route").read_text(encoding="utf-8").splitlines()[1:]
        defaults: list[tuple[int, str]] = []
        for row in rows:
            columns = row.split()
            if len(columns) < 8 or columns[1] != "00000000":
                continue
            try:
                flags = int(columns[3], 16)
                metric = int(columns[6])
            except ValueError:
                continue
            if flags & 0x1 and _is_usable_interface(columns[0]):
                defaults.append((metric, columns[0]))
        if defaults:
            best_metric = min(metric for metric, _ in defaults)
            selected.extend(item for item in defaults if item[0] == best_metric)
    except Exception:
        pass

    try:
        rows = Path("/proc/net/ipv6_route").read_text(encoding="utf-8").splitlines()
        defaults_v6: list[tuple[int, str]] = []
        for row in rows:
            columns = row.split()
            if len(columns) < 10:
                continue
            if columns[0] != "0" * 32 or columns[1] != "00":
                continue
            try:
                metric = int(columns[5], 16)
            except ValueError:
                continue
            interface = columns[-1]
            if _is_usable_interface(interface):
                defaults_v6.append((metric, interface))
        if defaults_v6:
            best_metric = min(metric for metric, _ in defaults_v6)
            selected.extend(item for item in defaults_v6 if item[0] == best_metric)
    except Exception:
        pass

    return list(dict.fromkeys(interface for _, interface in sorted(selected)))


def _interface_index(name: str) -> int:
    try:
        return socket.if_nametoindex(name)
    except OSError:
        return 0


class TrafficAccountant:
    """Accumulate selected host-interface counters without polling Docker state."""

    def __init__(self, state_dir: str | None = None, interface_spec: str | None = None) -> None:
        self.state_dir = Path(state_dir or os.environ.get("AGENT_STATE_DIR", "/opt/stacks/.fleetge"))
        self.db_path = self.state_dir / "traffic.sqlite"
        self.interface_spec = (interface_spec or os.environ.get("TRAFFIC_INTERFACES", "auto")).strip()
        self._lock = threading.RLock()
        self._initialized = False
        self._persistence_available = True
        self._boot_id = _boot_id()
        self._interfaces: list[str] = []
        self._interface_indexes: dict[str, int] = {}
        self._selection_mode = "auto" if not self.interface_spec or self.interface_spec.lower() == "auto" else "explicit"
        self._epoch = secrets.token_hex(8)
        self._ledger_id = secrets.token_hex(12)
        self._raw_rx = 0
        self._raw_tx = 0
        self._total_rx = 0
        self._total_tx = 0
        self._last_wall: float | None = None
        self._last_mono: float | None = None
        self._last_checkpoint = 0.0
        self._rx_rate: float | None = None
        self._tx_rate: float | None = None
        self._counter_reset = False
        self._has_gap = False
        self._open_buckets: dict[tuple[int, str], dict[str, Any]] = {}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _initialize(self) -> None:
        if self._initialized:
            return
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS traffic_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS traffic_bucket (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bucket_start INTEGER NOT NULL,
                        counter_epoch TEXT NOT NULL,
                        rx_bytes INTEGER NOT NULL DEFAULT 0,
                        tx_bytes INTEGER NOT NULL DEFAULT 0,
                        has_gap INTEGER NOT NULL DEFAULT 0,
                        counter_reset INTEGER NOT NULL DEFAULT 0,
                        interfaces TEXT NOT NULL DEFAULT '[]',
                        completed INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        UNIQUE(bucket_start, counter_epoch)
                    );
                    CREATE INDEX IF NOT EXISTS ix_traffic_bucket_completed
                    ON traffic_bucket(completed, id);
                    """
                )
                row = conn.execute("SELECT value FROM traffic_state WHERE key='current'").fetchone()
                if row:
                    state = json.loads(row["value"])
                    self._boot_id = str(state.get("boot_id") or self._boot_id)
                    self._interfaces = [str(item) for item in state.get("interfaces") or []]
                    self._interface_indexes = {
                        str(key): int(value) for key, value in (state.get("interface_indexes") or {}).items()
                    }
                    self._epoch = str(state.get("counter_epoch") or self._epoch)
                    self._ledger_id = str(state.get("ledger_id") or self._ledger_id)
                    self._raw_rx = int(state.get("raw_rx") or 0)
                    self._raw_tx = int(state.get("raw_tx") or 0)
                    self._total_rx = int(state.get("total_rx") or 0)
                    self._total_tx = int(state.get("total_tx") or 0)
                    self._last_wall = float(state["last_wall"]) if state.get("last_wall") else None
                for bucket in conn.execute("SELECT * FROM traffic_bucket WHERE completed=0"):
                    key = (int(bucket["bucket_start"]), str(bucket["counter_epoch"]))
                    self._open_buckets[key] = {
                        "rx": int(bucket["rx_bytes"]),
                        "tx": int(bucket["tx_bytes"]),
                        "has_gap": bool(bucket["has_gap"]),
                        "counter_reset": bool(bucket["counter_reset"]),
                        "interfaces": json.loads(bucket["interfaces"] or "[]"),
                    }
            self._last_checkpoint = time.monotonic()
        except Exception as exc:
            self._persistence_available = False
            logger.warning("Traffic persistence unavailable; using memory only: %s", exc)
        self._initialized = True

    def _select_interfaces(self, counters: dict[str, Any]) -> list[str]:
        if self._selection_mode == "explicit":
            requested = [item.strip() for item in self.interface_spec.split(",") if item.strip()]
            return [item for item in requested if item in counters]
        selected = [item for item in _default_route_interfaces() if item in counters]
        if selected:
            return selected
        candidates = [name for name in counters if _is_usable_interface(name)]
        if not candidates:
            return []
        # Last-resort fallback for non-Linux tests or unusual network stacks.
        return [max(candidates, key=lambda name: counters[name].bytes_recv + counters[name].bytes_sent)]

    @staticmethod
    def _aggregate(counters: dict[str, Any], interfaces: list[str]) -> tuple[int, int]:
        return (
            sum(int(counters[name].bytes_recv) for name in interfaces if name in counters),
            sum(int(counters[name].bytes_sent) for name in interfaces if name in counters),
        )

    def _new_epoch(self) -> None:
        self._epoch = secrets.token_hex(8)

    def _record_delta(self, start: float, end: float, rx_delta: int, tx_delta: int, *, gap: bool, reset: bool) -> None:
        if end <= start:
            start = end
        span = max(end - start, 0.001)
        cursor = start
        remaining_rx = max(0, int(rx_delta))
        remaining_tx = max(0, int(tx_delta))
        while cursor < end:
            bucket_start = int(cursor // BUCKET_SECONDS) * BUCKET_SECONDS
            segment_end = min(end, bucket_start + BUCKET_SECONDS)
            fraction = (segment_end - cursor) / span
            segment_rx = remaining_rx if segment_end >= end else int(round(rx_delta * fraction))
            segment_tx = remaining_tx if segment_end >= end else int(round(tx_delta * fraction))
            remaining_rx -= segment_rx
            remaining_tx -= segment_tx
            key = (bucket_start, self._epoch)
            bucket = self._open_buckets.setdefault(
                key,
                {"rx": 0, "tx": 0, "has_gap": False, "counter_reset": False, "interfaces": list(self._interfaces)},
            )
            bucket["rx"] += max(0, segment_rx)
            bucket["tx"] += max(0, segment_tx)
            bucket["has_gap"] = bool(bucket["has_gap"] or gap)
            bucket["counter_reset"] = bool(bucket["counter_reset"] or reset)
            cursor = segment_end

    def _persist(self, now_wall: float, *, close_completed: bool) -> None:
        if not self._persistence_available:
            return
        current_bucket = int(now_wall // BUCKET_SECONDS) * BUCKET_SECONDS
        state = {
            "boot_id": self._boot_id,
            "interfaces": self._interfaces,
            "interface_indexes": self._interface_indexes,
            "counter_epoch": self._epoch,
            "ledger_id": self._ledger_id,
            "raw_rx": self._raw_rx,
            "raw_tx": self._raw_tx,
            "total_rx": self._total_rx,
            "total_tx": self._total_tx,
            "last_wall": self._last_wall,
        }
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO traffic_state(key,value) VALUES('current',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (json.dumps(state, separators=(",", ":")),),
                )
                completed_keys: list[tuple[int, str]] = []
                for (bucket_start, epoch), bucket in self._open_buckets.items():
                    completed = bool(close_completed and bucket_start < current_bucket)
                    conn.execute(
                        """
                        INSERT INTO traffic_bucket(
                            bucket_start,counter_epoch,rx_bytes,tx_bytes,has_gap,counter_reset,
                            interfaces,completed,updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(bucket_start,counter_epoch) DO UPDATE SET
                            rx_bytes=excluded.rx_bytes, tx_bytes=excluded.tx_bytes,
                            has_gap=excluded.has_gap, counter_reset=excluded.counter_reset,
                            interfaces=excluded.interfaces, completed=excluded.completed,
                            updated_at=excluded.updated_at
                        """,
                        (
                            bucket_start, epoch, bucket["rx"], bucket["tx"], int(bucket["has_gap"]),
                            int(bucket["counter_reset"]), json.dumps(bucket["interfaces"]), int(completed), _utc_iso(),
                        ),
                    )
                    if completed:
                        completed_keys.append((bucket_start, epoch))
                for key in completed_keys:
                    self._open_buckets.pop(key, None)
                conn.execute(
                    "DELETE FROM traffic_bucket WHERE completed=1 AND bucket_start < ?",
                    (int(now_wall) - RETENTION_SECONDS,),
                )
            self._last_checkpoint = time.monotonic()
        except Exception as exc:
            logger.warning("Traffic checkpoint failed: %s", exc)

    def sample(self, *, active: bool) -> dict[str, Any]:
        with self._lock:
            self._initialize()
            now_wall = time.time()
            now_mono = time.monotonic()
            current_boot = _boot_id()
            counters = psutil.net_io_counters(pernic=True) or {}
            interfaces = self._select_interfaces(counters)
            indexes = {name: _interface_index(name) for name in interfaces}
            raw_rx, raw_tx = self._aggregate(counters, interfaces)

            previous_wall = self._last_wall
            same_generation = (
                current_boot == self._boot_id
                and interfaces == self._interfaces
                and indexes == self._interface_indexes
                and raw_rx >= self._raw_rx
                and raw_tx >= self._raw_tx
            )
            first_sample = previous_wall is None
            reset = bool(not first_sample and not same_generation)
            gap = bool(reset)
            if reset:
                self._new_epoch()
                rx_delta = tx_delta = 0
                self._interfaces = interfaces
                self._interface_indexes = indexes
                self._record_delta(now_wall - 0.001, now_wall, 0, 0, gap=True, reset=True)
            elif first_sample:
                rx_delta = tx_delta = 0
            else:
                rx_delta = raw_rx - self._raw_rx
                tx_delta = raw_tx - self._raw_tx
                self._total_rx += rx_delta
                self._total_tx += tx_delta
                self._record_delta(previous_wall, now_wall, rx_delta, tx_delta, gap=False, reset=False)

            dt = (now_mono - self._last_mono) if self._last_mono is not None else None
            if active and not reset and dt and 0 < dt <= 10.0:
                self._rx_rate = round(rx_delta / dt, 2)
                self._tx_rate = round(tx_delta / dt, 2)
            else:
                self._rx_rate = None
                self._tx_rate = None

            self._boot_id = current_boot
            self._interfaces = interfaces
            self._interface_indexes = indexes
            self._raw_rx = raw_rx
            self._raw_tx = raw_tx
            self._last_wall = now_wall
            self._last_mono = now_mono
            self._counter_reset = reset
            self._has_gap = bool(self._has_gap or gap)

            crossed_bucket = previous_wall is not None and int(previous_wall // BUCKET_SECONDS) < int(now_wall // BUCKET_SECONDS)
            if crossed_bucket or now_mono - self._last_checkpoint >= BUCKET_SECONDS:
                self._persist(now_wall, close_completed=True)
            return self.current()

    def current(self) -> dict[str, Any]:
        with self._lock:
            self._initialize()
            current_bucket = int((self._last_wall or time.time()) // BUCKET_SECONDS) * BUCKET_SECONDS
            open_rows = [
                bucket for (bucket_start, _), bucket in self._open_buckets.items()
                if bucket_start == current_bucket
            ]
            return {
                "timestamp": _utc_iso(self._last_wall) if self._last_wall else None,
                "sampleAgeSeconds": round(max(0.0, time.time() - self._last_wall), 3) if self._last_wall else None,
                "networkRxBytes": self._raw_rx,
                "networkTxBytes": self._raw_tx,
                "networkRxRate": self._rx_rate,
                "networkTxRate": self._tx_rate,
                "networkRxTotalBytes": self._total_rx,
                "networkTxTotalBytes": self._total_tx,
                "networkScope": "host_wan" if self._interfaces else "unknown",
                "networkSelectionMode": self._selection_mode,
                "networkInterfaces": list(self._interfaces),
                "networkCounterEpoch": self._epoch,
                "counterReset": self._counter_reset,
                "hasGap": self._has_gap,
                "persistenceAvailable": self._persistence_available,
                "ledgerId": self._ledger_id,
                "currentBucketStart": _utc_iso(current_bucket),
                "currentBucketRxBytes": sum(int(bucket["rx"]) for bucket in open_rows),
                "currentBucketTxBytes": sum(int(bucket["tx"]) for bucket in open_rows),
            }

    def history(self, cursor: int = 0, limit: int = 1000) -> dict[str, Any]:
        with self._lock:
            self._initialize()
            if not self._persistence_available:
                return {
                    "buckets": [], "nextCursor": cursor, "hasMore": False,
                    "persistenceAvailable": False, "ledgerId": self._ledger_id,
                }
            safe_limit = min(max(int(limit), 1), 2000)
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM traffic_bucket WHERE completed=1 AND id>? ORDER BY id LIMIT ?",
                    (max(int(cursor), 0), safe_limit + 1),
                ).fetchall()
            has_more = len(rows) > safe_limit
            rows = rows[:safe_limit]
            retention_gap = bool(cursor and rows and int(rows[0]["id"]) > int(cursor) + 1)
            buckets = [
                {
                    "id": int(row["id"]),
                    "bucketStart": _utc_iso(int(row["bucket_start"])),
                    "bucketSeconds": BUCKET_SECONDS,
                    "networkCounterEpoch": row["counter_epoch"],
                    "rxBytes": int(row["rx_bytes"]),
                    "txBytes": int(row["tx_bytes"]),
                    "hasGap": bool(row["has_gap"]),
                    "counterReset": bool(row["counter_reset"]),
                    "networkInterfaces": json.loads(row["interfaces"] or "[]"),
                }
                for row in rows
            ]
            next_cursor = int(rows[-1]["id"]) if rows else max(int(cursor), 0)
            return {
                "buckets": buckets,
                "nextCursor": next_cursor,
                "hasMore": has_more,
                "persistenceAvailable": True,
                "ledgerId": self._ledger_id,
                "retentionGap": retention_gap,
            }

    def close(self) -> None:
        with self._lock:
            if not self._initialized:
                return
            self._persist(time.time(), close_completed=True)


def is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        return bool(address.is_global)
    except ValueError:
        return False
