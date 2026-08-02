"""Enrollment primitives shared by the admin and public invite APIs.

The install URL is a short-lived Fernet envelope. The database only stores
SHA-256 digests of install and claim tokens; the envelope carries the claim
token long enough for the downloaded script to submit it.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.models import EnrollmentInvite, HostConfig
from app.services.agent_client import AgentClient
from app.services.crypto import decrypt_string, encrypt_string
from app.services.host_writer import write_hosts_to_yaml
from app.services.snapshot import snapshot_manager


INVITE_TTL = timedelta(minutes=10)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Restore UTC tzinfo lost by SQLite and normalize aware timestamps."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "host").strip().lower())
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "host"


def normalize_url(value: str) -> str | None:
    raw = (value or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if not raw or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return raw


def normalize_public_host(value: str) -> str | None:
    host = (value or "").strip().lower().rstrip(".")
    if not host or len(host) > 253 or "*" in host or "/" in host or ":" in host:
        return None
    labels = host.split(".")
    if len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        return None
    return host


def is_private_host(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return False


def normalize_geolocation(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    try:
        latitude = float(raw.get("latitude"))
        longitude = float(raw.get("longitude"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return {
        "city": str(raw.get("city") or "").strip()[:120] or None,
        "region": str(raw.get("region") or "").strip()[:120] or None,
        "country": str(raw.get("country") or "").strip()[:120] or None,
        "country_code": str(raw.get("country_code") or "").strip().upper()[:8] or None,
        "latitude": latitude,
        "longitude": longitude,
        "source": "ipwho.is",
        "confirmed": False,
    }


def resolve_request_source_ip(request) -> str | None:
    """Honor forwarded client IPs only from explicitly trusted proxy peers."""
    peer = request.client.host if request.client else None
    if not peer:
        return None
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    trusted = []
    for raw in get_settings().TRUSTED_PROXY_CIDRS.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            trusted.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            continue
    if not any(peer_ip in network for network in trusted):
        return peer_ip.compressed
    candidates = []
    forwarded = request.headers.get("forwarded", "")
    for group in forwarded.split(","):
        for token in group.split(";"):
            if token.strip().lower().startswith("for="):
                candidates.append(token.split("=", 1)[1].strip().strip('"'))
    candidates.extend(part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip())

    parsed_chain = []
    for candidate in candidates:
        try:
            candidate = candidate.strip().strip('"')
            if candidate.startswith("[") and "]" in candidate:
                candidate = candidate[1:candidate.index("]")]
            elif candidate.count(":") == 1 and candidate.rsplit(":", 1)[1].isdigit():
                candidate = candidate.rsplit(":", 1)[0]
            parsed_chain.append(ipaddress.ip_address(candidate))
        except ValueError:
            continue

    # Walk from the nearest hop towards the original client. A spoofed
    # left-most value cannot win unless every proxy to its right is trusted.
    for address in reversed([*parsed_chain, peer_ip]):
        if any(address in network for network in trusted):
            continue
        return address.compressed

    # CF-Connecting-IP is accepted only when the immediate trusted peer is a
    # public CDN address, never merely because a local reverse proxy is trusted.
    if peer_ip.is_global and request.headers.get("cf-connecting-ip"):
        try:
            return ipaddress.ip_address(request.headers["cf-connecting-ip"].strip()).compressed
        except ValueError:
            pass
    return peer_ip.compressed


def _envelope(invite_id: str, claim_token: str) -> str:
    payload = json.dumps(
        {"invite_id": invite_id, "claim_token": claim_token, "issued_at": utc_now().isoformat()},
        separators=(",", ":"),
    )
    return encrypt_string(payload)


def decode_install_token(token: str) -> tuple[str, str] | None:
    try:
        data = json.loads(decrypt_string(token))
        invite_id = str(data.get("invite_id") or "")
        claim_token = str(data.get("claim_token") or "")
        if invite_id and claim_token:
            return invite_id, claim_token
    except Exception:
        pass
    return None


def build_install_command(dashboard_url: str, install_token: str) -> str:
    return (
        f"curl -fsSL '{dashboard_url.rstrip('/')}/api/enroll/install/{install_token}' | "
        "{ [ \"$(id -u)\" -eq 0 ] && sh || sudo sh; }"
    )


def _compose_text() -> str:
    return """services:
  fleetge-agent:
    image: $ENROLLMENT_AGENT_IMAGE
    restart: unless-stopped
    network_mode: host
    env_file:
      - .env
    environment:
      AGENT_TOKEN: $AGENT_TOKEN
      AGENT_SECRET_PATH: $AGENT_SECRET_PATH
      AGENT_INSTANCE_ID: $AGENT_INSTANCE_ID
      STACKS_BASE_DIR: /opt/stacks
      AGENT_VERSION: $AGENT_VERSION
      PORT: $AGENT_PORT
      AGENT_BIND_HOST: 127.0.0.1
      METRICS_ACTIVE_INTERVAL: 2
      METRICS_IDLE_TIMEOUT: 15
      TRAFFIC_IDLE_INTERVAL: 60
      TRAFFIC_INTERFACES: auto
      AGENT_STATE_DIR: /opt/stacks/.fleetge
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - $STACK_ROOT:/opt/stacks
  fleetge-caddy:
    image: $ENROLLMENT_PROXY_IMAGE
    restart: unless-stopped
    depends_on:
      - fleetge-agent
    network_mode: host
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config

