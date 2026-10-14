"""Opt-in automatic updates using the existing Agent update operation."""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session, select

from app.database import engine
from app.models import AuditLog, AutoUpdateRun, Setting, StackAutoUpdate
from app.services.agent_client import AgentClient
from app.services.crypto import decrypt_string, encrypt_string

logger = logging.getLogger(__name__)
NOTIFY_KEYS = ("NOTIFYHUB_URL", "NOTIFYHUB_KEY", "NOTIFYHUB_RECIPIENT")
PULL_RETRY_DELAY = 10
OPERATION_TIMEOUT = 600


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def notify_settings() -> dict[str, str]:
    with Session(engine) as session:
        rows = session.exec(select(Setting).where(Setting.setting_key.in_(NOTIFY_KEYS))).all()
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
    with Session(engine) as session:
        for key, value in values.items():
            row = session.get(Setting, key) or Setting(setting_key=key)
            row.setting_value = value
            session.add(row)
        # Correcting credentials permits resubmission to the same destination.
        for run in session.exec(select(AutoUpdateRun).where(AutoUpdateRun.notify_status == "blocked")).all():
            if run.notify_url == url and run.notify_recipient == recipient:
                run.notify_status = "pending"
                run.notify_next_at = now_utc()
                session.add(run)
        session.commit()


def stack_policy(host_id: str, stack_name: str) -> StackAutoUpdate:
    with Session(engine) as session:
        return session.exec(select(StackAutoUpdate).where(
            StackAutoUpdate.host_id == host_id, StackAutoUpdate.stack_name == stack_name,
        )).first() or StackAutoUpdate(host_id=host_id, stack_name=stack_name)


def policy_map(host_id: str) -> dict[str, StackAutoUpdate]:
    with Session(engine) as session:
        return {row.stack_name: row for row in session.exec(select(StackAutoUpdate).where(StackAutoUpdate.host_id == host_id)).all()}


def stack_summaries(snap) -> list:
    policies = policy_map(snap.host_config.host_id)
    return [stack.model_copy(update={
        "auto_update_enabled": policies[stack.name].enabled if stack.name in policies else False,
        "auto_update_reason": policies[stack.name].reason if stack.name in policies else "",
    }) for stack in snap.stacks]


