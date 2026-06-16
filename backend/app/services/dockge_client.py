"""Dockge Socket.IO client — connection pool with agent proxy protocol.

Maintains one socket.IO connection per configured host. All operations go
through Dockge's agent proxy layer: the browser-style socket emits an
``agent(endpoint, eventName, ...args)`` event, which the Dockge server
forwards to the backend agent socket where the actual Docker operation runs.

Key protocol details (from Dockge source at github.com/louislam/dockge):
  - Login returns ``{ ok: true, token: ... }`` (NOT ``{ status: "ok" }``).
  - After login, the server emits an ``agentList`` event listing available agents.
  - All stack operations go through ``agent(endpoint, event, ...args)``.
  - Agent handlers receive positional args (e.g. ``startStack(stackName, callback)``),
    NOT dict-wrapped arguments.
  - ``requestStackList`` returns data via a separate ``stackList`` event on the
    agent socket, which the proxy forwards back to the client socket.

Whitelisted write actions (only these are accepted):
  - startStack, stopStack, restartStack, updateStack, saveStack, deployStack

Events NOT whitelisted (will be rejected):
  - deleteStack, startService, stopService, etc.
"""

import asyncio
import logging
from collections import deque
from typing import Any, Optional

import socketio

from app.models import HostConfig

logger = logging.getLogger(__name__)

# Actions allowed to be dispatched via the agent proxy
ALLOWED_ACTIONS: set[str] = {
    "startStack",
    "stopStack",
    "restartStack",
    "updateStack",
    "saveStack",
    "deployStack",
    "deleteStack",
}

# Read-only events allowed through the agent proxy (checked in _agent_call)
READ_EVENTS: set[str] = {
    "requestStackList",
    "getStack",
    "serviceStatusList",
}


class DockgeClientError(Exception):
    """Raised on Dockge communication failures."""


