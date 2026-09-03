# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
JSON-RPC 2.0 WebSocket client for Blender agent communication.

Handles bidirectional RPC:
- Connection with handshake (system.handshake)
- Keep-alive pings (system.ping)
- Script execution requests from server (blender.execute_script)
- Tool lifecycle notifications (agent.tool_start, agent.tool_end)
"""

import json
from mixar.config.logging_config import get_logger
import threading
import time
from queue import Empty, Queue
from typing import Any, Callable, Optional

from ..constants import (
    DISCONNECT_REASON_AUTH_FAILED,
    JSONRPCErrorCode,
    JSONRPCMethod,
    WS_CLOSE_AUTH_FAILED,
    WS_LIVENESS_PROBE_GRACE,
    WS_LIVENESS_TIMEOUT,
    WS_UI_STALE_THRESHOLD,
)
from .jsonrpc_auth import AuthBackoffManager

try:
    import websocket
except ImportError:
    websocket = None

logger = get_logger(__name__)


class JSONRPCWebSocketClient:
    """
    JSON-RPC 2.0 WebSocket client for /api/agent/ws/{connection_id}.

    Handles bidirectional RPC communication:
    - Server sends requests for script execution
    - Client responds with execution results
    - Server sends notifications for tool lifecycle
    """

    def __init__(
        self,
        host: str,
        connection_id: str,
        token_getter: Optional[Callable[[], Optional[str]]] = None,
        blender_version: str = "5.0.0",
        addon_version: str = "1.0.0",
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
        ping_interval: float = 15.0,
        on_script_execute: Optional[
            Callable[[str, Optional[str], str, str, Optional[dict]], Optional[dict]]
        ] = None,
        on_tool_start: Optional[Callable[[dict], None]] = None,
        on_tool_executing: Optional[Callable[[dict], None]] = None,
        on_tool_end: Optional[Callable[[dict], None]] = None,
        on_connected: Optional[Callable[[], None]] = None,
        on_disconnected: Optional[Callable[[str], None]] = None,
        on_notification: Optional[Callable[[dict], None]] = None,
        on_job_update: Optional[Callable[[dict], None]] = None,
        on_sandbox_control: Optional[Callable[[dict], dict]] = None,
        on_llm_request: Optional[
            Callable[[dict, Optional[str]], Optional[dict]]
        ] = None,
        on_addon_project_request: Optional[
            Callable[[str, dict, Optional[str]], Optional[dict]]
        ] = None,
        on_ui_request: Optional[
            Callable[[str, dict, Optional[str]], Optional[dict]]
        ] = None,
        role: Optional[str] = None,
        parent_instance_id: Optional[str] = None,
        device_id: Optional[str] = None,
    ):
        self._host = host
        self._connection_id = connection_id
        self._token_getter = token_getter
        self._blender_version = blender_version
        self._addon_version = addon_version
        self._device_id = device_id
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._ping_interval = ping_interval

        # Callbacks
        self._on_script_execute = on_script_execute
        self._on_tool_start = on_tool_start
        self._on_tool_executing = on_tool_executing
        self._on_tool_end = on_tool_end
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_notification = on_notification
        self._on_job_update = on_job_update
        self._on_sandbox_control = on_sandbox_control
        self._on_llm_request = on_llm_request
        self._on_addon_project_request = on_addon_project_request
        self._on_ui_request = on_ui_request
        self._role = role
        self._parent_instance_id = parent_instance_id

        # State
        self._ws: Optional["websocket.WebSocket"] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._connected = False
        self._handshake_complete = False
        self._current_delay = reconnect_delay
        self._last_ping_time = 0.0
        self._last_recv_time = 0.0
        # Liveness grace probe: set to the probe start time when the liveness
        # window expires, cleared when traffic arrives (see _receive_loop).
        self._liveness_probe_started: Optional[float] = None

        # Auth failure backoff
        self._auth = AuthBackoffManager()

        # Request ID counter
        self._request_id = 0
        self._request_id_lock = threading.Lock()

        # Pending request callbacks (request_id -> on_result callable)
        self._pending_callbacks: dict[str, Callable] = {}
        self._pending_lock = threading.Lock()

        # Outbound message queue
        self._outbound: Queue[str] = Queue()

    @property
    def ws_url(self) -> str:
        """Build WebSocket URL."""
        ws_host = self._host.replace("https://", "wss://").replace("http://", "ws://")
        return f"{ws_host}/api/agent/ws/{self._connection_id}"

    @property
    def is_connected(self) -> bool:
        """Check if connected and handshake completed."""
        return self._connected and self._handshake_complete

    @property
    def is_transport_live(self) -> bool:
        """Connected AND recently receiving traffic — the fast liveness signal.

        ``is_connected`` stays True on a silently dead TCP connection (wifi
        off, sleep/resume, NAT rebind) until the WS_LIVENESS_TIMEOUT watchdog
        tears it down: sends keep "succeeding" into the kernel buffer, so
        only recv starvation reveals the death. Status surfaces must not
        show Connected/Idle for that whole window, so this trips much
        earlier, on WS_UI_STALE_THRESHOLD of recv silence (a healthy
        connection carries at least a pong per ~15s ping).

        Display-only: send-gating must keep using ``is_connected`` — a
        stale-but-recoverable socket can still deliver queued work, and a
        false "down" there drops it.
        """
        if not (self._connected and self._handshake_complete):
            return False
        return (time.time() - self._last_recv_time) <= WS_UI_STALE_THRESHOLD

    @property
    def connection_id(self) -> str:
        """Get the connection ID."""
        return self._connection_id

    def connect(self) -> bool:
        """
        Start background thread and establish connection.

        Returns:
            True if thread started successfully
        """
        if websocket is None:
            logger.error("websocket-client library not available")
            return False

        if self._running.is_set():
            logger.debug("JSON-RPC client already running")
            return True

        self._running.set()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.name = "MixarJSONRPCWS"
        self._thread.start()

        logger.info(f"JSON-RPC WebSocket client started for {self.ws_url}")
        return True

    def disconnect(self) -> None:
        """Close connection and stop background thread."""
        self._running.clear()

        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

        self._connected = False
        self._handshake_complete = False
        logger.info("JSON-RPC WebSocket client stopped")

    def _run_loop(self) -> None:
        """Main loop running in background thread."""
        while self._running.is_set():
            try:
                if self._do_connect():
                    self._receive_loop()
            except Exception as e:
                logger.error(f"JSON-RPC run loop error: {e}")

            # Handle disconnection
            self._connected = False
            self._handshake_complete = False

            # Clear pending callbacks to prevent stale responses from leaking
            with self._pending_lock:
                self._pending_callbacks.clear()

            # Drain stale outbound messages to prevent them leaking into a new session
            drained = 0
            while not self._outbound.empty():
                try:
                    self._outbound.get_nowait()
                    drained += 1
                except Empty:
                    break
            if drained:
                logger.info(f"Cleared {drained} stale outbound messages on disconnect")

            if self._on_disconnected:
                try:
                    self._on_disconnected("Connection lost")
                except Exception as e:
                    logger.error(f"Error in on_disconnected callback: {e}")

            if self._running.is_set():
                logger.info(f"Reconnecting in {self._current_delay:.1f}s...")
                time.sleep(self._current_delay)
                self._current_delay = min(
                    self._current_delay * 2, self._max_reconnect_delay
                )

    def _do_connect(self) -> bool:
        """Establish connection and perform handshake."""
        # Stop if max auth failures reached
        if self._auth.max_failures_reached:
            logger.error("Max auth failures reached - stopping reconnection")
            if self._on_disconnected:
                self._on_disconnected(DISCONNECT_REASON_AUTH_FAILED)
            self._running.clear()
            return False

        try:
            logger.info(f"Connecting to {self.ws_url}")

            # Get auth token - attempt refresh if previous attempt failed
            token = self._token_getter() if self._token_getter else None
            if self._auth.failure_count > 0 and token:
                refreshed = self._try_refresh_token()
                if refreshed:
                    token = refreshed
            headers = [f"Authorization: Bearer {token}"] if token else []
            # Extend the "Share Usage Data" toggle to the backend's
            # server-side ws-connect/agent telemetry. Guarded: an
            # analytics failure must never block the connection.
            try:
                from mixar.modules.common.analytics.preferences import (
                    is_enabled as _telemetry_enabled,
                )
                headers.append(
                    f"x-telemetry-consent: {'1' if _telemetry_enabled() else '0'}"
                )
            except Exception:
                pass

            if not token:
                logger.warning("No auth token available - connection may fail")

            self._ws = websocket.create_connection(
                self.ws_url, timeout=10, header=headers
            )
            self._connected = True

            # Perform handshake. The backoff delay and auth-failure counter
            # are only reset AFTER the handshake succeeds: resetting them on
            # bare TCP/WS connect meant a server that accepts the upgrade but
            # rejects the token was retried in a tight ~1s loop forever
            # (failure count wiped each cycle, so max_failures never tripped).
            if not self._perform_handshake():
                # Handshake failure right after connect likely means auth rejection
                # (server accepted WS upgrade but closed on token validation)
                self._auth.record_failure(token)
                logger.warning(
                    f"Handshake failed (likely auth), attempt {self._auth.failure_count}/{self._auth._max_failures}"
                )
                self._ws.close()
                self._connected = False
                return False

            self._handshake_complete = True
            self._current_delay = self._reconnect_delay
            self._auth.reset()
            self._last_ping_time = time.time()
            self._last_recv_time = time.time()
            self._liveness_probe_started = None

            if self._on_connected:
                try:
                    self._on_connected()
                except Exception as e:
                    logger.error(f"Error in on_connected callback: {e}")

            logger.info("JSON-RPC WebSocket connected and authenticated")
            return True

        except websocket.WebSocketException as e:
            # Check for auth failure close code
            close_code = getattr(e, 'status_code', None)
            if close_code == WS_CLOSE_AUTH_FAILED:
                self._auth.record_failure(token)
                logger.error(
                    f"WebSocket auth failed (code {close_code}), "
                    f"attempt {self._auth.failure_count}/{self._auth._max_failures}: {e}"
                )
                self._connected = False
                return False
            logger.warning(f"Connection failed: {e}")
            self._connected = False
            return False
        except Exception as e:
            logger.warning(f"Connection failed: {e}")
            self._connected = False
            return False

    def _try_refresh_token(self) -> Optional[str]:
        """Attempt to refresh the access token. Returns new token or None."""
        try:
            from ...auth.core.auth import refresh_access_token, get_access_token
            result = refresh_access_token()
            if result.get("success"):
                logger.info("Token refreshed successfully before reconnect")
                return get_access_token()
            else:
                logger.warning(f"Token refresh failed: {result.get('message')}")
        except Exception as e:
            logger.warning(f"Token refresh error: {e}")
        return None

    def _perform_handshake(self) -> bool:
        """Send handshake request and wait for response."""
        from ...addon_project.constants import CAPABILITY as ADDON_PROJECT_CAPABILITY
        from ...agent_ui.constants import CAPABILITY as UI_CONTROL_CAPABILITY

        request_id = f"handshake_{self._next_request_id()}"

        params = {
            "blender_version": self._blender_version,
            "addon_version": self._addon_version,
            # "local_llm": this client can execute llm.request relays against
            # a local model server (modules/local_models) — the backend only
            # sends them when the user's BYOK provider is "local".
            "capabilities": [
                "script_execution",
                "notifications",
                "local_llm",
                # Client answers blender.liveness on the WS thread; the
                # backend only probes instances that advertise it (older
                # clients would silently never reply).
                "liveness",
                ADDON_PROJECT_CAPABILITY,
                # "ui_control_v1": the backend agent may operate this app's
                # real UI through ui.* requests (modules/agent_ui).
                UI_CONTROL_CAPABILITY,
            ],
        }
        # Anti-abuse device signal (one trial per machine); best-effort
        if self._device_id:
            params["device_id"] = self._device_id
        # A headless sandbox identifies itself so the backend can route a
        # create_model sub-build to it (parent_instance_id -> this connection).
        if self._role:
            params["role"] = self._role
            params["parent_instance_id"] = self._parent_instance_id
        handshake = {
            "jsonrpc": "2.0",
            "method": JSONRPCMethod.SYSTEM_HANDSHAKE,
            "id": request_id,
            "params": params,
        }

        self._ws.send(json.dumps(handshake))

        # Wait for response with timeout
        self._ws.settimeout(10)
        try:
            data = self._ws.recv()
            if not data:
                logger.warning("Handshake received empty response (connection closing)")
                return False
            response = json.loads(data)

            if response.get("result", {}).get("success"):
                logger.info("Handshake successful")
                return True
            else:
                error = response.get("error", {})
                logger.error(f"Handshake failed: {error.get('message', 'Unknown')}")
                return False

        except Exception as e:
            logger.error(f"Handshake error: {e}")
            return False

    def _receive_loop(self) -> None:
        """Receive and process incoming messages."""
        while self._running.is_set() and self._connected:
            try:
                # Liveness: a healthy connection receives at least the pong
                # to our ~15s pings. A silently dead TCP connection (network
                # drop, sleep/resume) times out recv forever while sends
                # still "succeed" — without this check the client never
                # notices and never reconnects.
                if time.time() - self._last_recv_time > WS_LIVENESS_TIMEOUT:
                    # Grace probe before declaring death. This thread starves
                    # whenever Blender's main thread holds the GIL through a
                    # long script/render — on wake, _last_recv_time is stale
                    # even though the server kept the connection healthy the
                    # whole time (uat3 2026-07-21: three healthy connections
                    # torn down here after GIL-blocked stretches). Send a ping
                    # and give the server one short window to answer; only a
                    # probe that ALSO gets nothing means the link is dead.
                    if self._liveness_probe_started is None:
                        self._liveness_probe_started = time.time()
                        logger.info(
                            f"No WebSocket traffic for {WS_LIVENESS_TIMEOUT:.0f}s "
                            f"— probing liveness before teardown"
                        )
                        self._send_ping()
                    elif (
                        time.time() - self._liveness_probe_started
                        > WS_LIVENESS_PROBE_GRACE
                    ):
                        # The probe's answer may already sit in the socket
                        # buffer if this thread was starved again during the
                        # grace window — drain once more before the verdict.
                        _probe_data = None
                        try:
                            self._ws.settimeout(1.0)
                            _probe_data = self._ws.recv()
                        except Exception:
                            pass
                        if _probe_data:
                            self._last_recv_time = time.time()
                            self._liveness_probe_started = None
                            self._handle_message(json.loads(_probe_data))
                            continue
                        logger.warning(
                            f"No WebSocket traffic for "
                            f"{time.time() - self._last_recv_time:.0f}s and the "
                            f"liveness probe got no answer in "
                            f"{WS_LIVENESS_PROBE_GRACE:.0f}s — treating "
                            f"connection as dead"
                        )
                        try:
                            self._ws.close()
                        except Exception:
                            pass
                        break
                else:
                    self._liveness_probe_started = None

                # Send ping if needed
                if time.time() - self._last_ping_time > self._ping_interval:
                    self._send_ping()

                # Process outbound queue
                self._process_outbound()

                # NOTE: Responses are now pushed directly to _outbound queue by
                # main_thread_executor via queue_response() - no cross-thread polling needed

                # Receive with timeout
                self._ws.settimeout(0.5)
                try:
                    data = self._ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except websocket.WebSocketConnectionClosedException as e:
                    # Check for auth failure close code
                    close_code = getattr(e, 'status_code', None)
                    if close_code == WS_CLOSE_AUTH_FAILED:
                        self._auth.record_failure(None)
                        logger.error(
                            f"WebSocket auth failed during receive (code {close_code}), "
                            f"attempt {self._auth.failure_count}"
                        )
                        if self._on_disconnected:
                            self._on_disconnected(DISCONNECT_REASON_AUTH_FAILED)
                        if self._auth.max_failures_reached:
                            self._running.clear()
                        return
                    logger.info("WebSocket connection closed by server")
                    break

                if data:
                    self._last_recv_time = time.time()
                    self._handle_message(json.loads(data))

            except Exception as e:
                logger.error(f"Receive error: {e}")
                break

        self._connected = False
        self._handshake_complete = False

    def send_request(
        self,
        method: str,
        params: dict,
        on_result: Optional[Callable[[Any], None]] = None,
    ) -> str:
        """Send a JSON-RPC request and optionally register a response callback.

        Args:
            method: JSON-RPC method name
            params: Method parameters
            on_result: Callback invoked with the result (or error dict) when
                       the server responds. Called on the WS thread.

        Returns:
            The request ID string.
        """
        request_id = f"req_{self._next_request_id()}"
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "id": request_id,
            "params": params,
        }
        if on_result is not None:
            with self._pending_lock:
                self._pending_callbacks[request_id] = on_result
        self._outbound.put(json.dumps(request))
        logger.debug(f"Queued request {request_id} ({method})")
        return request_id

    def send_notification(self, method: str, params: dict) -> bool:
        """Queue a JSON-RPC notification (no id, no response expected).

        Fire-and-forget client -> server reporting (e.g. the final-render
        outcome). Thread-safe: the payload only enters the outbound queue,
        which the WS thread drains. Returns False immediately when the client
        is not connected — the caller decides whether that matters (reporting
        is best-effort; the server's pending marker expires instead).
        """
        if not self._connected:
            return False
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._outbound.put(json.dumps(notification))
        logger.debug(f"Queued notification ({method})")
        return True

    def _handle_message(self, msg: dict) -> None:
        """Handle incoming JSON-RPC message."""
        # Check if it's a response (to our ping, handshake, or send_request)
        if "result" in msg or "error" in msg:
            msg_id = msg.get("id")
            if msg_id:
                with self._pending_lock:
                    cb = self._pending_callbacks.pop(msg_id, None)
                if cb is not None:
                    try:
                        payload = msg.get("result") if "result" in msg else msg.get("error")
                        cb(payload)
                    except Exception as e:
                        logger.error(f"Error in response callback for {msg_id}: {e}")
            return

        # It's a request or notification
        method = msg.get("method")
        params = msg.get("params", {})
        request_id = msg.get("id")  # None for notifications

        if method == JSONRPCMethod.BLENDER_EXECUTE_SCRIPT:
            self._handle_execute_script(params, request_id)

        elif method == JSONRPCMethod.BLENDER_LIVENESS:
            self._handle_liveness(request_id)

        elif method == JSONRPCMethod.AGENT_SANDBOX_CONTROL:
            self._handle_sandbox_control(params, request_id)

        elif method == JSONRPCMethod.LLM_REQUEST:
            self._handle_llm_request(params, request_id)

        elif isinstance(method, str) and method.startswith(JSONRPCMethod.ADDON_PROJECT_PREFIX):
            self._handle_addon_project_request(method, params, request_id)

        elif isinstance(method, str) and method.startswith(JSONRPCMethod.UI_CONTROL_PREFIX):
            self._handle_ui_request(method, params, request_id)

        elif method == JSONRPCMethod.AGENT_TOOL_START:
            if self._on_tool_start:
                try:
                    self._on_tool_start(params)
                except Exception as e:
                    logger.error(f"Error in on_tool_start callback: {e}")

        elif method == JSONRPCMethod.AGENT_TOOL_EXECUTING:
            if self._on_tool_executing:
                try:
                    self._on_tool_executing(params)
                except Exception as e:
                    logger.error(f"Error in on_tool_executing callback: {e}")

        elif method == JSONRPCMethod.AGENT_TOOL_END:
            if self._on_tool_end:
                try:
                    self._on_tool_end(params)
                except Exception as e:
                    logger.error(f"Error in on_tool_end callback: {e}")

        elif method == JSONRPCMethod.NOTIFICATIONS_PUSH:
            if self._on_notification:
                try:
                    self._on_notification(params)
                except Exception as e:
                    logger.error(f"Error in on_notification callback: {e}")

        elif method == JSONRPCMethod.JOB_UPDATE:
            if self._on_job_update:
                try:
                    self._on_job_update(params)
                except Exception as e:
                    logger.error(f"Error in on_job_update callback: {e}")

        else:
            logger.warning(f"Unknown JSON-RPC method: {method}")

    def _handle_addon_project_request(
        self, method: str, params: dict, request_id: Optional[str]
    ) -> None:
        """Handle a capability-scoped local project operation.

        The callback normally defers disk work to a worker and replies through
        ``queue_response``. A synchronous result remains useful in tests and
        for immediate refusals.
        """
        result = None
        if self._on_addon_project_request:
            try:
                result = self._on_addon_project_request(method, params, request_id)
                if result is None:
                    return
            except Exception as exc:
                logger.error("add-on project request failed: %s", exc)
                result = {
                    "success": False,
                    "error": {
                        "code": "handler_error",
                        "message": "The local add-on project handler failed",
                    },
                }
        else:
            result = {
                "success": False,
                "error": {
                    "code": "capability_unavailable",
                    "message": "Add-on Project Mode is unavailable in this client",
                },
            }
        if request_id and result is not None:
            self.queue_response(request_id, result)

    def _handle_ui_request(
        self, method: str, params: dict, request_id: Optional[str]
    ) -> None:
        """Handle a capability-scoped agent UI control request (``ui.*``).

        The callback schedules main-thread work and replies through
        ``queue_response``; a synchronous dict is an immediate refusal.
        """
        result = None
        if self._on_ui_request:
            try:
                result = self._on_ui_request(method, params, request_id)
                if result is None:
                    return
            except Exception as exc:
                logger.error("agent UI request failed: %s", exc)
                result = {
                    "success": False,
                    "error": {
                        "code": "internal",
                        "message": "The UI control handler failed in the client",
                    },
                }
        else:
            result = {
                "success": False,
                "error": {
                    "code": "not_enabled",
                    "message": "Agent UI control is unavailable in this client",
                },
            }
        if request_id and result is not None:
            self.queue_response(request_id, result)

    def _handle_liveness(self, request_id: Optional[str]) -> None:
        """Answer blender.liveness WITHOUT touching bpy or the main thread.

        The backend sends this before counting a script timeout toward its
        "Blender stopped responding" breaker. A legitimately long script
        holds the main thread (and mostly the GIL) while Blender is perfectly
        alive; this handler runs entirely on the WebSocket receive thread and
        answers whenever the GIL is acquirable at all — answering AT ALL is
        the proof of life the backend needs. Never import bpy-dependent
        modules on this path beyond the lock-guarded in-flight snapshot.
        """
        if request_id is None:
            return
        try:
            from .main_thread_executor import get_inflight_script, has_pending_requests

            inflight = get_inflight_script()
            self.queue_response(request_id, {
                "alive": True,
                "script_in_flight": inflight,
                "queue_pending": has_pending_requests(),
                "handshake_complete": self._handshake_complete,
            })
        except Exception as e:  # never let a probe raise inside the recv loop
            logger.error(f"Error in liveness handler: {e}")

    def _handle_execute_script(self, params: dict, request_id: Optional[str]) -> None:
        """Handle script execution request.

        The callback may return None to indicate async handling - in that case,
        the response will be sent later via the execution response queue.
        """
        script = params.get("script", "")
        tool_name = params.get("tool_name", "unknown")
        session_id = params.get("session_id", "")
        agent_ctx = params.get("agent_ctx")

        if self._on_script_execute:
            try:
                result = self._on_script_execute(
                    script, request_id, tool_name, session_id, agent_ctx
                )
                if result is None:
                    # Async handling - response will be sent via response queue
                    return
            except Exception as e:
                logger.error(f"Script execution error: {e}")
                result = {
                    "success": False,
                    "error": str(e),
                }
        else:
            result = {
                "success": False,
                "error": "No script execution handler registered",
            }

        # Send response if it's a request (has id) and we have a result
        if request_id and result is not None:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
            self._outbound.put(json.dumps(response))

    def _handle_llm_request(self, params: dict, request_id: Optional[str]) -> None:
        """Handle a server-initiated llm.request (local model relay).

        Mirrors ``_handle_execute_script``'s deferred contract: the callback
        returns ``None`` to indicate async handling — it spawns its own worker
        thread and replies later via ``queue_response(request_id, result)``.
        The WS receive thread must NEVER run the (up to ~minutes-long) local
        HTTP call itself; a synchronous return here is only used for
        immediate refusals.

        Failure results reuse the shape the relay layer defines —
        ``{"error": {"code", "message"}}`` — sent through the same
        ``queue_response`` path as every other response (matching how
        execute_script failures travel as result payloads).
        """
        result: Optional[dict] = None
        if self._on_llm_request:
            try:
                result = self._on_llm_request(params, request_id)
                if result is None:
                    # Deferred — the handler responds via queue_response later.
                    return
            except Exception as e:
                logger.error(f"llm.request handler error: {e}")
                result = {
                    "error": {"code": "relay_internal", "message": str(e)},
                }
        else:
            result = {
                "error": {
                    "code": "relay_unavailable",
                    "message": "No local LLM relay handler registered",
                },
            }
        if request_id and result is not None:
            self.queue_response(request_id, result)

    def _handle_sandbox_control(self, params: dict, request_id: Optional[str]) -> None:
        """Handle a server-initiated agent.sandbox_control request (parent side).

        Delegates to the on_sandbox_control callback (the sandbox supervisor) and
        replies with its result so the backend can confirm spawn/shutdown.
        """
        result = {"success": False, "error": "no sandbox control handler"}
        if self._on_sandbox_control:
            try:
                result = self._on_sandbox_control(params) or {"success": True}
            except Exception as e:
                logger.error(f"sandbox_control handler error: {e}")
                result = {"success": False, "error": str(e)}
        if request_id:
            self._outbound.put(json.dumps({
                "jsonrpc": "2.0", "id": request_id, "result": result,
            }))

    def _send_ping(self) -> None:
        """Send ping request."""
        request_id = f"ping_{self._next_request_id()}"
        ping = {
            "jsonrpc": "2.0",
            "method": JSONRPCMethod.SYSTEM_PING,
            "id": request_id,
        }
        self._outbound.put(json.dumps(ping))
        self._last_ping_time = time.time()
        logger.debug("Sent ping")

    def _process_outbound(self) -> None:
        """Send queued outbound messages.

        Called from _receive_loop on the same thread/socket. Uses a 10s
        send timeout to handle large payloads (base64 JPEG screenshots)
        while keeping the receive loop responsive. The timeout is saved
        and restored so recv() always gets its own 0.5s timeout back.
        """
        while True:
            try:
                data = self._outbound.get_nowait()
                if self._ws and self._connected:
                    prev_timeout = self._ws.gettimeout()
                    try:
                        self._ws.settimeout(10)
                        self._ws.send(data)
                    finally:
                        self._ws.settimeout(prev_timeout)
            except Empty:
                break
            except Exception as e:
                logger.error(f"Error sending outbound message: {e}")
                break

    def queue_response(self, request_id: str, result: dict) -> None:
        """Queue a JSON-RPC response for sending (thread-safe)."""
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        self._outbound.put(json.dumps(response))
        logger.debug(f"Response queued for request {request_id}")

    def _next_request_id(self) -> int:
        """Get next request ID (thread-safe)."""
        with self._request_id_lock:
            self._request_id += 1
            return self._request_id


# Global client instance
_jsonrpc_client: Optional[JSONRPCWebSocketClient] = None


def get_jsonrpc_client() -> Optional[JSONRPCWebSocketClient]:
    """Get the global JSON-RPC WebSocket client instance."""
    return _jsonrpc_client


def create_jsonrpc_client(
    host: str,
    connection_id: str,
    **kwargs,
) -> JSONRPCWebSocketClient:
    """
    Create and set the global JSON-RPC WebSocket client.

    Args:
        host: Server host URL (http/https)
        connection_id: Client connection ID
        **kwargs: Additional arguments for JSONRPCWebSocketClient

    Returns:
        Created JSONRPCWebSocketClient instance
    """
    global _jsonrpc_client

    if _jsonrpc_client is not None:
        _jsonrpc_client.disconnect()

    # Attach the anti-abuse device id unless the caller supplied one.
    # Lazy import + fail-open: the device id must never block connecting.
    if "device_id" not in kwargs:
        try:
            from ...auth.core.device import get_device_id

            kwargs["device_id"] = get_device_id()
        except Exception:
            kwargs["device_id"] = None

    _jsonrpc_client = JSONRPCWebSocketClient(host, connection_id, **kwargs)
    return _jsonrpc_client


def cleanup_jsonrpc_client() -> None:
    """Clean up the global JSON-RPC WebSocket client."""
    global _jsonrpc_client

    if _jsonrpc_client is not None:
        _jsonrpc_client.disconnect()
        _jsonrpc_client = None
