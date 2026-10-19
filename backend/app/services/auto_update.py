"""Opt-in automatic updates and durable manual update runs."""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session, select

from app.database import engine
from app.models import AuditLog, AutoUpdateRun, Setting, StackAutoUpdate
from app.services.agent_client import AgentClient
from app.services.crypto import decrypt_string, encrypt_string
from app.services.update_check import run_update_check

logger = logging.getLogger(__name__)
NOTIFY_KEYS = ("NOTIFYHUB_URL", "NOTIFYHUB_KEY", "NOTIFYHUB_RECIPIENT")
PULL_RETRY_DELAY = 10
OPERATION_TIMEOUT = 600
TERMINAL_STATES = {"success", "failed", "uncertain", "skipped"}


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


def scrub_log(text: str, token: str = "") -> str:
    if token:
        text = text.replace(token, "[redacted]")
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
            if any(not checks.get(image) or checks[image].status not in {"updatable", "up_to_date"} or checks[image].last_failure_status for image in images):
                continue
            targets = [image for image in images if snap.update_results.get(image) == "updatable"]
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

                with Session(get_engine()) as session:
                    run = session.get(AutoUpdateRun, run_id)
                    is_uncertain = bool(run and run.status == "uncertain")
                    source = run.source if run else ""
                    request_id = run.request_id if run else ""

                if is_uncertain and source == "bulk" and request_id:
                    with Session(get_engine()) as session:
                        remaining_runs = session.exec(select(AutoUpdateRun).where(
                            AutoUpdateRun.host_id == host_id,
                            AutoUpdateRun.request_id == request_id,
                            AutoUpdateRun.status == "queued",
                        )).all()
                        now = now_utc()
                        for rem in remaining_runs:
                            rem.status = "skipped"
                            rem.stage = "skipped"
                            rem.detail = f"前序任务 '{stack_name}' 结果未确认，已停止后续项目执行。"
                            rem.finished_at = now
                            session.add(rem)
                            self.pending.get(host_id, {}).pop(rem.stack_name, None)
                        session.commit()
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
        counts = {status: 0 for status in ("queued", "running", "success", "failed", "uncertain", "skipped")}
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
            run.status = "running"
            run.stage = stage
            if attempts is not None:
                run.attempts = attempts
            if targets is not None:
                run.targets_json = json.dumps(targets, ensure_ascii=False)
            session.add(run)
            session.commit()

    def _append_run_log(self, run_id: int, text: str, token: str = "") -> str:
        with Session(get_engine()) as session:
            run = session.get(AutoUpdateRun, run_id)
            if not run:
                return ""
            run.log_tail = scrub_log((run.log_tail or "") + text, token)
            session.add(run)
            session.commit()
            return run.log_tail

    async def execute(self, conn: AgentClient, stack_name: str, run_id: int | None = None) -> tuple[dict, str]:
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(conn.stack_action(stack_name, "updateStack", log_queue=queue))
        last_saved = 0.0
        unsaved = ""
        tail = ""
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT):
                while True:
                    chunk = await queue.get()
                    if chunk is None:
                        break
                    unsaved += chunk
                    tail = (tail + chunk)[-6000:]
                    if run_id is not None and asyncio.get_running_loop().time() - last_saved >= 1.0:
                        self._append_run_log(run_id, unsaved, getattr(conn, "_token", ""))
                        unsaved = ""
                        last_saved = asyncio.get_running_loop().time()
                if run_id is not None and unsaved:
                    self._append_run_log(run_id, unsaved, getattr(conn, "_token", ""))
                result = await task
            return result, scrub_log(tail, getattr(conn, "_token", ""))
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    def _running_services(snap, stack_name: str) -> dict[str, list]:
        services: dict[str, list] = {}
        for container in snap.containers:
            if getattr(container, "stack_name", None) != stack_name:
                continue
            state = getattr(container, "state", None) or ("running" if (getattr(container, "status", "") or "").lower().startswith("up") else "running")
            if state != "running":
                continue
            service_name = getattr(container, "service_name", None) or getattr(container, "name", None) or "app"
            if (getattr(container, "labels", None) or {}).get("com.docker.compose.oneoff", "False").lower() == "true":
                continue
            services.setdefault(service_name, []).append(container)
        return services

    async def _run_self_stack_update(self, conn: AgentClient, run_id: int, snap, stack_name: str, self_info: dict) -> None:
        service_containers = self._running_services(snap, stack_name)
        if not service_containers:
            self.finish(run_id, "skipped", "控制 Stack 没有可更新的运行服务。")
            return

        image_refs = [
            (container.image, container.repo_digests, container.image_id, container.platform)
            for containers in service_containers.values()
            for container in containers
            if container.image
        ]
        results = await run_update_check(snap.host_config.host_id, image_refs, force=True)
        self.snapshots().persist_update_check_results(snap.host_config.host_id, results)
        by_image = {result.image: result for result in results}
        check_failures = []
        selected_services = []
        for service, containers in service_containers.items():
            result = by_image.get(containers[0].image)
            if result is None or result.status not in {"updatable", "up_to_date"}:
                check_failures.append(f"{service}={result.status if result else 'check_failed'}")
            elif self.snapshots().get_snapshot(snap.host_config.host_id).update_results.get(result.image) == "updatable":
                selected_services.append(service)
        if check_failures:
            self.finish(run_id, "failed", "控制 Stack 镜像身份检查失败：" + ", ".join(check_failures))
            return
        if not selected_services:
            self.finish(run_id, "skipped", "控制 Stack 的镜像均已是最新。")
            return

        preflight = {
            service: {"container_count": len(service_containers[service])}
            for service in selected_services
        }
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
                self.finish(run_id, "skipped", result.get("message") or "控制 Stack 正在执行其他操作。")
            elif result.get("interrupted"):
                self.finish(run_id, "uncertain", result.get("message") or "Agent 连接中断，控制 Stack 更新结果未确认。")
            else:
                self.finish(run_id, "failed", result.get("message", "控制 Stack 更新任务启动失败。"))
            return

        job_id = result.get("job_id")
        if not job_id:
            self.finish(run_id, "uncertain", "Agent 未返回可跟踪的控制 Stack 更新任务 ID。")
            return
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
            if job.get("status") in TERMINAL_STATES:
                break
            await asyncio.sleep(2.0)
        else:
            self.finish(run_id, "uncertain", f"Agent job {job_id} did not reach a confirmed terminal state.")
            return

        if job.get("status") == "failed" or job.get("status") == "error":
            self.finish(run_id, "failed", job.get("message") or f"Agent job {job_id} failed.")
            return
        if job.get("status") in {"uncertain", "skipped"}:
            self.finish(run_id, job["status"], job.get("message") or f"Agent job {job_id} ended as {job['status']}.")
            return
        if job.get("status") != "success":
            self.finish(run_id, "uncertain", f"Agent job {job_id} returned no final result.")
            return
        if job.get("up_executed") is False:
            self.finish(run_id, "skipped", "Agent job completed without executing Compose up.")
            return
        if job.get("up_executed") is not True:
            self.finish(run_id, "uncertain", "Agent job did not report whether Compose up was executed.")
            return

        pulled = {item.get("service"): item for item in (job.get("pulled_images") or []) if isinstance(item, dict)}
        targets: dict[str, dict] = {}
        for service in selected_services:
            item = pulled.get(service)
            if not item or not item.get("image_id") or not item.get("platform"):
                self.finish(run_id, "uncertain", f"Agent job did not provide pulled image identity for service '{service}'.")
                return
            targets[service] = {
                "image": item.get("image"),
                "image_id": item["image_id"],
                "repo_digests": item.get("repo_digests") or [],
                "platform": item["platform"],
                "container_count": preflight[service]["container_count"],
            }
        self._set_run_stage(run_id, "verify", targets={"services": targets, "agent_job_id": job_id})
        status, detail = await self.snapshots().verify_update_targets(
            snap.host_config.host_id, stack_name, targets, not_before=snap.containers_updated,
        )
        self.finish(run_id, status, detail)

    async def run_stack(self, host_id: str, stack_name: str, targets: list[str], run_id: int | None = None) -> None:
        created_inline = False
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
                    created_inline = True
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

            service_containers = self._running_services(snap, stack_name)
            if not service_containers:
                self.finish(run_id, "skipped", "Stack 没有可验证的运行服务。")
                return
            if source in {"auto", "bulk"} and not any(snap.update_results.get(image) == "updatable" for image in targets):
                self.finish(run_id, "skipped", "重新检查后 Stack 已无待更新镜像。")
                return

            preflight = {
                service: {
                    "container_count": len(containers),
                    "images": list(dict.fromkeys(container.image for container in containers if getattr(container, "image", None))),
                }
                for service, containers in service_containers.items()
            }
            before_update = getattr(snap, "containers_updated", 0)
            final_logs = ""
            for attempt in (1, 2):
                self._set_run_stage(run_id, "pull", attempts=attempt)
                result, tail = await self.execute(conn, stack_name)
                final_logs = self._append_run_log(run_id, f"\n--- attempt {attempt} ---\n", getattr(conn, "_token", ""))
                stage = result.get("stage") or "unknown"
                self._set_run_stage(run_id, stage)
                if result.get("error_code") == "stack_busy":
                    self.finish(run_id, "skipped", result.get("message") or "Stack 正在执行其他操作。", final_logs)
                    return
                if result.get("interrupted"):
                    self.finish(run_id, "uncertain", result.get("message") or "Agent 连接中断，升级结果未确认。", final_logs)
                    return
                if not result.get("success"):
                    if stage == "pull" and attempt == 1:
                        await asyncio.sleep(PULL_RETRY_DELAY)
                        await self.snapshots().refresh_host_docker(host_id, trigger_initial_update_check=False)
                        if source == "auto" and self.eligible(host_id, stack_name, source) is None:
                            self.finish(run_id, "skipped", "拉取失败后自动更新已关闭或 Stack 不再可更新，取消重试。", final_logs)
                            return
                        continue
                    self.finish(run_id, "failed", f"升级失败，阶段：{stage}。{result.get('message', '')}", final_logs)
                    return
                if result.get("up_executed") is False:
                    self.finish(run_id, "skipped", "拉取完成时 Stack 已不处于运行状态，未执行 up。", final_logs)
                    return

                # If the snapshot manager has verify_update_targets, use full post-update verification;
                # otherwise fall back to finalize_stack_update for backwards compatibility.
                if hasattr(self.snapshots(), "verify_update_targets") and result.get("pulled_images"):
                    pulled = {item.get("service"): item for item in (result.get("pulled_images") or []) if isinstance(item, dict)}
                    verify_targets: dict[str, dict] = {}
                    for service, expected in preflight.items():
                        item = pulled.get(service)
                        if not item or not item.get("image_id") or not item.get("platform"):
                            self.finish(run_id, "uncertain", f"无法确认服务 '{service}' 的拉取镜像身份或平台。", final_logs)
                            return
                        verify_targets[service] = {
                            "image": item.get("image"),
                            "image_id": item["image_id"],
                            "repo_digests": item.get("repo_digests") or [],
                            "platform": item["platform"],
                            "container_count": expected["container_count"],
                        }
                    self._set_run_stage(run_id, "verify", targets={"preflight": preflight, "services": verify_targets})
                    verified, message = await self.snapshots().verify_update_targets(
                        host_id, stack_name, verify_targets, not_before=before_update,
                    )
                    self.finish(run_id, verified, message, final_logs)
                    return

                if hasattr(self.snapshots(), "finalize_stack_update"):
                    previous_refresh = getattr(self.snapshots().get_snapshot(host_id), "containers_updated", 0)
                    await self.snapshots().refresh_host_docker(host_id, trigger_initial_update_check=False)
                    refreshed = self.snapshots().get_snapshot(host_id)
                    if not refreshed or refreshed.status != "online" or getattr(refreshed, "containers_updated", 0) <= previous_refresh:
                        self.finish(run_id, "uncertain", "更新命令已完成，但无法取得更新后的容器状态。已暂停自动升级，请查看实际运行状态。", final_logs)
                        return
                    self._set_run_stage(run_id, "verify")
                    summaries = await self.snapshots().finalize_stack_update(host_id, stack_name, targets, wait_timeout=45.0)
                    verified = len(summaries) == len(set(targets)) and all(getattr(s, "verified", False) for s in summaries)
                    detail = "\n".join(s.verdict for s in summaries) or "无法取得更新验证结果。"
                    self.finish(run_id, "success" if verified else "failed", detail, final_logs)
                    return

                if result.get("up_executed") is not True:
                    self.finish(run_id, "uncertain", "Agent 未确认 Compose up 是否执行；缺少目标证据。", final_logs)
                    return
                self.finish(run_id, "uncertain", "未配置更新结果验证器。", final_logs)
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

            if run.source == "auto" and status in {"failed", "uncertain"}:
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
                    label = {"success": "成功", "failed": "失败", "uncertain": "结果未确认"}[status]
                    run.notify_url = config["NOTIFYHUB_URL"]
                    run.notify_recipient = config["NOTIFYHUB_RECIPIENT"]
                    run.notify_payload = json.dumps({
                        "event_type": "fleetge.stack.auto_update",
                        "event_key": f"fleetge:auto-update:{run.id}:{status}:{run.started_at.isoformat()}",
                        "title": f"Stack 自动更新{label}：{run.stack_name}"[:200],
                        "content": f"主机：{run.host_id}\nStack：{run.stack_name}\n结果：{label}\n尝试次数：{run.attempts}\n时间：{run.finished_at.isoformat()}\n{run.detail}\n" + ("自动更新已暂停。请在 Dashboard 查看详情。" if status != "success" else ""),
                        "level": "info" if status == "success" else "warning",
                        "recipients": [run.notify_recipient],
                        "message_type": "text",
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
                            response = await client.post(run.notify_url + "/api/v1/events", json=json.loads(run.notify_payload), headers={"X-API-Key": decrypt_string(config["NOTIFYHUB_KEY"])})
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
