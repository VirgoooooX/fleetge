"""Opt-in automatic updates and durable manual update runs."""

import asyncio
import json
import logging
import re
import uuid
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session, select

from app.database import engine
from app.models import AuditLog, AutoUpdateRun, ImageUpdateCache, Setting, StackAutoUpdate
from app.services.agent_client import AgentClient
from app.services.crypto import decrypt_string, encrypt_string
from app.services.notification_cover import prepare_notification
from app.services.update_check import _normalize_digest, _parse_platform, _platform_matches

logger = logging.getLogger(__name__)
NOTIFY_KEYS = ("NOTIFYHUB_URL", "NOTIFYHUB_KEY", "NOTIFYHUB_RECIPIENT")
PULL_RETRY_DELAY = 10
OPERATION_TIMEOUT = 600
TERMINAL_STATES = {"success", "partial", "failed", "uncertain", "skipped"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_engine():
    import app.services.auto_update as this_module
    return getattr(this_module, "engine", engine)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class UpdateRunError(Exception):
    def __init__(self, status_code: int, detail: str, *, existing_id: int | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.existing_id = existing_id


def notify_settings(session: Session | None = None) -> dict[str, str]:
    if session is not None:
        rows = session.exec(select(Setting).where(Setting.setting_key.in_(NOTIFY_KEYS))).all()
        return {row.setting_key: row.setting_value for row in rows}
    with Session(get_engine()) as s:
        rows = s.exec(select(Setting).where(Setting.setting_key.in_(NOTIFY_KEYS))).all()
        return {row.setting_key: row.setting_value for row in rows}


def save_notify_settings(url: str, recipient: str, api_key: str | None) -> None:
    url = url.strip().rstrip("/")
    recipient = recipient.strip()
    if url:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Notify Hub URL must be an HTTP(S) base URL without credentials, query or fragment")
    if recipient == "@all":
        raise ValueError("Select an individual Notify Hub recipient")
    values = {"NOTIFYHUB_URL": url, "NOTIFYHUB_RECIPIENT": recipient}
    if api_key is not None:
        api_key = api_key.strip()
        if api_key and not api_key.startswith("nfy_"):
            raise ValueError("Notify Hub API key must start with nfy_")
        values["NOTIFYHUB_KEY"] = encrypt_string(api_key) if api_key else ""
    with Session(get_engine()) as session:
        for key, value in values.items():
            row = session.get(Setting, key) or Setting(setting_key=key)
            row.setting_value = value
            session.add(row)
        for run in session.exec(select(AutoUpdateRun).where(AutoUpdateRun.notify_status == "blocked")).all():
            if run.notify_url == url and run.notify_recipient == recipient:
                run.notify_status = "pending"
                run.notify_next_at = now_utc()
                session.add(run)
        session.commit()


def stack_policy(host_id: str, stack_name: str) -> StackAutoUpdate:
    with Session(get_engine()) as session:
        return session.exec(select(StackAutoUpdate).where(
            StackAutoUpdate.host_id == host_id, StackAutoUpdate.stack_name == stack_name,
        )).first() or StackAutoUpdate(host_id=host_id, stack_name=stack_name)


def policy_map(host_id: str) -> dict[str, StackAutoUpdate]:
    with Session(get_engine()) as session:
        return {row.stack_name: row for row in session.exec(select(StackAutoUpdate).where(StackAutoUpdate.host_id == host_id)).all()}


def stack_summaries(snap) -> list:
    policies = policy_map(snap.host_config.host_id)
    return [stack.model_copy(update={
        "auto_update_enabled": policies[stack.name].enabled if stack.name in policies else False,
        "auto_update_reason": policies[stack.name].reason if stack.name in policies else "",
    }) for stack in snap.stacks]


def set_policy(host_id: str, stack_name: str, enabled: bool) -> StackAutoUpdate:
    with Session(get_engine()) as session:
        row = session.exec(select(StackAutoUpdate).where(
            StackAutoUpdate.host_id == host_id, StackAutoUpdate.stack_name == stack_name,
        )).first() or StackAutoUpdate(host_id=host_id, stack_name=stack_name)
        row.enabled = enabled
        row.reason = ""
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def control_stack(snap, stack_name: str, self_info: dict) -> bool:
    if self_info.get("stack_name") == stack_name:
        return True
    for container in snap.containers:
        if container.stack_name != stack_name:
            continue
        repository = container.image.split("@", 1)[0].rsplit("/", 1)[-1].split(":", 1)[0]
        if repository in {"fleetge", "fleetge-agent"}:
            return True
    return False


def scrub_log(text: str, token: str = "", *, terminal: bool = False) -> str:
    if token:
        text = text.replace(token, "[redacted]")
    if not terminal:
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"(?i)((?:password|token|api[_-]?key|authorization)\s*[:=]\s*)\S+", r"\1[redacted]", text)
    text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text)
    return text[-6000:]