volumes:
  caddy_data:
  caddy_config:
"""


def _caddyfile_text(invite: EnrollmentInvite) -> str:
    return f"""{invite.agent_public_host} {{
    encode gzip
    reverse_proxy 127.0.0.1:{invite.agent_port}
}}
"""


def _env_text(invite: EnrollmentInvite, agent_token: str) -> str:
    return "\n".join(
        [
            f"AGENT_TOKEN={agent_token}",
            f"AGENT_SECRET_PATH={invite.secret_path or ''}",
            f"AGENT_INSTANCE_ID={invite.agent_instance_id}",
            f"AGENT_PORT={invite.agent_port}",
            f"STACK_ROOT={invite.stack_root}",
            f"ENROLLMENT_AGENT_IMAGE={invite.agent_image}",
            f"ENROLLMENT_PROXY_IMAGE={get_settings().ENROLLMENT_PROXY_IMAGE}",
            f"AGENT_PUBLIC_HOST={invite.agent_public_host}",
            "AGENT_VERSION=1.0.0",
            "AGENT_ENABLE_WRITE=true",
            "AGENT_ENABLE_DELETE=true",
            "AGENT_ENABLE_GLOBAL_ENV=true",
            "AGENT_ENABLE_PRUNE=false",
        ]
    ) + "\n"


def render_install_script(invite: EnrollmentInvite, claim_token: str, agent_token: str, dashboard_url: str) -> str:
    compose_b64 = base64.b64encode(_compose_text().encode()).decode()
    caddy_b64 = base64.b64encode(_caddyfile_text(invite).encode()).decode()
    env_b64 = base64.b64encode(_env_text(invite, agent_token).encode()).decode()
    claim_url = dashboard_url.rstrip("/") + "/api/enroll/claim"
    status_url = dashboard_url.rstrip("/") + "/api/enroll/status"
    return f'''#!/bin/sh
set -eu

INSTALL_DIR=/opt/fleetge-agent
STACK_ROOT="{invite.stack_root}"
AGENT_PORT="{invite.agent_port}"
CLAIM_URL="{claim_url}"
STATUS_URL="{status_url}"
CLAIM_TOKEN="{claim_token}"
AGENT_HEALTH_URL="http://127.0.0.1:$AGENT_PORT/{(invite.secret_path or '').strip('/')}/api/agent/health"

log() {{ printf '%s\\n' "[fleetge-enroll] $*" >&2; }}
fail() {{ log "安装失败：$*"; exit 1; }}

[ "$(uname -s 2>/dev/null || true)" = "Linux" ] || fail "仅支持 Linux"
command -v docker >/dev/null 2>&1 || fail "未找到 Docker"
docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose v2"
[ -d "$STACK_ROOT" ] || mkdir -p "$STACK_ROOT" || fail "无法创建 Stack 目录"
MANAGED_EXISTING=false
if [ -f "$INSTALL_DIR/compose.yaml" ] && grep -q 'fleetge-agent:' "$INSTALL_DIR/compose.yaml"; then
  MANAGED_EXISTING=true
fi
if [ "$MANAGED_EXISTING" = false ] && command -v ss >/dev/null 2>&1; then
  for port in {invite.agent_port} 80 443; do
    if ss -ltn | awk '{{print $4}}' | grep -Eq "(^|:)$port$"; then fail "端口 $port 已被占用"; fi
  done
fi

umask 077
mkdir -p "$INSTALL_DIR"
[ ! -f "$INSTALL_DIR/compose.yaml" ] || grep -q 'fleetge-agent:' "$INSTALL_DIR/compose.yaml" || fail "安装目录中已有其他 Compose 项目"
EXISTING_INSTANCE_ID=""
if [ -f "$INSTALL_DIR/.env" ]; then
  EXISTING_INSTANCE_ID=$(sed -n 's/^AGENT_INSTANCE_ID=//p' "$INSTALL_DIR/.env" | head -n 1)
  if [ -n "$EXISTING_INSTANCE_ID" ] && ! printf '%s' "$EXISTING_INSTANCE_ID" | grep -Eq '^[A-Za-z0-9._-]+$'; then
    EXISTING_INSTANCE_ID=""
  fi
fi
tmp_env="$INSTALL_DIR/.env.$$"
tmp_compose="$INSTALL_DIR/compose.yaml.$$"
tmp_caddy="$INSTALL_DIR/Caddyfile.$$"
cleanup() {{ rm -f "$tmp_env" "$tmp_compose" "$tmp_caddy"; }}
trap cleanup EXIT INT TERM
printf '%s' '{env_b64}' | base64 -d > "$tmp_env" || fail "写入配置失败"
printf '%s' '{compose_b64}' | base64 -d > "$tmp_compose" || fail "写入 Compose 失败"
printf '%s' '{caddy_b64}' | base64 -d > "$tmp_caddy" || fail "写入 Caddy 配置失败"
if [ -n "$EXISTING_INSTANCE_ID" ]; then
  sed "s/^AGENT_INSTANCE_ID=.*/AGENT_INSTANCE_ID=$EXISTING_INSTANCE_ID/" "$tmp_env" > "$tmp_env.id"
  mv -f "$tmp_env.id" "$tmp_env"
fi
chmod 600 "$tmp_env" "$tmp_compose" "$tmp_caddy"
mv -f "$tmp_env" "$INSTALL_DIR/.env"
mv -f "$tmp_compose" "$INSTALL_DIR/compose.yaml"
mv -f "$tmp_caddy" "$INSTALL_DIR/Caddyfile"
trap - EXIT INT TERM

docker compose --env-file "$INSTALL_DIR/.env" -f "$INSTALL_DIR/compose.yaml" up -d || fail "Agent 启动失败"
AGENT_TOKEN_VALUE=$(sed -n 's/^AGENT_TOKEN=//p' "$INSTALL_DIR/.env")
i=0
while [ "$i" -lt 30 ]; do
  if env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
    curl --noproxy '*' -fsSL --max-time 2 -H "Authorization: Bearer $AGENT_TOKEN_VALUE" "$AGENT_HEALTH_URL" >/dev/null 2>&1; then break; fi
  i=$((i + 1)); sleep 1
done
[ "$i" -lt 30 ] || fail "Agent 健康检查超时"

HOSTNAME_VALUE=$(hostname 2>/dev/null || uname -n)
INSTANCE_ID=$(sed -n 's/^AGENT_INSTANCE_ID=//p' "$INSTALL_DIR/.env")
AGENT_PUBLIC_HOST=$(sed -n 's/^AGENT_PUBLIC_HOST=//p' "$INSTALL_DIR/.env")
if CLAIM_RESULT=$(env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  curl --noproxy '*' -fsSL --max-time 20 -X POST "$CLAIM_URL" \
  -F "claim_token=$CLAIM_TOKEN" \
  -F "hostname=$HOSTNAME_VALUE" \
  -F "instance_id=$INSTANCE_ID" \
  -F "agent_public_host=$AGENT_PUBLIC_HOST" \
  -F "callback_mode=direct"); then
  :
else
  CLAIM_RESULT=$(curl -fsSL --max-time 20 -X POST "$CLAIM_URL" \
    -F "claim_token=$CLAIM_TOKEN" \
    -F "hostname=$HOSTNAME_VALUE" \
    -F "instance_id=$INSTANCE_ID" \
    -F "agent_public_host=$AGENT_PUBLIC_HOST" \
    -F "callback_mode=proxy_fallback") || fail "Dashboard 回连失败；请检查 Dashboard URL 和网络"
fi
STATE=$(printf '%s' "$CLAIM_RESULT" | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\\([^"]*\\)".*/\\1/p')
[ -n "$STATE" ] || fail "Dashboard 未返回入网状态"
if [ "$STATE" = "active" ]; then log "Agent 已启动并完成入网"; exit 0; fi

i=0
while [ "$i" -lt 90 ]; do
  STATUS_BODY=$(curl -fsSL --max-time 10 -X POST "$STATUS_URL" -F "claim_token=$CLAIM_TOKEN" 2>/dev/null || true)
  STATE=$(printf '%s' "$STATUS_BODY" | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\\([^"]*\\)".*/\\1/p')
  case "$STATE" in
    active) log "Agent 已启动并完成入网"; exit 0 ;;
    expired|failed|revoked) fail "主控入网失败：$STATE" ;;
  esac
  i=$((i + 1)); sleep 2
done
fail "Agent 已部署，但主控仍在等待 DNS/HTTPS 验证；请稍后查看邀请状态"
'''


async def verify_candidate(config: HostConfig) -> tuple[bool, dict | None, str | None]:
    client = AgentClient(config)
    try:
        if not await client.ping():
            return False, None, "Docker ping failed"
        info = await client.info()
        self_info = await client.get_self()
        return True, {"info": info, "self": self_info}, None
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: Agent validation request failed"
    finally:
        await client.close()


async def verify_candidates(
    agent_url_candidates: Iterable[str], agent_token_encrypted: str, secret_path: str
) -> tuple[str | None, dict | None, str | None]:
    seen: set[str] = set()
    last_error: str | None = None
    for raw in agent_url_candidates:
        candidate = normalize_url(raw)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        cfg = HostConfig(
            host_id="enrollment-check",
            display_name="Enrollment check",
            agent_url=f"{candidate}/{secret_path.strip('/')}",
            agent_token_encrypted=agent_token_encrypted,
        )
        ok, details, err = await verify_candidate(cfg)
        if ok:
            return candidate, details, None
        last_error = err
    return None, None, last_error or "No reachable candidate URL"


async def suggest_location_from_ip(ip: str | None) -> dict | None:
    # With no usable client/host IP, ipwho.is resolves the Dashboard's own
    # public egress address. This is useful behind a local reverse proxy.
    if ip:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            ip = None
    if ip and is_private_host(ip):
        ip = None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            endpoint = f"https://ipwho.is/{ip}" if ip else "https://ipwho.is/"
            response = await client.get(
                endpoint,
                params={"fields": "success,city,region,country,country_code,latitude,longitude"},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("success") is False:
                return None
            return normalize_geolocation(payload)
    except Exception:
        return None


async def search_location_names(query: str, language: str = "zh") -> list[dict]:
    """Resolve a city/place name to selectable WGS84 coordinates."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={
                    "name": query[:120],
                    "count": 8,
                    "language": (language or "en").lower()[:8],
                    "format": "json",
                },
            )
            response.raise_for_status()
            payload = response.json()
        results: list[dict] = []
        for item in payload.get("results") or []:
            try:
                latitude = float(item["latitude"])
                longitude = float(item["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            city = str(item.get("name") or "").strip() or None
            region = str(item.get("admin1") or item.get("admin2") or "").strip() or None
            country = str(item.get("country") or "").strip() or None
            country_code = str(item.get("country_code") or "").strip().upper()[:8] or None
            results.append({
                "name": city or query,
                "city": city,
                "region": region,
                "country": country,
                "country_code": country_code,
                "latitude": latitude,
                "longitude": longitude,
                "source": "open-meteo",
                "confirmed": False,
            })
        return results
    except Exception:
        return []


def candidate_host_ip(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).hostname
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        return None


def create_invite(session: Session, username: str, dashboard_url: str, agent_public_host: str, stack_root: str, agent_port: int, agent_image: str) -> tuple[EnrollmentInvite, str]:
    claim_token = secrets.token_urlsafe(32)
    agent_token = secrets.token_urlsafe(48)
    invite_id = uuid.uuid4().hex
    install_token = _envelope(invite_id, claim_token)
    invite = EnrollmentInvite(
        invite_id=invite_id,
        install_token_hash=token_hash(install_token),
        claim_token_hash=token_hash(claim_token),
        agent_token_encrypted=encrypt_string(agent_token),
        secret_path="fleetge-" + secrets.token_urlsafe(12),
        agent_public_host=agent_public_host,
        agent_instance_id=uuid.uuid4().hex,
        agent_port=agent_port,
        stack_root=stack_root,
        agent_image=agent_image,
        dashboard_url=dashboard_url.rstrip("/"),
        expires_at=utc_now() + INVITE_TTL,
        created_by=username,
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return invite, install_token


def expire_invite_if_needed(invite: EnrollmentInvite) -> bool:
    if invite.status in {"active", "revoked", "expired"}:
        return invite.status == "expired"
    if ensure_utc(invite.expires_at) <= utc_now():
        invite.status = "expired"
        invite.agent_token_encrypted = None
        invite.secret_path = None
        invite.failure_reason = "Invitation expired"
        return True
    return False


def choose_host_id(session: Session, hostname: str, instance_id: str) -> str:
    base = slugify(hostname)
    existing = session.exec(select(HostConfig).where(HostConfig.host_id == base)).first()
    if not existing or existing.agent_instance_id == instance_id:
        return base
    suffix = slugify(instance_id[:6])
    candidate = f"{base}-{suffix}"
    n = 2
    while session.exec(select(HostConfig).where(HostConfig.host_id == candidate)).first():
        candidate = f"{base}-{suffix}-{n}"
        n += 1
    return candidate


def location_for_host(host: HostConfig) -> dict | None:
    if host.location_latitude is None or host.location_longitude is None:
        return None
    return {
        "latitude": host.location_latitude,
        "longitude": host.location_longitude,
        "city": host.location_city,
        "region": host.location_region,
        "country": host.location_country,
        "country_code": host.location_country_code,
        "source": host.location_source,
        "confirmed": bool(host.location_confirmed),
        "confidence": host.location_confidence,
    }


async def activate_or_update_host(
    session: Session,
    invite: EnrollmentInvite,
    hostname: str,
    instance_id: str,
    agent_url: str,
    location: dict | None,
) -> HostConfig:
    existing = session.exec(
        select(HostConfig).where(HostConfig.agent_instance_id == instance_id)
    ).first()
    if existing is None:
        host_id = choose_host_id(session, hostname, instance_id)
        existing = HostConfig(host_id=host_id, display_name=hostname or host_id, enabled=True)
        session.add(existing)
    existing.display_name = hostname or existing.display_name or existing.host_id
    existing.enabled = True
    existing.agent_url = agent_url.rstrip("/") + "/" + (invite.secret_path or "").strip("/")
    existing.agent_token_encrypted = invite.agent_token_encrypted
    existing.agent_instance_id = instance_id
    existing.enrollment_callback_ip = invite.callback_ip
    existing.enrollment_callback_mode = invite.callback_mode
    invite.host_id = existing.host_id
    invite.status = "active"
    invite.completed_at = utc_now()
    # Remove sensitive material from the invitation after successful claim.
    invite.agent_token_encrypted = None
    invite.secret_path = None
    session.commit()
    write_hosts_to_yaml()
    await snapshot_manager.refresh_hosts()
    return existing


class EnrollmentMonitor:
    """Keep verifying claimed public Agent URLs until invite expiry."""

    def __init__(self, interval: float = 5.0):
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._wake_event = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="fleetge-enrollment-monitor")

    async def stop(self) -> None:
        self._stop.set()
        self._wake_event.set()
        if self._task:
            await self._task
            self._task = None

    def wake(self) -> None:
        self._wake_event.set()

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self._scan_once()
            self._wake_event.clear()
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    async def _scan_once(self) -> None:
        with Session(engine) as session:
            invites = session.exec(
                select(EnrollmentInvite).where(EnrollmentInvite.status == "verifying")
            ).all()
            invite_ids = [invite.invite_id for invite in invites]
        for invite_id in invite_ids:
            if self._stop.is_set():
                return
            await self._verify_invite(invite_id)

    async def _verify_invite(self, invite_id: str) -> None:
        with Session(engine) as session:
            invite = session.exec(
                select(EnrollmentInvite).where(EnrollmentInvite.invite_id == invite_id)
            ).first()
            if invite is None or invite.status != "verifying":
                return
            if expire_invite_if_needed(invite):
                session.commit()
                return
            if not invite.agent_public_host or not invite.agent_token_encrypted or not invite.secret_path:
                invite.status = "failed"
                invite.failure_reason = "Enrollment credentials are incomplete"
                session.commit()
                return
            public_host = invite.agent_public_host
            encrypted_token = invite.agent_token_encrypted
            secret_path = invite.secret_path
            instance_id = invite.agent_instance_id
            hostname = invite.hostname or invite.host_id or "enrolled-host"
            location = None
            if invite.location_payload:
                try:
                    location = json.loads(invite.location_payload)
                except (TypeError, ValueError):
                    location = None

        try:
            agent_url, details, failure = await verify_candidates(
                [f"https://{public_host}"], encrypted_token, secret_path
            )
            self_info = (details or {}).get("self") or {}
            reported_instance = str(self_info.get("instance_id") or "")
            if reported_instance and reported_instance != instance_id:
                agent_url = None
                failure = "Agent instance identity did not match"
        except Exception:
            agent_url = None
            failure = "Agent verification request failed"

        with Session(engine) as session:
            invite = session.exec(
                select(EnrollmentInvite).where(EnrollmentInvite.invite_id == invite_id)
            ).first()
            if invite is None or invite.status != "verifying":
                return
            if not agent_url:
                invite.failure_reason = failure or "等待 DNS、HTTPS 或 Agent 可访问"
                session.commit()
                return
            await activate_or_update_host(
                session,
                invite,
                hostname,
                instance_id,
                agent_url,
                location,
            )


enrollment_monitor = EnrollmentMonitor()
