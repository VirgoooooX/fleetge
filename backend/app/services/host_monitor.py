"""Independent lightweight host liveness monitor, fault attribution, and durable Notify Hub alerts."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import ssl
import struct
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session, select

from app.database import engine
from app.models import HostConfig, HostMonitorState, HostStatusAlertOutbox, Setting
from app.schemas import HostMonitorSummary
from app.services.agent_client import AgentClient
from app.services.auto_update import notify_settings
from app.services.crypto import decrypt_string
from app.services.network_utils import is_private_ip
from app.services.notification_cover import prepare_notification
from app.services.notify_hub import NOTIFY_KEYS, matches_destination, submit_event
from app.services.settings_service import get_setting_value
from app.time_utils import as_utc, utc_now

logger = logging.getLogger(__name__)

MAX_NOTIFY_ATTEMPTS = 5
STARTUP_GRACE_SECONDS = 30.0
WAN_CANARY_TARGETS: tuple[tuple[str, int], ...] = (
    ("223.5.5.5", 443),
    ("119.29.29.29", 443),
    ("1.1.1.1", 443),
)
ALERT_EVENT_TYPE = "fleetge.host.status_alert"
RECOVERED_EVENT_TYPE = "fleetge.host.status_recovered"


def get_engine():
    import app.services.host_monitor as this_module
    return getattr(this_module, "engine", engine)


def _bool_setting(key: str, default: bool = True, session: Session | None = None) -> bool:
    if session is not None:
        row = session.get(Setting, key)
    else:
        with Session(get_engine()) as s:
            row = s.get(Setting, key)
    if row is None:
        return default
    return row.setting_value.strip().lower() not in {"0", "false", "off", "no"}


def host_monitor_alerts_enabled(session: Session | None = None) -> bool:
    return _bool_setting("HOST_MONITOR_ALERTS_ENABLED", True, session=session)


def host_monitor_notify_clean_reboot(session: Session | None = None) -> bool:
    return _bool_setting("HOST_MONITOR_NOTIFY_CLEAN_REBOOT", True, session=session)


def set_host_monitor_alert_settings(*, enabled: bool, notify_clean_reboot: bool) -> dict[str, bool]:
    with Session(get_engine()) as session:
        for key, value in (
            ("HOST_MONITOR_ALERTS_ENABLED", "true" if enabled else "false"),
            ("HOST_MONITOR_NOTIFY_CLEAN_REBOOT", "true" if notify_clean_reboot else "false"),
        ):
            row = session.get(Setting, key) or Setting(setting_key=key)
            row.setting_value = value
            session.add(row)
        session.commit()
    return {"enabled": enabled, "notify_clean_reboot": notify_clean_reboot}


def host_monitor_interval_seconds() -> int:
    raw = get_setting_value("HOST_MONITOR_INTERVAL", "300")
    try:
        val = int(raw)
    except (TypeError, ValueError):
        val = 300
    return max(60, min(val, 3600))


def _truncate_chars(text: str, max_chars: int = 40) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)] + "…"


def _truncate_utf8(text: str, max_bytes: int = 512) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    ellipsis = "…".encode("utf-8")
    budget = max(0, max_bytes - len(ellipsis))
    cut = encoded[:budget]
    while cut:
        try:
            return cut.decode("utf-8") + "…"
        except UnicodeDecodeError:
            cut = cut[:-1]
    return ""


def _format_duration(seconds: float | int | None) -> str:
    if seconds is None or seconds < 60:
        return "不足 1 分钟"
    total_minutes = int(seconds // 60)
    days, rem = divmod(total_minutes, 1440)
    hours, minutes = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    if minutes and not days:
        parts.append(f"{minutes} 分钟")
    return " ".join(parts) if parts else "不足 1 分钟"


def _parse_agent_endpoint(agent_url: str | None) -> tuple[str, int, Literal["http", "https"]] | None:
    if not agent_url:
        return None
    parsed = urlsplit(agent_url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return None
    port = parsed.port or (443 if scheme == "https" else 80)
    return parsed.hostname.strip().lower(), port, scheme  # type: ignore[return-value]


def _is_lan_host(agent_url: str | None) -> bool:
    endpoint = _parse_agent_endpoint(agent_url)
    if endpoint is None:
        return True
    hostname, _, _ = endpoint
    if is_private_ip(hostname):
        return True
    if hostname.endswith(".local") or hostname.endswith(".lan"):
        return True
    return False


def _icmp_checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return (~total) & 0xFFFF


def _best_effort_icmp_sync(ip_addr: str, timeout: float = 1.5, count: int = 3) -> tuple[bool | None, int, int]:
    """Try unprivileged SOCK_DGRAM ICMP echo with multi-packet sampling.

    Returns (reachable, received, sent):
      - reachable=None if ICMP sockets are not permitted by container/OS
      - reachable=True as soon as any echo reply is received
      - reachable=False if all packets time out
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
    except OSError:
        return None, 0, 0
    sent = 0
    received = 0
    try:
        sock.settimeout(timeout)
        ident = os.getpid() & 0xFFFF
        payload = b"fleetge-ping"
        for seq in range(1, max(1, count) + 1):
            header = struct.pack("!BBHHH", 8, 0, 0, ident, seq)
            checksum = _icmp_checksum(header + payload)
            packet = struct.pack("!BBHHH", 8, 0, checksum, ident, seq) + payload
            try:
                sock.sendto(packet, (ip_addr, 0))
                sent += 1
                sock.recvfrom(1024)
                received += 1
                return True, received, sent
            except socket.timeout:
                if seq < count:
                    time.sleep(0.25)
                continue
            except OSError:
                return (None, received, sent) if sent == 0 else (False, received, sent)
        return False, received, sent
    finally:
        sock.close()