def set_policy(host_id: str, stack_name: str, enabled: bool) -> StackAutoUpdate:
    with Session(engine) as session:
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
        self.pending: dict[str, dict[str, list[str]]] = {}
        self.workers: dict[str, asyncio.Task] = {}
        self.active: set[tuple[str, str]] = set()
        self.notify_task: asyncio.Task | None = None

    @staticmethod
    def snapshots():
        from app.services.snapshot import snapshot_manager
        return snapshot_manager

    async def start(self) -> None:
        self.started = True
        # An unfinished command is never assumed successful or replayed.
        with Session(engine) as session:
            ids = [run.id for run in session.exec(select(AutoUpdateRun).where(AutoUpdateRun.status == "running")).all()]
        for run_id in ids:
            self.finish(run_id, "uncertain", "升级过程中 Fleetge 重启，执行结果未确认。请查看容器状态。")
        self.notify_task = asyncio.create_task(self.notification_loop())

    async def stop(self) -> None:
        self.started = False
        tasks = list(self.workers.values()) + ([self.notify_task] if self.notify_task else [])
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.workers.clear()
        self.pending.clear()

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
            # Do not act on stale successful cache entries after a failed check.
            checks = {r.image: r for r in snap.update_check_results}
            if any(not checks.get(image) or checks[image].status not in {"updatable", "up_to_date"} or checks[image].last_failure_status for image in images):
                continue
            targets = [image for image in images if snap.update_results.get(image) == "updatable"]
            self.pending.setdefault(host_id, {})[stack.name] = targets
        if self.pending.get(host_id) and host_id not in self.workers:
            self.workers[host_id] = asyncio.create_task(self.run_host(host_id))

    async def run_host(self, host_id: str) -> None:
        try:
            while self.pending.get(host_id) and self.started:
                stack_name = next(iter(self.pending[host_id]))
                targets = self.pending[host_id].pop(stack_name)
                self.active.add((host_id, stack_name))
                try:
                    await self.run_stack(host_id, stack_name, targets)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Automatic update failed for %s/%s", host_id, stack_name)
                finally:
                    self.active.discard((host_id, stack_name))
        finally:
            self.workers.pop(host_id, None)
            self.pending.pop(host_id, None)

    def eligible(self, host_id: str, stack_name: str):
        if not stack_policy(host_id, stack_name).enabled:
            return None
        snap = self.snapshots().get_snapshot(host_id)
        if not snap or not snap.host_config or not snap.host_config.enabled or not snap.host_config.agent_url or snap.status != "online":
            return None
        stack = next((s for s in snap.stacks if s.name == stack_name), None)
        return snap if stack and stack.status == "running" and stack.management_status != "unmanaged" else None

    async def execute(self, conn: AgentClient, stack_name: str) -> tuple[dict, str]:
        queue: asyncio.Queue = asyncio.Queue()
        tail = ""
        task = asyncio.create_task(conn.stack_action(stack_name, "updateStack", log_queue=queue))
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT):
                while True:
                    chunk = await queue.get()
                    if chunk is None:
                        break
                    tail = (tail + chunk)[-12000:]
                result = await task
            return result, scrub_log(tail, conn._token)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def run_stack(self, host_id: str, stack_name: str, targets: list[str]) -> None:
        await self.snapshots().refresh_host_docker(host_id, trigger_initial_update_check=False)
        snap = self.eligible(host_id, stack_name)
        if snap is None or not any(snap.update_results.get(image) == "updatable" for image in targets):
            return
        conn = AgentClient(snap.host_config)
        run_id = None
        try:
            try:
                self_info = await conn.get_self()
            except Exception:
                return  # Identity must be known before unattended updates.
            if not self_info.get("stack_name") or control_stack(snap, stack_name, self_info):
                return
            detail = await conn.get_stack(stack_name)
            if not detail or not (detail.get("stack", {}).get("composeYAML") or "").strip():
                return
            with Session(engine) as session:
                run = AutoUpdateRun(host_id=host_id, stack_name=stack_name)
                session.add(run)
                session.commit()
                session.refresh(run)
                run_id = run.id
            logs = ""
            for attempt in (1, 2):
                with Session(engine) as session:
                    run = session.get(AutoUpdateRun, run_id)
                    run.attempts = attempt
                    session.add(run)
                    session.commit()
                result, tail = await self.execute(conn, stack_name)
                logs = (logs + f"\n--- attempt {attempt} ---\n" + tail)[-6000:]
                stage = result.get("stage", "unknown")
                with Session(engine) as session:
                    run = session.get(AutoUpdateRun, run_id)
                    run.stage = stage
                    session.add(run)
                    session.commit()
                if result.get("error_code") == "stack_busy":
                    self.finish(run_id, "skipped", "Stack 正在执行其他操作，本次跳过。")
                    return
                if result.get("interrupted"):
                    self.finish(run_id, "uncertain", "Agent 连接中断，升级结果未确认。请查看容器状态。", logs)
                    return
                if result.get("success"):
                    if result.get("up_executed") is False:
                        self.finish(run_id, "skipped", "拉取完成时 Stack 已不处于正常运行状态，未执行 up。")
                        return
                    summaries = await self.snapshots().finalize_stack_update(host_id, stack_name, targets, wait_timeout=45.0)
                    current = self.snapshots().get_snapshot(host_id)
                    verified = len(summaries) == len(set(targets)) and all(
                        s.cleared or (current and current.update_results.get(s.image) == "up_to_date") for s in summaries
                    )
                    detail = "\n".join(s.verdict for s in summaries) or "无法取得更新验证结果。"
                    self.finish(run_id, "success" if verified else "failed", detail, logs)
                    return
                if stage != "pull" or attempt == 2:
                    self.finish(run_id, "failed", f"升级失败，阶段：{stage}。{result.get('message', '')}", logs)
                    return
                await asyncio.sleep(PULL_RETRY_DELAY)
                await self.snapshots().refresh_host_docker(host_id, trigger_initial_update_check=False)
                if self.eligible(host_id, stack_name) is None:
                    self.finish(run_id, "skipped", "拉取失败后，自动更新已关闭或 Stack 不再可更新，取消第二次尝试。", logs)
                    return
        except asyncio.CancelledError:
            if run_id is not None:
                self.finish(run_id, "uncertain", "升级执行中断，结果未确认。请查看容器状态。")
            raise
        except Exception:
            if run_id is not None:
                self.finish(run_id, "uncertain", "升级或验证未取得明确结果，已暂停自动更新。")
            else:
                logger.exception("Automatic update preflight failed for %s/%s", host_id, stack_name)
        finally:
            await conn.close()
            try:
                await self.snapshots().refresh_host_docker(host_id, trigger_initial_update_check=False)
            except Exception:
                logger.warning("Could not refresh containers after automatic update")

    def finish(self, run_id: int, status: str, detail: str, logs: str = "") -> None:
        config = notify_settings()
        with Session(engine) as session:
            run = session.get(AutoUpdateRun, run_id)
            if not run or run.status != "running":
                return
            run.status = status
            run.detail = scrub_log(detail)
            run.finished_at = now_utc()
            if status in {"failed", "uncertain"}:
                policy = session.exec(select(StackAutoUpdate).where(StackAutoUpdate.host_id == run.host_id, StackAutoUpdate.stack_name == run.stack_name)).first()
                if policy:
                    policy.enabled = False
                    policy.reason = run.detail
                    session.add(policy)
            session.add(AuditLog(user="system", action="stack.auto_update", host_id=run.host_id, stack_name=run.stack_name,
                                 result="error" if status == "failed" else status, detail=f"attempts={run.attempts}; stage={run.stage}\n{run.detail}\n{logs}"))
            if status != "skipped" and all(config.get(key) for key in NOTIFY_KEYS):
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
        with Session(engine) as session:
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
                with Session(engine) as session:
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