class DockgeConnection:
    """A single Socket.IO connection to one Dockge instance."""

    def __init__(self, config: HostConfig, password: str):
        self._host_id = config.host_id
        self._url = config.dockge_url.rstrip("/")
        self._username = config.dockge_username
        self._password = password
        self._endpoint: str = ""
        self._sio: Optional[socketio.AsyncClient] = None
        self._connected: bool = False
        self._lock = asyncio.Lock()
        # Terminal output buffer — retains last 100 lines for any action
        # (moved into per-operation monitor dict for isolation)
        # Active terminal monitors: {terminal_name -> {"future": Future, "queue": Optional[asyncio.Queue], "buffer": deque}}
        self._terminal_monitors: dict[str, dict] = {}
        # Callbacks for agent events: {event_name -> list of callbacks}
        self._agent_listeners: dict[str, list] = {}

    def add_agent_listener(self, event_name: str, callback) -> None:
        self._agent_listeners.setdefault(event_name, []).append(callback)

    def remove_agent_listener(self, event_name: str, callback) -> None:
        if event_name in self._agent_listeners:
            try:
                self._agent_listeners[event_name].remove(callback)
            except ValueError:
                pass

    # ── Lifecycle ─────────────────────────────────────────────────

    async def connect(self) -> None:
        """Establish Socket.IO, authenticate, discover endpoint."""
        if self._connected:
            return
        async with self._lock:
            if self._connected:
                return

            self._sio = socketio.AsyncClient()
            self._sio.on("connect", self._on_connect)
            self._sio.on("disconnect", self._on_disconnect)
            self._sio.on("connect_error", self._on_connect_error)
            # Persistent handler for terminal events and other agent proxied events
            self._sio.on("agent", self._on_agent_event)

            try:
                await asyncio.wait_for(
                    self._sio.connect(
                        self._url,
                        socketio_path="/socket.io",
                        transports=["websocket", "polling"],
                    ),
                    timeout=15.0,
                )
            except Exception as exc:
                self._cleanup()
                raise DockgeClientError(
                    f"Failed to connect to Dockge at {self._url}: {exc}"
                )

            # Authenticate — Dockge returns { ok: true, token: "..." }
            try:
                auth_result = await self._sio.call(
                    "login",
                    {"username": self._username, "password": self._password},
                    timeout=15,
                )
                if not auth_result or not auth_result.get("ok"):
                    reason = (
                        auth_result.get("msg", "unknown")
                        if auth_result
                        else "no response"
                    )
                    self._cleanup()
                    raise DockgeClientError(
                        f"Dockge authentication failed for {self._host_id}: {reason}"
                    )
            except socketio.exceptions.TimeoutError:
                self._cleanup()
                raise DockgeClientError(
                    f"Dockge login timed out for {self._host_id}"
                )

            # v1 connects to each Dockge instance directly.  In Dockge's agent
            # proxy handler, an empty endpoint means "call the local agent".
            # Do not auto-pick a remote agent from agentList here; multi-agent
            # fan-out should be explicit in host config in a later version.
            self._endpoint = ""

            logger.info(
                "Dockge %s: connected, endpoint=%r",
                self._host_id,
                self._endpoint or "<default>",
            )
            self._connected = True

    async def disconnect(self) -> None:
        if self._sio and self._connected:
            await self._sio.disconnect()
        self._cleanup()

    def _cleanup(self) -> None:
        self._connected = False
        self._sio = None
        self._endpoint = ""

    async def is_connected(self) -> bool:
        return self._connected and self._sio is not None and self._sio.connected

    # ── Agent proxy calls ─────────────────────────────────────────

    async def _agent_call(self, event: str, *args: Any, timeout: int = 30) -> Any:
        """Emit via the agent proxy and return the ack response.

        For events that return data through the Socket.IO ack/callback
        mechanism (e.g. ``getStack``, ``startStack``).

        The proxy receives ``agent(endpoint, event, *args)``, forwards
        ``event(*args)`` to the agent socket, and the ack returns the result.
        """
        if not self._connected or not self._sio:
            raise DockgeClientError(f"Dockge {self._host_id}: not connected")

        if event not in READ_EVENTS and event not in ALLOWED_ACTIONS:
            raise DockgeClientError(
                f"Event '{event}' is not allowed. "
                f"Read: {sorted(READ_EVENTS)} | Write: {sorted(ALLOWED_ACTIONS)}"
            )

        payload = (self._endpoint, event) + args

        try:
            result = await self._sio.call("agent", payload, timeout=timeout)

            # --- Unwrap Dockge error-first callback [err, data] ---
            # Dockge agent handlers use Node-style callbacks: callback(err, data).
            # Socket.IO serialises this as a list [err, data].
            # Only unwrap when shape is [err, data] (exactly 2 elements);
            # other list shapes (e.g. a bare list of services) pass through.
            if isinstance(result, list) and len(result) == 2:
                if result[0]:
                    err_desc = result[0]
                    if isinstance(err_desc, dict):
                        err_desc = err_desc.get("message", str(err_desc))
                    raise DockgeClientError(
                        f"Dockge {self._host_id}: {event} returned error: {err_desc}"
                    )
                # Success: take the data element
                result = result[1]

            # Dockge returns ``False`` on agent side error
            if result is False or result is None:
                raise DockgeClientError(
                    f"Dockge {self._host_id}: agent returned false for {event}"
                )
            if isinstance(result, dict) and result.get("ok") is False:
                reason = result.get("msg") or result.get("message") or result
                raise DockgeClientError(
                    f"Dockge {self._host_id}: {event} failed: {reason}"
                )
            return result
        except socketio.exceptions.TimeoutError:
            raise DockgeClientError(
                f"Dockge {self._host_id}: {event} timed out after {timeout}s"
            )
        except DockgeClientError:
            raise
        except Exception as exc:
            raise DockgeClientError(
                f"Dockge {self._host_id}: {event} failed: {exc}"
            )

    async def _agent_emit(self, event: str, *args: Any) -> None:
        """Emit via the agent proxy without waiting for an ack.

        For events whose result comes as a separate event
        (e.g. ``requestStackList`` → ``stackList``).
        """
        if not self._connected or not self._sio:
            raise DockgeClientError(f"Dockge {self._host_id}: not connected")

        if event not in READ_EVENTS:
            raise DockgeClientError(
                f"Event '{event}' is not in read whitelist: {sorted(READ_EVENTS)}"
            )

        payload = (self._endpoint, event) + args
        try:
            await self._sio.emit("agent", payload)
        except Exception as exc:
            raise DockgeClientError(
                f"Dockge {self._host_id}: {event} emit failed: {exc}"
            )

    # ── Public API ─────────────────────────────────────────────────

    def _normalize_stack_list(self, data: Any) -> list[dict]:
        """Normalize Dockge's stackList payload to a list of stack dicts."""
        if not isinstance(data, dict):
            return data if isinstance(data, list) else []

        raw_stacks = (
            data.get("stackList")
            or data.get("stacks")
            or data.get("data")
            or []
        )

        if isinstance(raw_stacks, dict):
            normalized: list[dict] = []
            for stack_name, stack_data in raw_stacks.items():
                if isinstance(stack_data, dict):
                    stack = dict(stack_data)
                    stack.setdefault("name", stack_name)
                    normalized.append(stack)
                else:
                    normalized.append({"name": stack_name, "status": stack_data})
            return normalized

        return raw_stacks if isinstance(raw_stacks, list) else []

    async def list_stacks(self) -> list[dict]:
        """Return all stacks from Dockge.

        Protocol: ``requestStackList(callback)`` — the ack carries no data.
        The result arrives via the ``stackList`` event forwarded from the
        agent socket.
        """
        future: "asyncio.Future[list[dict]]" = (
            asyncio.get_running_loop().create_future()
        )

        def on_stack_list(data: Any) -> None:
            if not future.done():
                future.set_result(self._normalize_stack_list(data))

        self.add_agent_listener("stackList", on_stack_list)

        try:
            # requestStackList itself acknowledges only that refresh was
            # requested; the actual stack data arrives as agent("stackList", ...).
            await self._agent_call("requestStackList", timeout=10)
            return await asyncio.wait_for(future, timeout=10.0)
        except asyncio.TimeoutError:
            raise DockgeClientError(
                f"Dockge {self._host_id}: requestStackList timed out (no agent stackList event)"
            )
        finally:
            self.remove_agent_listener("stackList", on_stack_list)

    async def get_stack(self, name: str) -> Optional[dict]:
        """Get a single stack's details.

        Agent handler: ``getStack(stackName, callback)``.
        """
        return await self._agent_call("getStack", name, timeout=30)

    # ── Terminal-monitored actions ─────────────────────────────────

    async def _run_with_terminal(
        self,
        name: str,
        action: str,
        *args: Any,
        timeout: int = 60,
        log_queue: Optional["asyncio.Queue[str]"] = None,
    ) -> dict:
        """Execute a Dockge action that produces terminal output.

        Registers a terminal monitor for Write/Exit events, runs the
        agent call, and captures output to ``_terminal_buffer`` while
        also forwarding each line to ``log_queue`` when provided.

        Puts ``None`` into ``log_queue`` as a sentinel after the action
        completes (including its 3-second terminal-drain window), so the
        consumer knows all lines have been delivered.
        """
        terminal_name = f"compose-{self._endpoint}-{name}"

        # Per-operation buffer so concurrent actions don't collide
        per_buffer: deque[str] = deque(maxlen=100)
        terminal_done: "asyncio.Future[None]" = (
            asyncio.get_running_loop().create_future()
        )
        monitor_registered = False

        try:
            # Refuse concurrent operations on the same stack — the terminal
            # monitor key would be overwritten, corrupting both operations.
            if terminal_name in self._terminal_monitors:
                raise DockgeClientError(
                    f"Dockge {self._host_id}: another operation is already running for "
                    f"stack '{name}'. Wait for it to finish, then retry."
                )

            self._terminal_monitors[terminal_name] = {
                "future": terminal_done,
                "queue": log_queue,
                "buffer": per_buffer,
            }
            monitor_registered = True

            result = await self._agent_call(action, *args, timeout=timeout)
            # Best-effort drain: wait up to 3s for terminal to finish
            try:
                await asyncio.wait_for(terminal_done, timeout=3)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

            log_tail = "\n".join(per_buffer)

            if isinstance(result, dict):
                return {**result, "log_tail": log_tail}
            return {"result": result, "log_tail": log_tail}
        finally:
            if monitor_registered:
                self._terminal_monitors.pop(terminal_name, None)
            if log_queue is not None:
                await log_queue.put(None)  # EOF sentinel

    async def save_stack(
        self,
        name: str,
        compose_yaml: str,
        compose_env: str,
        *,
        deploy: bool = False,
        is_add: bool = False,
        log_queue: Optional["asyncio.Queue[str]"] = None,
    ) -> dict:
        """Save or deploy an existing stack compose file.

        Dockge agent handlers:
        ``saveStack(name, composeYAML, composeENV, isAdd, callback)``
        ``deployStack(name, composeYAML, composeENV, isAdd, callback)``

        When ``deploy=True``, terminal output is captured via
        ``_run_with_terminal`` (same as ``stack_action``).  Plain saves
        use the simpler ``_agent_call`` since they produce no terminal
        output.
        """
        event = "deployStack" if deploy else "saveStack"
        if deploy:
            return await self._run_with_terminal(
                name,
                event,
                name,
                compose_yaml,
                compose_env,
                is_add,
                timeout=120,
                log_queue=log_queue,
            )
        result = await self._agent_call(
            event,
            name,
            compose_yaml,
            compose_env,
            is_add,
            timeout=60,
        )
        if isinstance(result, dict):
            return result
        return {"result": result}

    async def service_status(self, name: str) -> list[dict]:
        """Get service statuses for a stack.

        Agent handler: ``serviceStatusList(stackName, callback)``.
        """
        result = await self._agent_call("serviceStatusList", name, timeout=30)
        if isinstance(result, dict):
            statuses = (
                result.get("serviceStatusList")
                or result.get("services")
                or result.get("data")
                or []
            )
            if isinstance(statuses, dict):
                return [
                    {
                        "name": service_name,
                        "state": status,
                        "status": str(status),
                    }
                    for service_name, status in statuses.items()
                ]
            return statuses if isinstance(statuses, list) else []
        if isinstance(result, list):
            return result
        return []

    async def stack_action(
        self, name: str, action: str, log_queue: Optional["asyncio.Queue[str]"] = None
    ) -> dict:
        """Execute a whitelisted action on a stack, capturing terminal output.

        For actions that trigger Docker operations (update, deploy, restart),
        the method registers temporary listeners for terminal Write/Exit events
        from Dockge's agent proxy and captures the last 100 lines of output.

        Agent handlers: ``startStack(stackName, callback)``,
        ``stopStack(stackName, callback)``, etc.

        When ``log_queue`` is provided, each terminal output line is also
        pushed to the queue for real-time streaming.  ``None`` is pushed as
        an EOF sentinel after the action completes.

        Returns:
            dict with keys:
              - result: the raw ack from the agent call
              - log_tail: captured terminal output (last 100 lines), or ""
              - success: bool inferred from the agent response
        """
        if action not in ALLOWED_ACTIONS:
            raise DockgeClientError(
                f"Action '{action}' is not allowed. "
                f"Allowed: {sorted(ALLOWED_ACTIONS)}"
            )

        return await self._run_with_terminal(
            name, action, name, timeout=60, log_queue=log_queue
        )

    async def delete_stack(self, name: str) -> dict:
        """Delete a stack directory via Dockge's deleteStack agent event.

        Returns a dict with ``ok`` / ``success`` keys as returned by Dockge.
        """
        result = await self._agent_call("deleteStack", name, timeout=30)
        if isinstance(result, dict):
            return {"success": result.get("ok", True), "message": str(result)}
        return {"success": True, "message": str(result)}

    async def get_logs(self, name: str, tail: int = 200) -> str:
        """Fetch stack logs via Docker proxy container logs.

        v1 uses the docker-socket-proxy container logs endpoint instead of
        Dockge's socket events, since ``stackLogs`` is not in the agent
        handler and per-container logs from the proxy are more reliable.

        The caller should use the Docker proxy client to fetch logs directly
        via ``/containers/<id>/logs``. This method is kept for compatibility
        and returns a placeholder.
        """
        logger.warning(
            "Dockge get_logs is not available in v1; use docker-proxy container logs instead"
        )
        return "[Logs: use container-level log endpoint via docker proxy]"

    # ── Socket.IO event handlers ───────────────────────────────────

    def _on_connect(self) -> None:
        logger.debug("Dockge %s socket connected", self._host_id)

    def _on_disconnect(self) -> None:
        self._connected = False
        logger.warning("Dockge %s socket disconnected", self._host_id)

    def _on_connect_error(self, data: Any) -> None:
        logger.error(
            "Dockge %s socket connect error: %s", self._host_id, data
        )

    # ── Persistent agent event handler ────────────────────────────────

    def _on_agent_event(self, event_name: Any, *args: Any) -> None:
        """Persistent handler for all ``agent`` proxied events.

        Routes terminal Write/Exit events to active monitors (set up by
        ``stack_action``).  Also forwards ``stackList`` events for the
        legacy ``list_stacks`` flow.
        """
        # 1. Dispatch to temporary callbacks
        if event_name in self._agent_listeners:
            for cb in list(self._agent_listeners[event_name]):
                try:
                    cb(*args)
                except Exception as exc:
                    logger.error("Error in agent listener: %s", exc)

        # 2. Main handlers
        if event_name == "terminalWrite":
            tname = args[0] if len(args) > 0 else ""
            data = args[1] if len(args) > 1 else ""
            monitor = self._terminal_monitors.get(tname)
            if monitor and data:
                buf = monitor.get("buffer")
                if buf is not None:
                    buf.append(data)
                q = monitor.get("queue")
                if q is not None:
                    try:
                        q.put_nowait(data)
                    except asyncio.QueueFull:
                        pass

        elif event_name == "terminalExit":
            tname = args[0] if len(args) > 0 else ""
            monitor = self._terminal_monitors.pop(tname, None)
            if monitor:
                future = monitor.get("future")
                if future is not None and not future.done():
                    future.set_result(None)

        elif event_name == "stackList":
            # Real-time cache update when Dockge broadcasts stackList
            try:
                data = args[0] if args else {}
                parsed_stacks = self._normalize_stack_list(data)
                
                # Import snapshot_manager locally to prevent circular imports
                from app.services.snapshot import snapshot_manager
                snapshot_manager.update_host_stacks_realtime(self._host_id, parsed_stacks)
            except Exception as exc:
                logger.error("Error in agent stackList handler: %s", exc)


class DockgePool:
    """Manages multiple DockgeConnection instances, one per host."""

    def __init__(self):
        self._connections: dict[str, DockgeConnection] = {}

    async def get_or_create(
        self, config: HostConfig, password: str
    ) -> DockgeConnection:
        conn = self._connections.get(config.host_id)
        if conn is None:
            conn = DockgeConnection(config, password)
            self._connections[config.host_id] = conn
        if not await conn.is_connected():
            await conn.connect()
        return conn

    async def remove(self, host_id: str) -> None:
        conn = self._connections.pop(host_id, None)
        if conn:
            await conn.disconnect()

    async def disconnect_all(self) -> None:
        for conn in self._connections.values():
            await conn.disconnect()
        self._connections.clear()


# Singleton
dockge_pool = DockgePool()