class AutoUpdateManager:
    def __init__(self):
        self.started = False
        self.pending: dict[str, dict[str, tuple[int, list[str]]]] = {}
        self.workers: dict[str, asyncio.Task] = {}
        self.active: set[tuple[str, str]] = set()
        self.notify_task: asyncio.Task | None = None
        # Replay recent raw terminal chunks to viewers without owning execution.
        # Persistent audit tails remain plain text and separately bounded.
        self.output: OrderedDict[int, deque[tuple[int, str]]] = OrderedDict()
        self.output_sequences: dict[int, int] = {}

    @staticmethod
    def snapshots():
        from app.services.snapshot import snapshot_manager
        return snapshot_manager

    async def start(self) -> None:
        if self.started:
            return
        self.started = True
        with Session(get_engine()) as session:
            rows = session.exec(select(AutoUpdateRun).where(AutoUpdateRun.status.in_(["running", "queued"]))).all()
            for run in rows:
                if run.status == "running":
                    self.finish(run.id, "uncertain", "升级过程中 Fleetge 重启，执行结果未确认。请查看容器状态。")
                else:
                    self.finish(run.id, "skipped", "Fleetge 重启前任务尚未开始，未自动重放。")
        self.notify_task = asyncio.create_task(self.notification_loop())

    async def stop(self) -> None:
        self.started = False
        with Session(get_engine()) as session:
            queued = session.exec(select(AutoUpdateRun).where(AutoUpdateRun.status == "queued")).all()
            for run in queued:
                run.status = "skipped"
                run.stage = "skipped"
                run.detail = "Fleetge 已停止，尚未启动的更新未执行。"
                run.finished_at = now_utc()
                session.add(run)
            session.commit()
        tasks = list(self.workers.values()) + ([self.notify_task] if self.notify_task else [])
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.workers.clear()
        self.pending.clear()
        self.notify_task = None

    def enqueue(self, host_id: str, freshly_updatable: list[str]) -> None:
        if not self.started or not freshly_updatable:
            return
        snap = self.snapshots().get_snapshot(host_id)
        if snap is None or not snap.host_config or not snap.host_config.enabled:
            return
        policies = policy_map(host_id)
        fresh = set(freshly_updatable)
        for stack in snap.stacks:
            if not policies.get(stack.name) or not policies[stack.name].enabled or stack.status != "running":
                continue
            images = list(dict.fromkeys(c.image for c in snap.containers if c.stack_name == stack.name and c.image))
            if not fresh.intersection(images) or (host_id, stack.name) in self.active:
                continue
            checks = {r.image: r for r in snap.update_check_results}
            targets = [image for image in images if snap.update_results.get(image) == "updatable"
                       and checks.get(image) and checks[image].status == "updatable"
                       and not checks[image].last_failure_status]
            if not targets:
                continue
            request_id = str(uuid.uuid4())
            with Session(get_engine()) as session:
                active_run = session.exec(select(AutoUpdateRun).where(
                    AutoUpdateRun.host_id == host_id,
                    AutoUpdateRun.stack_name == stack.name,
                    AutoUpdateRun.status.in_(["queued", "running"]),
                )).first()
                if active_run:
                    continue
                run = AutoUpdateRun(
                    host_id=host_id,
                    request_id=request_id,
                    source="auto",
                    requested_by="system",
                    stack_name=stack.name,
                    status="queued",
                    stage="queued",
                )
                session.add(run)
                session.commit()
                session.refresh(run)
                self.pending.setdefault(host_id, {})[stack.name] = (run.id, targets)
        self._start_worker(host_id)

    def _start_worker(self, host_id: str) -> None:
        if self.started and self.pending.get(host_id) and host_id not in self.workers:
            task = asyncio.create_task(self.run_host(host_id))
            self.workers[host_id] = task

    async def run_host(self, host_id: str) -> None:
        try:
            while self.pending.get(host_id) and self.started:
                stack_name = next(iter(self.pending[host_id]))
                run_id, targets = self.pending[host_id].pop(stack_name)
                with Session(get_engine()) as session:
                    run = session.get(AutoUpdateRun, run_id)
                    queued = bool(run and run.status == "queued")
                if not queued:
                    continue
                self.active.add((host_id, stack_name))
                try:
                    await self.run_stack(host_id, stack_name, targets, run_id=run_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Update failed for %s/%s", host_id, stack_name)
                    self.finish(run_id, "uncertain", "升级未获得明确结果，请检查容器状态。")
                finally:
                    self.active.discard((host_id, stack_name))

                # Each Stack/service owns its outcome. An uncertain result does
                # not cancel unrelated updates in the same host batch.

        finally:
            self.workers.pop(host_id, None)
            self.pending.pop(host_id, None)

    async def submit(self, host_id: str, request_id: str, mode: str, stack_names: list[str], requested_by: str) -> dict:
        if not self.started:
            raise UpdateRunError(503, "Update scheduler is unavailable.")
        try:
            request_id = str(uuid.UUID(request_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise UpdateRunError(422, "request_id must be a UUID.") from exc
        if mode not in {"manual", "bulk"}:
            raise UpdateRunError(422, "mode must be manual or bulk.")
        names = list(dict.fromkeys(name.strip() for name in stack_names if name and name.strip()))
        if not names or (mode == "manual" and len(names) != 1):
            raise UpdateRunError(422, "manual mode requires one Stack; bulk mode requires at least one Stack.")

        with Session(get_engine()) as session:
            existing = session.exec(select(AutoUpdateRun).where(AutoUpdateRun.request_id == request_id).order_by(AutoUpdateRun.id)).all()
            if existing:
                if any(row.host_id != host_id for row in existing):
                    raise UpdateRunError(409, "request_id is already used by another host.")
                existing_names = [row.stack_name for row in existing]
                if any(row.source != mode for row in existing) or existing_names != names:
                    raise UpdateRunError(409, "request_id was already submitted with different parameters.")
                return self.batch_payload(existing)

        snap = self.snapshots().get_snapshot(host_id)
        if not snap or not snap.host_config:
            raise UpdateRunError(404, f"Host '{host_id}' not found.")
        stacks = {stack.name: stack for stack in snap.stacks}
        missing = [name for name in names if name not in stacks]
        if missing:
            raise UpdateRunError(404, f"Stack not found: {', '.join(missing)}")

        self_info: dict = {}
        if snap.host_config.agent_url:
            conn = AgentClient(snap.host_config)
            try:
                self_info = await conn.get_self()
            except Exception as exc:
                if mode == "bulk" and not all(control_stack(snap, name, {}) for name in names):
                    raise UpdateRunError(503, "Cannot confirm the Agent Stack identity; bulk update was not accepted.") from exc
            finally:
                await conn.close()

        runs: list[AutoUpdateRun] = []
        with Session(get_engine()) as session:
            for name in names:
                stack = stacks[name]
                reason = ""
                status = "queued"
                if mode == "bulk" and control_stack(snap, name, self_info):
                    status, reason = "skipped", "Fleetge／Agent 自身所在的 Stack，请使用单独更新入口。"
                elif mode == "bulk" and stack.management_status == "unmanaged":
                    status, reason = "skipped", "该 Stack 没有可管理的 Compose 配置。"
                elif mode == "bulk" and stack.status != "running":
                    status, reason = "skipped", "Stack 当前未运行，未提交更新。"

                active_run = session.exec(select(AutoUpdateRun).where(
                    AutoUpdateRun.host_id == host_id,
                    AutoUpdateRun.stack_name == name,
                    AutoUpdateRun.status.in_(["queued", "running"]),
                )).first()
                if active_run:
                    if mode == "manual":
                        raise UpdateRunError(409, f"Stack '{name}' already has an active update run.", existing_id=active_run.id)
                    status, reason = "skipped", f"Stack 已有活动更新任务（run {active_run.id}）。"

                run = AutoUpdateRun(
                    host_id=host_id,
                    request_id=request_id,
                    source=mode,
                    requested_by=requested_by,
                    stack_name=name,
                    status=status,
                    stage="queued" if status == "queued" else "skipped",
                    detail=reason,
                    finished_at=now_utc() if status == "skipped" else None,
                )
                session.add(run)
                runs.append(run)
            session.commit()
            for run in runs:
                session.refresh(run)
                if run.status == "queued":
                    images = [
                        container.image for container in snap.containers
                        if container.stack_name == run.stack_name and container.image
                    ]
                    self.pending.setdefault(host_id, {})[run.stack_name] = (run.id, list(dict.fromkeys(images)))
        self._start_worker(host_id)
        return self.batch_payload(runs)

    @staticmethod
    def item_payload(run: AutoUpdateRun) -> dict:
        return {
            "id": run.id,
            "host_id": run.host_id,
            "request_id": run.request_id or "",
            "source": run.source or "auto",
            "requested_by": run.requested_by or "system",
            "stack_name": run.stack_name,
            "status": run.status,
            "stage": run.stage,
            "attempts": run.attempts,
            "detail": run.detail,
            "log_tail": run.log_tail,
            "targets_json": run.targets_json,
            "agent_job_id": run.agent_job_id,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }

    @classmethod
    def batch_payload(cls, runs: list[AutoUpdateRun]) -> dict:
        if not runs:
            return {}
        counts = {status: 0 for status in ("queued", "running", "success", "partial", "failed", "uncertain", "skipped")}
        for run in runs:
            if run.status in counts:
                counts[run.status] += 1
        return {
            "host_id": runs[0].host_id,
            "request_id": runs[0].request_id or "",
            "mode": runs[0].source or "auto",
            "items": [cls.item_payload(run) for run in runs],
            "finished": counts["queued"] == 0 and counts["running"] == 0,
            "counts": counts,
        }

    def get_batch(self, host_id: str, request_id: str) -> dict | None:
        with Session(get_engine()) as session:
            runs = session.exec(select(AutoUpdateRun).where(
                AutoUpdateRun.host_id == host_id,
                AutoUpdateRun.request_id == request_id,
            ).order_by(AutoUpdateRun.id)).all()
            return self.batch_payload(runs) if runs else None

    def list_runs(self, host_id: str) -> dict:
        with Session(get_engine()) as session:
            active = session.exec(select(AutoUpdateRun).where(
                AutoUpdateRun.host_id == host_id,
                AutoUpdateRun.status.in_(["queued", "running"]),
            ).order_by(AutoUpdateRun.id)).all()
            recent = session.exec(select(AutoUpdateRun).where(
                AutoUpdateRun.host_id == host_id,
                AutoUpdateRun.status.not_in(["queued", "running"]),
            ).order_by(AutoUpdateRun.id.desc()).limit(50)).all()
            return {"active": [self.item_payload(row) for row in active], "recent": [self.item_payload(row) for row in reversed(recent)]}

    def stop_pending(self, host_id: str, request_id: str) -> dict | None:
        with Session(get_engine()) as session:
            runs = session.exec(select(AutoUpdateRun).where(
                AutoUpdateRun.host_id == host_id,
                AutoUpdateRun.request_id == request_id,
            ).order_by(AutoUpdateRun.id)).all()
            if not runs:
                return None
            if any(run.source != "bulk" for run in runs):
                raise UpdateRunError(409, "Only bulk update batches can stop pending projects.")
            now = now_utc()
            for run in runs:
                if run.status == "queued":
                    run.status = "skipped"
                    run.stage = "skipped"
                    run.detail = "用户停止了该批次尚未开始的项目。"
                    run.finished_at = now
                    session.add(run)
                    self.pending.get(host_id, {}).pop(run.stack_name, None)
            session.commit()
            for run in runs:
                session.refresh(run)
            return self.batch_payload(runs)

    def eligible(self, host_id: str, stack_name: str, source: str = "auto"):
        if source == "auto" and not stack_policy(host_id, stack_name).enabled:
            return None
        snap = self.snapshots().get_snapshot(host_id)
        if not snap or not snap.host_config or not snap.host_config.enabled or not snap.host_config.agent_url or snap.status != "online":
            return None
        stack = next((s for s in snap.stacks if s.name == stack_name), None)
        return snap if stack and stack.status == "running" and stack.management_status != "unmanaged" else None

    def _set_run_stage(self, run_id: int, stage: str, *, attempts: int | None = None, targets: dict | None = None) -> None:
        with Session(get_engine()) as session:
            run = session.get(AutoUpdateRun, run_id)
            if not run or run.status not in {"queued", "running"}:
                return
            changed_stage = run.stage != stage
            run.status = "running"
            run.stage = stage
            if attempts is not None:
                run.attempts = attempts
            if targets is not None:
                run.targets_json = json.dumps(targets, ensure_ascii=False)
            session.add(run)
            session.commit()
        if changed_stage and stage == "verify":
            self._append_run_log(run_id, "\r\n[Fleetge] 正在本地校验运行镜像与缓存目标，并等待容器健康检查（不查询仓库）…\r\n")

    def _publish_run_output(self, run_id: int, text: str, token: str = "") -> None:
        if not text:
            return
        if run_id not in self.output:
            self.output[run_id] = deque(maxlen=256)
            if len(self.output) > 50:
                removed_id, _ = self.output.popitem(last=False)
                self.output_sequences.pop(removed_id, None)
        sequence = self.output_sequences.get(run_id, 0) + 1
        self.output_sequences[run_id] = sequence
        self.output[run_id].append((sequence, scrub_log(text, token, terminal=True)))

    def read_run_output(self, run_id: int, after: int = 0) -> list[tuple[int, str]] | None:
        chunks = self.output.get(run_id)
        return None if chunks is None else [(sequence, text) for sequence, text in chunks if sequence > after]

    def _append_run_log(self, run_id: int, text: str, token: str = "", *, publish: bool = True) -> str:
        if publish:
            self._publish_run_output(run_id, text, token)
        with Session(get_engine()) as session:
            run = session.get(AutoUpdateRun, run_id)
            if not run:
                return ""
            run.log_tail = scrub_log((run.log_tail or "") + text, token)
            session.add(run)
            session.commit()
            return run.log_tail

    async def execute(self, conn: AgentClient, stack_name: str, run_id: int | None = None, *, services: list[str]) -> tuple[dict, str]:
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(conn.stack_action(stack_name, "updateServices", log_queue=queue, services=services))
        last_saved = 0.0
        unsaved = ""
        tail = ""
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT):
                while True:
                    chunk = await queue.get()
                    if chunk is None:
                        break
                    if run_id is not None:
                        self._publish_run_output(run_id, chunk, getattr(conn, "_token", ""))
                    unsaved += chunk
                    tail = (tail + chunk)[-6000:]
                    if run_id is not None and asyncio.get_running_loop().time() - last_saved >= 1.0:
                        self._append_run_log(run_id, unsaved, getattr(conn, "_token", ""), publish=False)
                        unsaved = ""
                        last_saved = asyncio.get_running_loop().time()
                if run_id is not None and unsaved:
                    self._append_run_log(run_id, unsaved, getattr(conn, "_token", ""), publish=False)
                    unsaved = ""
                result = await task
            return result, scrub_log(tail, getattr(conn, "_token", ""))
        finally:
            if run_id is not None and unsaved:
                self._append_run_log(run_id, unsaved, getattr(conn, "_token", ""), publish=False)
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    def _running_services(snap, stack_name: str) -> dict[str, list]:
        services: dict[str, list] = {}
        for container in snap.containers:
            if getattr(container, "stack_name", None) != stack_name:
                continue
            state = getattr(container, "state", None) or "running"
            if state != "running":
                continue
            service_name = getattr(container, "service_name", None)
            if not service_name:
                continue
            if (getattr(container, "labels", None) or {}).get("com.docker.compose.oneoff", "False").lower() == "true":
                continue
            services.setdefault(service_name, []).append(container)
        return services

    def _select_update_services(self, snap, stack_name: str) -> tuple[dict[str, dict], dict[str, dict]]:
        """Freeze typed registry evidence from the existing check cache."""
        checks = {result.image: result for result in snap.update_check_results}
        with Session(get_engine()) as session:
            rows = session.exec(select(ImageUpdateCache).where(ImageUpdateCache.host_id == snap.host_config.host_id)).all()
            checked_at = {row.image: row.checked_at.isoformat() for row in rows}
        selected: dict[str, dict] = {}
        skipped: dict[str, dict] = {}
        for service, containers in self._running_services(snap, stack_name).items():
            image = containers[0].image
            result = checks.get(image)
            if not result or result.status not in {"updatable", "up_to_date"} or result.last_failure_status:
                reason = f"镜像检测不可用（{getattr(result, 'last_failure_status', None) or getattr(result, 'status', 'unknown')}），请检查更新。"
            elif snap.update_results.get(image) != "updatable":
                reason = "没有检测到更新。"
            elif not result.platform or not (result.registry_config_digest or result.registry_manifest_digest):
                reason = "缓存缺少有效的平台或目标摘要，请检查更新。"
            else:
                if all(
                    _platform_matches(_parse_platform(container.platform), _parse_platform(result.platform), exact_variant=False)
                    and (
                        (container.image_config_digest and result.registry_config_digest
                         and _normalize_digest(container.image_config_digest) == _normalize_digest(result.registry_config_digest))
                        or (not container.image_config_digest and container.image_manifest_digest and result.registry_manifest_digest
                            and _normalize_digest(container.image_manifest_digest) == _normalize_digest(result.registry_manifest_digest))
                    )
                    for container in containers
                ):
                    skipped[service] = {"status": "skipped", "detail": "服务已使用缓存目标镜像。"}
                    continue
                selected[service] = {
                    "image": image,
                    "container_count": len(containers),
                    "cached_target": {
                        "registry_config_digest": result.registry_config_digest,
                        "registry_manifest_digest": result.registry_manifest_digest,
                        "platform": result.platform,
                        "checked_at": checked_at.get(image),
                    },
                }
                continue
            skipped[service] = {"status": "skipped", "detail": reason}
        return selected, skipped

    @staticmethod
    def _service_outcome(results: dict[str, dict]) -> tuple[str, str]:
        states = [result["status"] for result in results.values()]
        if "success" in states and any(state in {"failed", "uncertain"} for state in states):
            status = "partial"
        elif "uncertain" in states:
            status = "uncertain"
        elif "failed" in states:
            status = "failed"
        elif "success" in states:
            status = "success"
        else:
            status = "skipped"
        labels = {"success": "成功", "failed": "失败", "uncertain": "待确认", "skipped": "跳过", "partial": "部分成功"}
        detail = labels[status] + "；" + "；".join(
            f"{service}：{labels[result['status']]}，{result['detail']}"
            for service, result in results.items()
        ) if results else "跳过：Stack 没有可更新的运行服务。"
        return status, detail

    async def _run_self_stack_update(self, conn: AgentClient, run_id: int, snap, stack_name: str, self_info: dict) -> None:
        selected, service_results = self._select_update_services(snap, stack_name)
        task_targets = {"services": selected, "results": service_results}
        self._set_run_stage(run_id, "preflight", targets=task_targets)
        # The detached job survives either the Dashboard or Agent restarting.
        # Submit one service at a time so a failed pull cannot block siblings.
        agent_service = self_info.get("service_name")
        # Update the Agent first: its detached job survives the handoff, while
        # recreating the Dashboard can stop this scheduler before the next job.
        for service in sorted(selected, key=lambda name: name != agent_service):
            try:
                status, detail = await self._run_control_service_job(
                    conn, run_id, snap, stack_name, service, selected[service], self_info,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                status, detail = "uncertain", f"控制服务执行结果未确认：{exc}"
            service_results[service] = {"status": status, "detail": detail}
            self._append_run_log(run_id, f"\r\n[Fleetge] {service}: {status} — {detail}\r\n")
            self._set_run_stage(run_id, "service_done", targets=task_targets)
        status, detail = self._service_outcome(service_results)
        self.finish(run_id, status, detail)

    async def _run_control_service_job(self, conn, run_id, snap, stack_name, service, target, self_info) -> tuple[str, str]:
        selected_services = [service]
        before_update = snap.containers_updated
        agent_service = self_info.get("service_name")
        action = "selfUpdate" if agent_service in selected_services else "updateServicesJob"
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(conn.stack_action(stack_name, action, log_queue=queue, services=selected_services))
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT):
                while True:
                    chunk = await queue.get()
                    if chunk is None:
                        break
                    self._append_run_log(run_id, chunk, conn._token)
                result = await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        if not result.get("success", result.get("ok", False)):
            if result.get("error_code") == "stack_busy":
                return "skipped", result.get("message") or "控制 Stack 正在执行其他操作。"
            elif result.get("interrupted"):
                return "uncertain", result.get("message") or "Agent 连接中断，控制 Stack 更新结果未确认。"
            else:
                return "failed", result.get("message", "控制 Stack 更新任务启动失败。")

        job_id = result.get("job_id")
        if not job_id:
            return "uncertain", "Agent 未返回可跟踪的控制 Stack 更新任务 ID。"
        with Session(get_engine()) as session:
            run = session.get(AutoUpdateRun, run_id)
            run.agent_job_id = job_id
            run.stage = "pull"
            session.add(run)
            session.commit()

        started = asyncio.get_running_loop().time()
        last_log_size = 0
        job: dict = {}
        while asyncio.get_running_loop().time() - started < OPERATION_TIMEOUT:
            try:
                logs = await conn.get_job_logs(job_id)
                content = logs.get("content", "")
                if len(content) > last_log_size:
                    self._append_run_log(run_id, content[last_log_size:], conn._token)
                    last_log_size = len(content)
                job = await conn.get_job(job_id)
            except Exception:
                await asyncio.sleep(2.0)
                continue
            self._set_run_stage(run_id, job.get("phase") or job.get("status") or "running")
            if job.get("status") in TERMINAL_STATES | {"error"}:
                break
            await asyncio.sleep(2.0)
        else:
            return "uncertain", f"Agent job {job_id} did not reach a confirmed terminal state."

        if job.get("status") == "failed" or job.get("status") == "error":
            return "failed", job.get("message") or f"Agent job {job_id} failed."
        if job.get("status") in {"uncertain", "skipped"}:
            return job["status"], job.get("message") or f"Agent job {job_id} ended as {job['status']}."
        if job.get("status") != "success":
            return "uncertain", f"Agent job {job_id} returned no final result."
        if job.get("up_executed") is False:
            return "skipped", "Agent job completed without executing Compose up."
        if job.get("up_executed") is not True:
            return "uncertain", "Agent job did not report whether Compose up was executed."

        pulled = {item.get("service"): item for item in (job.get("pulled_images") or []) if isinstance(item, dict)}
        item = pulled.get(service)
        if not item or item.get("image") != target["image"] or not item.get("image_id") or not item.get("platform"):
            return "uncertain", f"Agent job did not provide matching pulled image identity for service '{service}'."
        target.update({
            "image_id": item["image_id"],
            "repo_digests": item.get("repo_digests") or [],
            "platform": item["platform"],
        })
        self._set_run_stage(run_id, "verify")
        return await self.snapshots().verify_update_targets(
            snap.host_config.host_id, stack_name, {service: target}, not_before=before_update,
        )

    async def run_stack(self, host_id: str, stack_name: str, targets: list[str], run_id: int | None = None) -> None:
        conn: AgentClient | None = None
        try:
            await self.snapshots().refresh_host_docker(host_id, trigger_initial_update_check=False)
            snap = self.eligible(host_id, stack_name, "manual" if run_id is not None else "auto")
            if snap is None or (run_id is None and not any(snap.update_results.get(image) == "updatable" for image in targets)):
                if run_id is not None:
                    self.finish(run_id, "skipped", "主机离线、Stack 未运行/不可管理，或自动更新已关闭。")
                return
            conn = AgentClient(snap.host_config)
            try:
                self_info = await conn.get_self()
            except Exception as exc:
                if run_id is not None:
                    self.finish(run_id, "skipped", f"无法确认 Agent 所属 Stack，未执行更新：{exc}")
                return
            if not self_info.get("stack_name") or control_stack(snap, stack_name, self_info):
                if run_id is not None:
                    with Session(get_engine()) as session:
                        run = session.get(AutoUpdateRun, run_id)
                        is_manual = run and run.source == "manual"
                    if not is_manual:
                        self.finish(run_id, "skipped", "Fleetge／Agent 自身所在的 Stack 只能使用单独更新入口。")
                        return
                    await self._run_self_stack_update(conn, run_id, snap, stack_name, self_info)
                return
            detail = await conn.get_stack(stack_name)
            if not detail or not (detail.get("stack", {}).get("composeYAML") or "").strip():
                if run_id is not None:
                    self.finish(run_id, "skipped", "Stack 没有可管理的 Compose 配置。")
                return

            if run_id is None:
                with Session(get_engine()) as session:
                    run = AutoUpdateRun(host_id=host_id, stack_name=stack_name, source="auto", status="running", stage="preflight")
                    session.add(run)
                    session.commit()
                    session.refresh(run)
                    run_id = run.id
            else:
                with Session(get_engine()) as session:
                    run = session.get(AutoUpdateRun, run_id)
                    if not run or run.status != "queued":
                        return
                    run.status = "running"
                    run.stage = "preflight"
                    session.add(run)
                    session.commit()

            with Session(get_engine()) as session:
                run = session.get(AutoUpdateRun, run_id)
                source = run.source or "auto"

            selected, service_results = self._select_update_services(snap, stack_name)
            task_targets = {"services": selected, "results": service_results}
            self._set_run_stage(run_id, "preflight", targets=task_targets)
            for service, target in selected.items():
                if source == "auto" and not stack_policy(host_id, stack_name).enabled:
                    service_results[service] = {"status": "skipped", "detail": "自动更新已关闭。"}
                    continue
                self._append_run_log(run_id, f"\r\n[Fleetge] 更新服务 {service}…\r\n")
                try:
                    outcome, message = await self._update_service(conn, host_id, stack_name, run_id, source, service, target, task_targets)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Service update failed for %s/%s/%s", host_id, stack_name, service)
                    outcome, message = "uncertain", f"执行或校验未获得明确结果：{exc}"
                service_results[service] = {"status": outcome, "detail": message}
                self._append_run_log(run_id, f"\r\n[Fleetge] {service}: {outcome} — {message}\r\n")
                self._set_run_stage(run_id, "service_done", targets=task_targets)
            status, message = self._service_outcome(service_results)
            self.finish(run_id, status, message)
            return
        except asyncio.CancelledError:
            if run_id is not None:
                self.finish(run_id, "uncertain", "Fleetge 已停止，升级执行结果未确认。请检查容器状态。")
            raise
        except Exception as exc:
            logger.exception("Update failed for %s/%s", host_id, stack_name)
            if run_id is not None:
                self.finish(run_id, "uncertain", f"升级或验证未取得明确结果：{exc}")
        finally:
            if conn is not None:
                await conn.close()
            try:
                await self.snapshots().refresh_host_docker(host_id, trigger_initial_update_check=False)
            except Exception:
                logger.warning("Could not refresh containers after update")

    async def _update_service(self, conn, host_id, stack_name, run_id, source, service, target, task_targets) -> tuple[str, str]:
        before_update = self.snapshots().get_snapshot(host_id).containers_updated
        for attempt in (1, 2):
            self._set_run_stage(run_id, "pull", attempts=attempt, targets=task_targets)
            result, _ = await self.execute(conn, stack_name, run_id, services=[service])
            stage = result.get("stage") or "unknown"
            self._set_run_stage(run_id, stage)
            if result.get("error_code") == "stack_busy":
                return "skipped", result.get("message") or "Stack 正在执行其他操作。"
            if result.get("interrupted"):
                return "uncertain", "Agent 连接中断，该服务更新结果未确认。"
            if not result.get("success"):
                if stage == "pull" and attempt == 1:
                    self._append_run_log(run_id, f"\r\n[Fleetge] {service} 拉取失败，{PULL_RETRY_DELAY:g} 秒后重试一次…\r\n")
                    await asyncio.sleep(PULL_RETRY_DELAY)
                    if source == "auto" and not stack_policy(host_id, stack_name).enabled:
                        return "skipped", "自动更新已关闭，取消重试。"
                    continue
                return "failed", f"升级失败，阶段：{stage}。{result.get('message', '')}"
            if result.get("up_executed") is False:
                return "skipped", "拉取完成时 Stack 已不处于运行状态，未执行 up。"
            pulled = {item.get("service"): item for item in result.get("pulled_images", []) if isinstance(item, dict)}
            item = pulled.get(service)
            if (result.get("up_executed") is not True or not item
                    or item.get("image") != target["image"] or not item.get("image_id") or not item.get("platform")):
                return "uncertain", "Agent 未提供匹配的拉取目标及 Compose up 执行证据。"
            target.update({
                "image_id": item["image_id"], "repo_digests": item.get("repo_digests") or [],
                "platform": item["platform"],
            })
            self._set_run_stage(run_id, "verify", targets=task_targets)
            return await self.snapshots().verify_update_targets(
                host_id, stack_name, {service: target}, not_before=before_update,
            )
        return "failed", "镜像拉取失败。"

    def finish(self, run_id: int, status: str, detail: str, logs: str = "") -> None:
        if status not in TERMINAL_STATES:
            raise ValueError(f"Invalid update run terminal status: {status}")
        with Session(get_engine()) as session:
            run = session.get(AutoUpdateRun, run_id)
            if not run or run.status not in {"queued", "running"}:
                return
            if logs:
                run.log_tail = scrub_log((run.log_tail or "") + logs)
            run.status = status
            run.stage = status if status in {"uncertain", "skipped"} else run.stage
            run.detail = scrub_log(detail)
            run.finished_at = now_utc()

            if run.source == "auto" and status in {"partial", "failed", "uncertain"}:
                policy = session.exec(select(StackAutoUpdate).where(
                    StackAutoUpdate.host_id == run.host_id,
                    StackAutoUpdate.stack_name == run.stack_name,
                )).first()
                if policy:
                    policy.enabled = False
                    policy.reason = run.detail
                    session.add(policy)

            action = "stack.auto_update" if run.source == "auto" else "stack.update_run"
            session.add(AuditLog(
                user=run.requested_by or "system",
                action=action,
                host_id=run.host_id,
                stack_name=run.stack_name,
                result="error" if status == "failed" else status,
                detail=f"request_id={run.request_id}; run_id={run.id}; attempts={run.attempts}; stage={run.stage}\n{run.detail}\n{run.log_tail}",
            ))

            if run.source == "auto" and status != "skipped":
                config = notify_settings(session)
                if all(config.get(key) for key in NOTIFY_KEYS):
                    label = {"success": "成功", "partial": "部分成功", "failed": "失败", "uncertain": "结果未确认"}[status]
                    run.notify_url = config["NOTIFYHUB_URL"]
                    run.notify_recipient = config["NOTIFYHUB_RECIPIENT"]
                    snap = self.snapshots().get_snapshot(run.host_id)
                    stack = next((item for item in snap.stacks if item.name == run.stack_name), None) if snap else None
                    run.notify_payload = json.dumps({
                        "event_type": "fleetge.stack.auto_update",
                        "event_key": f"fleetge:auto-update:{run.id}:{status}:{run.started_at.isoformat()}",
                        "title": f"【Fleetge】更新{label}｜{run.stack_name}"[:40],
                        "content": f"主机：{run.host_id}\n" + ("已完成更新，运行检查通过。" if status == "success" else "该 Stack 的自动更新已暂停，请在 Fleetge 查看记录并处理。"),
                        "level": "info" if status == "success" else "warning",
                        "recipients": [run.notify_recipient],
                        "message_type": "text",
                        "_stack_icon": getattr(stack, "icon_url", None),
                    }, ensure_ascii=False)
                    run.notify_status = "pending"
                    run.notify_next_at = now_utc()
                    run.notify_expires_at = now_utc() + timedelta(hours=24)
            session.add(run)
            session.commit()

    async def notification_loop(self) -> None:
        while True:
            try:
                await self.send_notifications()
            except Exception:
                logger.exception("Automatic update notification sweep failed")
            await asyncio.sleep(30)

    async def send_notifications(self) -> None:
        config = notify_settings()
        with Session(get_engine()) as session:
            runs = session.exec(select(AutoUpdateRun).where(AutoUpdateRun.notify_status.in_(["pending", "blocked"]))).all()
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), follow_redirects=False) as client:
            for run in runs:
                expired = run.notify_expires_at and utc(run.notify_expires_at) <= now_utc()
                if expired:
                    status, error = "expired", "通知未在 24 小时内提交，已停止补发。"
                elif run.notify_status == "blocked" or (run.notify_next_at and utc(run.notify_next_at) > now_utc()):
                    continue
                else:
                    status, error = "pending", ""
                    if config.get("NOTIFYHUB_URL") != run.notify_url or config.get("NOTIFYHUB_RECIPIENT") != run.notify_recipient or not config.get("NOTIFYHUB_KEY"):
                        status, error = "blocked", "通知配置已删除或目标已改变。"
                    else:
                        try:
                            api_key = decrypt_string(config["NOTIFYHUB_KEY"])
                            payload = await prepare_notification(client, run.notify_url, api_key, json.loads(run.notify_payload))
                            # Freeze the actual media reference or text fallback before sending.
                            # A timeout/restart retries the same event and the same payload.
                            with Session(get_engine()) as session:
                                row = session.get(AutoUpdateRun, run.id)
                                row.notify_payload = json.dumps(payload, ensure_ascii=False)
                                session.add(row)
                                session.commit()
                            response = await client.post(run.notify_url + "/api/v1/events", json=payload, headers={"X-API-Key": api_key})
                            if response.status_code == 202:
                                data = response.json().get("data", {})
                                if data.get("status") == "accepted" and data.get("event_id"):
                                    status = "accepted"
                                else:
                                    error = "Notify Hub 返回 202，但未确认事件已接收。"
                            elif response.status_code == 429 or response.status_code >= 500:
                                error = f"Notify Hub HTTP {response.status_code}，稍后补发。"
                            else:
                                status, error = "blocked", f"Notify Hub HTTP {response.status_code}，请检查通知配置。"
                        except (httpx.HTTPError, ValueError):
                            error = "Notify Hub 请求未获确认，稍后使用相同事件 key 补发。"
                with Session(get_engine()) as session:
                    row = session.get(AutoUpdateRun, run.id)
                    row.notify_status = status
                    row.notify_error = error
                    row.notify_attempts += 1
                    row.notify_next_at = now_utc() + timedelta(seconds=min(3600, 60 * 2 ** min(row.notify_attempts - 1, 6)))
                    if status in {"blocked", "expired"} and run.notify_status != status:
                        session.add(AuditLog(user="system", action="stack.auto_update.notify", host_id=run.host_id, stack_name=run.stack_name, result="error", detail=error))
                    session.add(row)
                    session.commit()


auto_update_manager = AutoUpdateManager()
