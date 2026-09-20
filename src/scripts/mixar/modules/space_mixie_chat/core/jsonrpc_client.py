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
from queue import Empty, Full, Queue
from .socket_queue import SocketQueue
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
from .jsonrpc_frames import (
    HANDSHAKE_AUTH_FAILED,
    HANDSHAKE_OK,
    HANDSHAKE_TRANSIENT,
    KIND_CLOSED,
    KIND_MESSAGE,
    read_frame,
    wait_for_handshake,
)

try:
    import websocket
except ImportError:
    websocket = None

logger = get_logger(__name__)


from .socket_connection import SocketConnection
from .socket_dispatch import SocketDispatch
from .socket_requests import SocketRequests


class JSONRPCWebSocketClient(SocketConnection, SocketDispatch, SocketRequests):
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
        on_execution_request: Optional[
            Callable[[str, dict, Optional[str]], Optional[dict]]
        ] = None,
        on_turn_event: Optional[Callable[[str, dict], None]] = None,
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
        self._archive_sync = None
        self.agent_history_supported = False
        self.agent_history_blobs_by_reference = False
        self._on_execution_request = on_execution_request
        self._on_turn_event = on_turn_event
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
        self._pending_deadlines = {}
        self.agent_ws_supported = False
        self._writer = None
        self._reauth_stop = None

        # Outbound message queue
        self._outbound: Queue[str] = SocketQueue()

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
        if self._archive_sync:
            self._archive_sync.stop()

        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

        self._connected = False
        self._handshake_complete = False
        logger.info("JSON-RPC WebSocket client stopped")


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
                        _probe = None
                        try:
                            _probe = read_frame(self._ws)
                        except Exception:
                            pass
                        if _probe is not None and _probe.kind != KIND_CLOSED:
                            # Any frame — a protocol ping included — is
                            # proof the link is alive.
                            self._last_recv_time = time.time()
                            self._liveness_probe_started = None
                            if _probe.kind == KIND_MESSAGE:
                                self._handle_message(json.loads(_probe.text))
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
                self._expire_pending()

                # NOTE: Responses are now pushed directly to _outbound queue by
                # main_thread_executor via queue_response() - no cross-thread polling needed

                # Receive with timeout. read_frame keeps control frames and
                # the close code — recv() returned "" for all of them, so a
                # server ping never counted as traffic and a close never
                # said why.
                try:
                    frame = read_frame(self._ws)
                except websocket.WebSocketTimeoutException:
                    continue
                except websocket.WebSocketConnectionClosedException:
                    logger.info("WebSocket connection closed by server")
                    break

                if frame.kind == KIND_CLOSED:
                    if frame.close_code == WS_CLOSE_AUTH_FAILED:
                        # Recorded, not terminal: the run loop reconnects
                        # and _do_connect refreshes the token first, then
                        # decides whether a retry can help.
                        self._auth.record_failure(None)
                        logger.error(
                            f"Server closed the connection with "
                            f"{WS_CLOSE_AUTH_FAILED} (authentication failed), "
                            f"auth attempt {self._auth.failure_count}"
                        )
                    else:
                        logger.info(
                            f"WebSocket connection closed by server "
                            f"(code {frame.close_code})"
                        )
                    break

                self._last_recv_time = time.time()
                if frame.kind == KIND_MESSAGE:
                    self._handle_message(json.loads(frame.text))

            except Exception as e:
                logger.error(f"Receive error: {e}")
                break

        self._connected = False
        self._handshake_complete = False


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