async def _best_effort_icmp(ip_addr: str | None, timeout: float = 1.5, count: int = 3) -> tuple[bool | None, int, int]:
    if not ip_addr or ":" in ip_addr:
        return None, 0, 0
    return await asyncio.to_thread(_best_effort_icmp_sync, ip_addr, timeout, count)


def _classify_tls_exception(exc: BaseException) -> Literal["timeout", "reset", "other"]:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, (ConnectionResetError, BrokenPipeError, ssl.SSLEOFError)):
        return "reset"
    msg = str(exc).lower()
    if any(k in msg for k in ("timed out", "timeout")):
        return "timeout"
    if any(k in msg for k in ("reset", "eof", "broken pipe")):
        return "reset"
    return "other"


@dataclass
class DirectProbeResult:
    ok: bool
    agent_error: bool = False
    http_status: int | None = None
    failed_stage: str | None = None
    tcp_ok: bool = False
    icmp_reachable: bool | None = None
    icmp_received: int | None = None
    icmp_sent: int | None = None
    tls_error_kind: Literal["timeout", "reset", "other"] | None = None
    latency_ms: int | None = None
    boot_id: str | None = None
    uptime_seconds: int | None = None
    last_boot_shutdown_clean: bool | None = None
    error: str = ""


class HostMonitorManager:
    """Background liveness monitor with tiered debounce, hysteresis, flapping guard, WAN canary, peer verification, and Notify Hub outbox."""

    def __init__(self) -> None:
        self.started = False
        self.tasks: list[asyncio.Task] = []
        self._probe_wake = asyncio.Event()
        self._delivery_wake = asyncio.Event()
        self._cache: dict[str, HostMonitorSummary] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._flap_history: dict[str, list[datetime]] = {}
        # Legacy test-override knobs (when retry_delay_seconds is set explicitly, it overrides all tiered delays)
        self.retry_count: int = 2
        self.retry_delay_seconds: float | None = None
        # Tiered debounce & hysteresis defaults
        self.lan_retry_delays: tuple[float, ...] = (15.0, 30.0)
        self.wan_retry_delays: tuple[float, ...] = (30.0, 60.0)
        self.wan_blocked_extra_delay: float = 90.0
        self.wan_recovery_confirm_delay: float = 30.0
        self.flapping_window_seconds: float = 1800.0
        self.flapping_threshold: int = 2
        self.startup_grace_seconds: float = STARTUP_GRACE_SECONDS

    def _row_to_summary(self, row: HostMonitorState) -> HostMonitorSummary:
        try:
            diagnostics = json.loads(row.diagnostics_json) if row.diagnostics_json else None
        except ValueError:
            diagnostics = None
        state = row.state if row.state in {"unknown", "online", "blocked", "agent_error", "offline"} else "unknown"
        return HostMonitorSummary(
            state=state,  # type: ignore[arg-type]
            state_since=as_utc(row.state_since) if row.state_since else None,
            last_checked_at=as_utc(row.last_checked_at) if row.last_checked_at else None,
            last_ok_at=as_utc(row.last_ok_at) if row.last_ok_at else None,
            latency_ms=row.latency_ms,
            consecutive_failures=row.consecutive_failures,
            boot_id=row.boot_id,
            uptime_seconds=row.uptime_seconds,
            last_reboot_at=as_utc(row.last_reboot_at) if row.last_reboot_at else None,
            last_reboot_type=row.last_reboot_type,
            reason=row.last_reason or "",
            diagnostics=diagnostics if isinstance(diagnostics, dict) else None,
        )

    def load_cache_from_db(self) -> None:
        with Session(get_engine()) as session:
            rows = session.exec(select(HostMonitorState)).all()
        self._cache = {row.host_id: self._row_to_summary(row) for row in rows}

    def get_summary(self, host_id: str) -> HostMonitorSummary | None:
        return self._cache.get(host_id)

    def wake(self) -> None:
        self._probe_wake.set()

    async def start(self) -> None:
        if self.started:
            return
        self.load_cache_from_db()
        self.started = True
        self._probe_wake.clear()
        self._delivery_wake.clear()
        self.tasks = [
            asyncio.create_task(self._probe_loop(), name="host-monitor-probe"),
            asyncio.create_task(self._delivery_loop(), name="host-monitor-delivery"),
        ]
        logger.info("HostMonitorManager started (interval=%ds)", host_monitor_interval_seconds())

    async def stop(self) -> None:
        self.started = False
        self._probe_wake.set()
        self._delivery_wake.set()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        logger.info("HostMonitorManager stopped")

    async def _probe_loop(self) -> None:
        if self.startup_grace_seconds > 0:
            try:
                await asyncio.wait_for(self._probe_wake.wait(), timeout=self.startup_grace_seconds)
            except asyncio.TimeoutError:
                pass
            self._probe_wake.clear()

        while self.started:
            sweep_started = time.monotonic()
            try:
                await self.probe_all_hosts()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Host monitor sweep failed")

            interval = host_monitor_interval_seconds()
            elapsed = time.monotonic() - sweep_started
            wait_seconds = max(5.0, float(interval) - elapsed)
            self._probe_wake.clear()
            try:
                await asyncio.wait_for(self._probe_wake.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass

    async def _delivery_loop(self) -> None:
        while self.started:
            try:
                await self.dispatch_pending()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Host status alert delivery failed")

            self._delivery_wake.clear()
            try:
                await asyncio.wait_for(self._delivery_wake.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                pass

    # ── Low-level probes ────────────────────────────────────────────────

    def _effective_retry_delays(self, *, is_lan: bool, skip_retry_delay: bool) -> list[float]:
        if skip_retry_delay:
            return [0.0] * max(0, self.retry_count)
        if self.retry_delay_seconds is not None:
            delay = max(0.0, float(self.retry_delay_seconds))
            return [delay] * max(0, self.retry_count)
        base = self.lan_retry_delays if is_lan else self.wan_retry_delays
        return list(base)

    def _effective_extra_delay(self, default_delay: float, *, skip_retry_delay: bool) -> float:
        if skip_retry_delay:
            return 0.0
        if self.retry_delay_seconds is not None:
            return max(0.0, float(self.retry_delay_seconds))
        return max(0.0, float(default_delay))

    def _prune_and_count_flaps(self, host_id: str, now: datetime) -> int:
        cutoff = now - timedelta(seconds=self.flapping_window_seconds)
        events = [ts for ts in self._flap_history.get(host_id, []) if ts >= cutoff]
        if events:
            self._flap_history[host_id] = events
        else:
            self._flap_history.pop(host_id, None)
        return len(events)

    def _is_flapping(self, host_id: str, now: datetime) -> bool:
        return self._prune_and_count_flaps(host_id, now) >= self.flapping_threshold

    def _record_flap_recovery(self, host_id: str, now: datetime) -> None:
        self._prune_and_count_flaps(host_id, now)
        self._flap_history.setdefault(host_id, []).append(now)

    def _set_rechecking_cache(
        self,
        host_id: str,
        *,
        pending_failures: int,
        suspected_since: datetime,
        phase: str,
        failed_stage: str | None = None,
    ) -> None:
        cached = self._cache.get(host_id)
        if cached is None:
            return
        diag = dict(cached.diagnostics or {})
        diag.update(
            {
                "rechecking": True,
                "recheck_phase": phase,
                "pending_failures": pending_failures,
                "suspected_since": suspected_since.isoformat(),
                "last_failed_stage": failed_stage,
            }
        )
        self._cache[host_id] = cached.model_copy(update={"diagnostics": diag})

    async def _diagnose_transport_failure(
        self, agent_url: str, *, is_lan: bool = False
    ) -> tuple[str, bool, bool | None, Literal["timeout", "reset", "other"] | None, int | None, int | None]:
        """Return (failed_stage, tcp_ok, icmp_reachable, tls_error_kind, icmp_received, icmp_sent)."""
        endpoint = _parse_agent_endpoint(agent_url)
        if endpoint is None:
            return "dns", False, None, None, None, None
        host, port, scheme = endpoint

        loop = asyncio.get_running_loop()
        resolved_ip: str | None = None
        try:
            infos = await asyncio.wait_for(
                loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
                timeout=3.0 if is_lan else 5.0,
            )
            if infos and infos[0][4]:
                resolved_ip = str(infos[0][4][0])
        except Exception:
            return "dns", False, None, None, None, None

        icmp_task = asyncio.create_task(_best_effort_icmp(resolved_ip, timeout=1.5, count=3))
        writer: asyncio.StreamWriter | None = None
        tcp_ok = False
        failed_stage = "tcp"
        tls_error_kind: Literal["timeout", "reset", "other"] | None = None
        tcp_timeout = 3.0 if is_lan else 5.0
        tls_timeout = 3.0 if is_lan else 6.0
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(resolved_ip or host, port),
                timeout=tcp_timeout,
            )
            tcp_ok = True
            if scheme == "https":
                failed_stage = "tls"
                ctx = ssl.create_default_context()
                try:
                    await asyncio.wait_for(
                        writer.start_tls(ctx, server_hostname=host),
                        timeout=tls_timeout,
                    )
                except Exception as exc:
                    tls_error_kind = _classify_tls_exception(exc)
                    raise
            failed_stage = "http"
        except Exception:
            pass
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
                except Exception:
                    pass
        icmp_reachable, icmp_received, icmp_sent = await icmp_task
        return (
            failed_stage,
            tcp_ok,
            icmp_reachable,
            tls_error_kind,
            icmp_received if icmp_sent > 0 else None,
            icmp_sent if icmp_sent > 0 else None,
        )

    async def _probe_direct_once(self, host: HostConfig) -> DirectProbeResult:
        started = time.monotonic()
        is_lan = _is_lan_host(host.agent_url)
        client = AgentClient(host)
        try:
            data = await client.fetch_liveness(is_lan=is_lan)
            latency_ms = int((time.monotonic() - started) * 1000)
            boot_id = str(data["boot_id"]) if data.get("boot_id") else None
            uptime_raw = data.get("uptime_seconds")
            uptime_seconds = int(uptime_raw) if isinstance(uptime_raw, (int, float)) else None
            clean_raw = data.get("last_boot_shutdown_clean")
            clean_flag = clean_raw if isinstance(clean_raw, bool) else None
            return DirectProbeResult(
                ok=True,
                tcp_ok=True,
                http_status=200,
                latency_ms=latency_ms,
                boot_id=boot_id,
                uptime_seconds=uptime_seconds,
                last_boot_shutdown_clean=clean_flag,
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            latency_ms = int((time.monotonic() - started) * 1000)
            return DirectProbeResult(
                ok=False,
                agent_error=code in {401, 403, 404, 502, 503, 504},
                http_status=code,
                failed_stage="http",
                tcp_ok=True,
                latency_ms=latency_ms,
                error=f"HTTP {code}",
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            (
                failed_stage,
                tcp_ok,
                icmp_reachable,
                tls_error_kind,
                icmp_received,
                icmp_sent,
            ) = await self._diagnose_transport_failure(host.agent_url or "", is_lan=is_lan)
            return DirectProbeResult(
                ok=False,
                agent_error=False,
                failed_stage=failed_stage,
                tcp_ok=tcp_ok,
                icmp_reachable=icmp_reachable,
                icmp_received=icmp_received,
                icmp_sent=icmp_sent,
                tls_error_kind=tls_error_kind,
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}"[:200],
            )
        finally:
            await client.close()

    async def _check_local_wan_egress(self) -> bool:
        """Verify the controller itself has outbound internet access before alerting on public hosts."""
        async def probe_target(ip: str, port: int) -> bool:
            writer: asyncio.StreamWriter | None = None
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=2.5)
                return True
            except Exception:
                return False
            finally:
                if writer is not None:
                    try:
                        writer.close()
                        await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
                    except Exception:
                        pass

        results = await asyncio.gather(*(probe_target(ip, port) for ip, port in WAN_CANARY_TARGETS))
        return any(results)

    async def _call_peer_probe(
        self, peer: HostConfig, *, target_host: str, target_port: int, target_scheme: Literal["http", "https"]
    ) -> dict[str, Any]:
        client = AgentClient(peer)
        try:
            return await client.peer_probe(
                host=target_host,
                port=target_port,
                scheme=target_scheme,
                timeout_seconds=5.0,
            )
        finally:
            await client.close()

    async def _verify_via_peers(self, target: HostConfig, all_hosts: list[HostConfig]) -> dict[str, Any]:
        endpoint = _parse_agent_endpoint(target.agent_url)
        if endpoint is None:
            return {"checked": False, "reachable": None, "peers_tried": []}
        target_host, target_port, target_scheme = endpoint

        candidates: list[HostConfig] = []
        for candidate in all_hosts:
            if candidate.host_id == target.host_id or not candidate.enabled or not candidate.agent_url:
                continue
            if _is_lan_host(candidate.agent_url):
                continue
            cached = self._cache.get(candidate.host_id)
            if cached and cached.state not in {"online", "unknown"}:
                continue
            candidates.append(candidate)

        peers_tried: list[str] = []
        any_answered = False
        for peer in candidates[:2]:
            peers_tried.append(peer.host_id)
            try:
                result = await self._call_peer_probe(
                    peer,
                    target_host=target_host,
                    target_port=target_port,
                    target_scheme=target_scheme,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.debug("Peer %s does not support /api/agent/peer-probe yet", peer.host_id)
                continue
            except Exception as exc:
                logger.debug("Peer probe via %s failed: %s", peer.host_id, exc)
                continue

            any_answered = True
            if result.get("reachable") is True:
                return {
                    "checked": True,
                    "reachable": True,
                    "peer_host_id": peer.host_id,
                    "peer_name": peer.display_name or peer.host_id,
                    "peer_http_status": result.get("http_status"),
                    "peer_upstream_error": bool(result.get("upstream_error")),
                    "peers_tried": peers_tried,
                }

        return {
            "checked": any_answered,
            "reachable": False if any_answered else None,
            "peer_host_id": peers_tried[-1] if any_answered and peers_tried else None,
            "peer_name": None,
            "peer_http_status": None,
            "peers_tried": peers_tried,
        }

    # ── Orchestration & state machine ───────────────────────────────────

    async def probe_all_hosts(self) -> None:
        with Session(get_engine()) as session:
            hosts = list(session.exec(select(HostConfig).where(HostConfig.enabled.is_(True))).all())

        # Remove cached entries for deleted/disabled hosts
        enabled_ids = {h.host_id for h in hosts}
        for stale in list(self._cache):
            if stale not in enabled_ids:
                self._cache.pop(stale, None)

        public_ok_event = {"ok": False}
        sweep_context: dict[str, set[str]] = {"wan_ok": set(), "wan_failed": set()}

        async def run_one(host: HostConfig) -> None:
            if not host.agent_url:
                return
            summary = await self.probe_host(
                host.host_id,
                all_hosts=hosts,
                public_ok_hint=public_ok_event,
                sweep_context=sweep_context,
            )
            if summary and summary.state == "online" and not _is_lan_host(host.agent_url):
                public_ok_event["ok"] = True

        # Run all hosts concurrently so one host's long WAN debounce does not starve others
        await asyncio.gather(*(run_one(h) for h in hosts), return_exceptions=True)

    async def probe_host(
        self,
        host_id: str,
        *,
        all_hosts: list[HostConfig] | None = None,
        public_ok_hint: dict[str, bool] | None = None,
        sweep_context: dict[str, set[str]] | None = None,
        skip_retry_delay: bool = False,
    ) -> HostMonitorSummary | None:
        lock = self._host_locks.setdefault(host_id, asyncio.Lock())
        async with lock:
            with Session(get_engine()) as session:
                if all_hosts is None:
                    all_hosts = list(session.exec(select(HostConfig).where(HostConfig.enabled.is_(True))).all())
                host = next((h for h in all_hosts if h.host_id == host_id), None)
                if host is None:
                    host = session.exec(select(HostConfig).where(HostConfig.host_id == host_id)).first()
                existing_row = session.get(HostMonitorState, host_id)
                prev_state = existing_row.state if existing_row is not None else "unknown"
            if host is None or not host.agent_url:
                return None

            is_lan = _is_lan_host(host.agent_url)
            suspected_since = utc_now()
            result = await self._probe_direct_once(host)
            attempts_failed = 0 if result.ok else 1

            if not is_lan and sweep_context is not None:
                if result.ok:
                    sweep_context.setdefault("wan_ok", set()).add(host.host_id)
                else:
                    sweep_context.setdefault("wan_failed", set()).add(host.host_id)

            # Recovery hysteresis for WAN hosts: require 2 consecutive successes before declaring recovered
            if result.ok and not is_lan and prev_state in {"blocked", "offline", "agent_error"}:
                recovery_delay = self._effective_extra_delay(
                    self.wan_recovery_confirm_delay, skip_retry_delay=skip_retry_delay
                )
                self._set_rechecking_cache(
                    host.host_id,
                    pending_failures=0,
                    suspected_since=suspected_since,
                    phase="recovery_confirm",
                )
                if recovery_delay > 0:
                    await asyncio.sleep(recovery_delay)
                confirm_res = await self._probe_direct_once(host)
                if confirm_res.ok:
                    result = confirm_res
                else:
                    # Flapped back to failure during recovery confirmation -> hold existing incident state
                    logger.info(
                        "WAN recovery confirmation failed for %s; holding state=%s",
                        host.host_id,
                        prev_state,
                    )
                    self._set_rechecking_cache(
                        host.host_id,
                        pending_failures=1,
                        suspected_since=suspected_since,
                        phase="recovery_failed",
                        failed_stage=confirm_res.failed_stage,
                    )
                    return self._cache.get(host.host_id)

            # Tiered debounce retries on failure before transitioning state
            if not result.ok:
                retry_delays = self._effective_retry_delays(is_lan=is_lan, skip_retry_delay=skip_retry_delay)
                for delay in retry_delays:
                    self._set_rechecking_cache(
                        host.host_id,
                        pending_failures=attempts_failed,
                        suspected_since=suspected_since,
                        phase="failure_debounce",
                        failed_stage=result.failed_stage,
                    )
                    if delay > 0:
                        await asyncio.sleep(delay)
                    retry_res = await self._probe_direct_once(host)
                    result = retry_res
                    if retry_res.ok:
                        attempts_failed = 0
                        break
                    attempts_failed += 1

                # If recovered during debounce while previously in an incident state, still confirm WAN stability
                if result.ok and not is_lan and prev_state in {"blocked", "offline", "agent_error"}:
                    recovery_delay = self._effective_extra_delay(
                        self.wan_recovery_confirm_delay, skip_retry_delay=skip_retry_delay
                    )
                    if recovery_delay > 0:
                        await asyncio.sleep(recovery_delay)
                    confirm_res = await self._probe_direct_once(host)
                    if confirm_res.ok:
                        result = confirm_res
                    else:
                        return self._cache.get(host.host_id)

            now = utc_now()
            is_flapping = (not is_lan) and self._is_flapping(host.host_id, now)
            multi_wan_degraded = (
                not is_lan
                and sweep_context is not None
                and len(sweep_context.get("wan_failed", set())) >= 2
            )

            if not result.ok and not result.agent_error and not is_lan:
                # Local WAN egress sanity check before blaming any public host
                wan_ok = bool(public_ok_hint and public_ok_hint.get("ok"))
                if not wan_ok:
                    wan_ok = await self._check_local_wan_egress()
                if not wan_ok:
                    logger.warning(
                        "Local WAN egress unavailable; suppressing failure transition for public host %s",
                        host.host_id,
                    )
                    return self._cache.get(host.host_id)

            peer_info: dict[str, Any] = {"checked": False, "reachable": None, "peers_tried": []}
            if not result.ok and not result.agent_error and not is_lan:
                peer_info = await self._verify_via_peers(host, all_hosts)

                # Stronger confirmation window for 'blocked' (3+ minutes total; extended further on flapping or multi-WAN jitter)
                if peer_info.get("reachable") is True and prev_state != "blocked":
                    extra_rounds = 1
                    if is_flapping or multi_wan_degraded:
                        extra_rounds = 2
                    extra_delay = self._effective_extra_delay(
                        self.wan_blocked_extra_delay, skip_retry_delay=skip_retry_delay
                    )
                    for round_idx in range(extra_rounds):
                        self._set_rechecking_cache(
                            host.host_id,
                            pending_failures=attempts_failed,
                            suspected_since=suspected_since,
                            phase=f"blocked_confirm_{round_idx + 1}",
                            failed_stage=result.failed_stage,
                        )
                        if extra_delay > 0:
                            await asyncio.sleep(extra_delay)
                        confirm_direct = await self._probe_direct_once(host)
                        result = confirm_direct
                        if confirm_direct.ok:
                            attempts_failed = 0
                            peer_info = {"checked": False, "reachable": None, "peers_tried": []}
                            break
                        attempts_failed += 1
                        if confirm_direct.agent_error:
                            peer_info = {"checked": False, "reachable": None, "peers_tried": []}
                            break
                        wan_still_ok = bool(public_ok_hint and public_ok_hint.get("ok")) or await self._check_local_wan_egress()
                        if not wan_still_ok:
                            logger.warning(
                                "Local WAN egress unavailable during blocked confirmation for %s; suppressing transition",
                                host.host_id,
                            )
                            return self._cache.get(host.host_id)
                        peer_info = await self._verify_via_peers(host, all_hosts)
                        if peer_info.get("reachable") is not True:
                            break
                    now = utc_now()

            return self._apply_probe_outcome(
                host,
                result,
                attempts_failed,
                peer_info,
                now,
                is_flapping=is_flapping,
                multi_wan_degraded=multi_wan_degraded,
            )

    def _build_failure_reason(
        self,
        new_state: str,
        result: DirectProbeResult,
        peer_info: dict[str, Any],
        *,
        is_lan: bool,
        is_flapping: bool = False,
    ) -> str:
        if new_state == "agent_error":
            code = result.http_status
            if code in {502, 503, 504}:
                return f"主机公网反代返回 HTTP {code}，宿主机在线但 Agent 服务不可用，请检查 Agent 容器状态。"
            return f"Agent 返回 HTTP {code}，宿主机在线但令牌或秘密路径配置异常，请检查配置。"

        if new_state == "blocked":
            peer_label = peer_info.get("peer_name") or peer_info.get("peer_host_id") or "海外节点"
            if result.tcp_ok and result.failed_stage == "tls":
                if result.tls_error_kind == "reset":
                    stage_desc = "国内直连 TLS 连接被重置（TCP 假通）"
                elif result.tls_error_kind == "timeout":
                    stage_desc = "国内直连 TLS 握手超时（TCP 假通）"
                else:
                    stage_desc = "国内直连 TLS 超时/重置（TCP 假通）"
            elif result.tcp_ok and result.failed_stage == "http":
                stage_desc = "国内直连 HTTP 超时/重置（TCP 假通）"
            elif result.failed_stage == "dns":
                stage_desc = "国内 DNS 解析异常"
            else:
                stage_desc = "国内直连 TCP 不可达"
            icmp_note = ""
            if result.icmp_reachable is True:
                icmp_note = "，ICMP 可达"
            elif result.icmp_reachable is False:
                icmp_note = "，ICMP 不可达"
            flap_note = "（近期线路频繁波动）" if is_flapping else ""
            return f"{stage_desc}{icmp_note}，海外节点 {peer_label} 复核正常{flap_note}。请检查线路或端口策略。"

        # offline
        if is_lan:
            return f"局域网直连探活连续失败（{result.failed_stage or 'network'}），疑似关机、死机或内网断连。"
        if peer_info.get("checked"):
            peers = "、".join(peer_info.get("peers_tried") or [])
            return f"国内直连与海外节点（{peers}）均不可达，疑似死机、关机或机房故障，请登录服务商面板排查。"
        return "国内直连不可达（暂无可用海外节点复核），疑似死机、关机或网络中断，请及时排查。"

    def _cancel_pending_incident_alerts_in_session(
        self,
        session: Session,
        *,
        host_id: str,
        incident_id: str | None,
    ) -> tuple[int, bool]:
        """Cancel unsent pending failure alerts for a recovered incident.

        Returns (cancelled_count, had_sent_alert).
        """
        if not incident_id:
            return 0, True
        prefix = f"fleetge:host-status:{host_id}:inc-{incident_id}:"
        rows = list(
            session.exec(
                select(HostStatusAlertOutbox).where(
                    HostStatusAlertOutbox.host_id == host_id,
                    HostStatusAlertOutbox.event_type == ALERT_EVENT_TYPE,
                )
            ).all()
        )
        matched = [r for r in rows if r.alert_key.startswith(prefix)]
        cancelled = 0
        had_sent = False
        for item in matched:
            if item.status == "sent":
                had_sent = True
            elif item.status == "pending" and item.attempts > 0:
                item.status = "cancelled"
                item.last_error = "Cancelled: host recovered before alert delivery."
                session.add(item)
                cancelled += 1
        return cancelled, had_sent

    def _apply_probe_outcome(
        self,
        host: HostConfig,
        result: DirectProbeResult,
        attempts_failed: int,
        peer_info: dict[str, Any],
        now: datetime,
        *,
        is_flapping: bool = False,
        multi_wan_degraded: bool = False,
    ) -> HostMonitorSummary:
        is_lan = _is_lan_host(host.agent_url)
        display_name = host.display_name or host.host_id

        with Session(get_engine()) as session:
            row = session.get(HostMonitorState, host.host_id)
            if row is None:
                row = HostMonitorState(host_id=host.host_id, state="unknown")

            prev_state = row.state
            prev_boot_id = row.boot_id
            prev_state_since = as_utc(row.state_since) if row.state_since else None
            prev_incident_id = row.active_incident_id

            row.last_checked_at = now
            row.latency_ms = result.latency_ms

            if result.ok:
                row.last_ok_at = now
                row.consecutive_failures = 0
                if result.uptime_seconds is not None:
                    row.uptime_seconds = result.uptime_seconds

                boot_changed = bool(prev_boot_id and result.boot_id and result.boot_id != prev_boot_id)
                if result.boot_id:
                    row.boot_id = result.boot_id

                reboot_type: str | None = None
                if boot_changed:
                    row.last_reboot_at = now
                    if result.last_boot_shutdown_clean is True:
                        reboot_type = "clean"
                    elif result.last_boot_shutdown_clean is False:
                        reboot_type = "unclean"
                    else:
                        reboot_type = "unknown"
                    row.last_reboot_type = reboot_type

                diagnostics = {
                    "ok": True,
                    "http_status": result.http_status,
                    "latency_ms": result.latency_ms,
                    "boot_changed": boot_changed,
                    "reboot_type": reboot_type,
                }
                row.diagnostics_json = json.dumps(diagnostics, ensure_ascii=False)
                row.last_reason = ""
                row.state = "online"

                if prev_state == "unknown":
                    row.state_since = now
                    row.active_incident_id = None
                elif prev_state in {"offline", "blocked", "agent_error"}:
                    duration_text = _format_duration((now - prev_state_since).total_seconds() if prev_state_since else None)
                    incident_id = prev_incident_id or f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
                    row.state_since = now
                    row.active_incident_id = None
                    self._record_flap_recovery(host.host_id, now)

                    cancelled_count, had_sent_alert = self._cancel_pending_incident_alerts_in_session(
                        session,
                        host_id=host.host_id,
                        incident_id=prev_incident_id,
                    )

                    if boot_changed and reboot_type == "unclean":
                        self._enqueue_alert_in_session(
                            session,
                            host=host,
                            event_type=ALERT_EVENT_TYPE,
                            alert_key=f"fleetge:host-status:{host.host_id}:inc-{incident_id}:recovered-unclean",
                            title=f"【Fleetge】异常重启恢复｜{display_name}",
                            content=f"主机已上线（离线持续 {duration_text}），但上次为非正常关机，请检查系统日志与容器状态。",
                            level="warning",
                            now=now,
                        )
                    elif cancelled_count > 0 and not had_sent_alert:
                        logger.info(
                            "Cancelled %d unsent alert(s) for %s incident %s; suppressing redundant recovery alert",
                            cancelled_count,
                            host.host_id,
                            incident_id,
                        )
                    elif boot_changed and reboot_type == "clean":
                        self._enqueue_alert_in_session(
                            session,
                            host=host,
                            event_type=RECOVERED_EVENT_TYPE,
                            alert_key=f"fleetge:host-status:{host.host_id}:inc-{incident_id}:recovered",
                            title=f"【Fleetge】恢复在线｜{display_name}",
                            content=f"主机已恢复在线（离线持续 {duration_text}，检测到正常关机/重启后上线）。",
                            level="info",
                            now=now,
                        )
                    else:
                        self._enqueue_alert_in_session(
                            session,
                            host=host,
                            event_type=RECOVERED_EVENT_TYPE,
                            alert_key=f"fleetge:host-status:{host.host_id}:inc-{incident_id}:recovered",
                            title=f"【Fleetge】恢复在线｜{display_name}",
                            content=f"直连探活已恢复正常（本次异常持续 {duration_text}，主机未重启）。",
                            level="info",
                            now=now,
                        )
                elif prev_state == "online" and boot_changed:
                    uptime_text = _format_duration(result.uptime_seconds)
                    boot_key = (result.boot_id or uuid.uuid4().hex)[:12]
                    if reboot_type == "unclean":
                        self._enqueue_alert_in_session(
                            session,
                            host=host,
                            event_type=ALERT_EVENT_TYPE,
                            alert_key=f"fleetge:host-status:{host.host_id}:reboot:{boot_key}",
                            title=f"【Fleetge】异常重启｜{display_name}",
                            content=f"检测到主机在未优雅关闭的情况下重启并上线（当前已运行 {uptime_text}），请排查 OOM、内核日志与容器状态。",
                            level="warning",
                            now=now,
                        )
                    elif reboot_type == "clean" and host_monitor_notify_clean_reboot(session=session):
                        self._enqueue_alert_in_session(
                            session,
                            host=host,
                            event_type=RECOVERED_EVENT_TYPE,
                            alert_key=f"fleetge:host-status:{host.host_id}:reboot:{boot_key}",
                            title=f"【Fleetge】正常重启｜{display_name}",
                            content=f"检测到主机已完成正常重启并重新上线，当前已运行 {uptime_text}。",
                            level="info",
                            now=now,
                        )
            else:
                if result.agent_error:
                    new_state = "agent_error"
                elif not is_lan and peer_info.get("reachable") is True:
                    new_state = "blocked"
                else:
                    new_state = "offline"

                reason = self._build_failure_reason(
                    new_state,
                    result,
                    peer_info,
                    is_lan=is_lan,
                    is_flapping=is_flapping,
                )
                diagnostics = {
                    "ok": False,
                    "failed_stage": result.failed_stage,
                    "tls_error_kind": result.tls_error_kind,
                    "tcp_ok": result.tcp_ok,
                    "http_status": result.http_status,
                    "icmp_reachable": result.icmp_reachable,
                    "icmp_received": result.icmp_received,
                    "icmp_sent": result.icmp_sent,
                    "error": result.error,
                    "peer_checked": peer_info.get("checked"),
                    "peer_reachable": peer_info.get("reachable"),
                    "peer_host_id": peer_info.get("peer_host_id"),
                    "peer_http_status": peer_info.get("peer_http_status"),
                    "peers_tried": peer_info.get("peers_tried", []),
                    "flapping": is_flapping,
                    "multi_wan_degraded": multi_wan_degraded,
                }
                row.consecutive_failures += max(1, attempts_failed)
                row.last_reason = reason
                row.diagnostics_json = json.dumps(diagnostics, ensure_ascii=False)

                state_changed = prev_state != new_state
                if state_changed:
                    if prev_state in {"unknown", "online"} or not prev_incident_id:
                        row.state_since = now
                        row.active_incident_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
                    row.state = new_state

                    title_map = {
                        "blocked": f"【Fleetge】疑似被墙｜{display_name}",
                        "offline": f"【Fleetge】主机失联｜{display_name}",
                        "agent_error": f"【Fleetge】Agent异常｜{display_name}",
                    }
                    self._enqueue_alert_in_session(
                        session,
                        host=host,
                        event_type=ALERT_EVENT_TYPE,
                        alert_key=f"fleetge:host-status:{host.host_id}:inc-{row.active_incident_id}:{new_state}",
                        title=title_map[new_state],
                        content=reason,
                        level="warning",
                        now=now,
                    )

            row.updated_at = now
            session.add(row)
            session.commit()
            session.refresh(row)
            summary = self._row_to_summary(row)
            self._cache[host.host_id] = summary
            return summary

    def _enqueue_alert_in_session(
        self,
        session: Session,
        *,
        host: HostConfig,
        event_type: str,
        alert_key: str,
        title: str,
        content: str,
        level: str,
        now: datetime,
    ) -> None:
        if not host_monitor_alerts_enabled(session=session):
            return
        existing = session.exec(
            select(HostStatusAlertOutbox).where(HostStatusAlertOutbox.alert_key == alert_key)
        ).first()
        if existing is not None:
            return
        config = notify_settings(session)
        if not all(config.get(key) for key in NOTIFY_KEYS):
            return
        payload = {
            "event_type": event_type,
            "event_key": alert_key,
            "title": _truncate_chars(title, 40),
            "content": _truncate_utf8(content, 512),
            "level": level,
            "recipients": [config["NOTIFYHUB_RECIPIENT"]],
            "message_type": "text",
            "_host_icon": host.logo,
        }
        session.add(
            HostStatusAlertOutbox(
                alert_key=alert_key,
                host_id=host.host_id,
                event_type=event_type,
                status="pending",
                notify_url=config["NOTIFYHUB_URL"],
                notify_recipient=config["NOTIFYHUB_RECIPIENT"],
                payload=json.dumps(payload, ensure_ascii=False),
                attempts=0,
                next_attempt_at=now,
                expires_at=now + timedelta(hours=24),
                last_error="",
            )
        )
        self._delivery_wake.set()

    # ── Durable Notify Hub delivery ─────────────────────────────────────

    async def dispatch_pending(self) -> None:
        if not host_monitor_alerts_enabled():
            return
        config = notify_settings()
        now = utc_now()
        with Session(get_engine()) as session:
            alerts = list(
                session.exec(
                    select(HostStatusAlertOutbox)
                    .where(
                        HostStatusAlertOutbox.status == "pending",
                        HostStatusAlertOutbox.next_attempt_at <= now,
                    )
                    .order_by(HostStatusAlertOutbox.id)
                ).all()
            )
        if not alerts:
            return

        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), follow_redirects=False) as client:
            for alert in alerts:
                expires_at = as_utc(alert.expires_at)
                if expires_at <= now:
                    self._finish_delivery(alert.id, "expired", "Notification expired before acceptance.")
                    continue
                if not matches_destination(config, alert.notify_url, alert.notify_recipient):
                    self._finish_delivery(alert.id, "blocked", "Notify Hub configuration changed before delivery.")
                    continue
                try:
                    payload = json.loads(alert.payload)
                    with Session(get_engine()) as session:
                        host = session.exec(select(HostConfig).where(HostConfig.host_id == alert.host_id)).first()
                    if "_host_icon" in payload and host is not None:
                        payload["_host_icon"] = host.logo
                    api_key = decrypt_string(config["NOTIFYHUB_KEY"])
                    payload = await prepare_notification(client, alert.notify_url, api_key, payload)
                    with Session(get_engine()) as session:
                        row = session.get(HostStatusAlertOutbox, alert.id)
                        if row is None or row.status != "pending":
                            continue
                        row.payload = json.dumps(payload, ensure_ascii=False)
                        session.add(row)
                        session.commit()
                    status, error = await submit_event(client, alert.notify_url, api_key, payload)
                    if status == "accepted":
                        self._finish_delivery(alert.id, "sent", "", sent=True)
                    elif status == "pending":
                        self._retry_delivery(alert.id, error)
                    else:
                        self._finish_delivery(alert.id, "blocked", error)
                except (httpx.HTTPError, ValueError) as exc:
                    self._retry_delivery(alert.id, f"Notify Hub request was not confirmed ({type(exc).__name__}).")
                except Exception as exc:
                    self._finish_delivery(alert.id, "blocked", f"Notify Hub configuration error ({type(exc).__name__}).")

    def _retry_delivery(self, alert_id: int, error: str) -> None:
        now = utc_now()
        with Session(get_engine()) as session:
            alert = session.get(HostStatusAlertOutbox, alert_id)
            if alert is None or alert.status != "pending":
                return
            alert.attempts += 1
            alert.last_error = error
            if alert.attempts >= MAX_NOTIFY_ATTEMPTS:
                alert.status = "failed"
            else:
                delay = min(15 * 60, 60 * (2 ** (alert.attempts - 1)))
                alert.next_attempt_at = now + timedelta(seconds=delay)
            session.add(alert)
            session.commit()

    def _finish_delivery(self, alert_id: int, status: str, error: str, *, sent: bool = False) -> None:
        with Session(get_engine()) as session:
            alert = session.get(HostStatusAlertOutbox, alert_id)
            if alert is None or alert.status != "pending":
                return
            alert.status = status
            alert.last_error = error
            if status not in {"cancelled", "expired"}:
                alert.attempts += 1
            if sent:
                alert.sent_at = utc_now()
            session.add(alert)
            session.commit()


host_monitor_manager = HostMonitorManager()
