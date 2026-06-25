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

from ..constants import JSONRPCErrorCode, JSONRPCMethod, WS_CLOSE_AUTH_FAILED
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
        on_script_execute: Optional[Callable[[str, Optional[str]], dict]] = None,
        on_tool_start: Optional[Callable[[dict], None]] = None,
        on_tool_executing: Optional[Callable[[dict], None]] = None,
        on_tool_end: Optional[Callable[[dict], None]] = None,
        on_connected: Optional[Callable[[], None]] = None,
        on_disconnected: Optional[Callable[[str], None]] = None,
        on_notification: Optional[Callable[[dict], None]] = None,
        on_sandbox_control: Optional[Callable[[dict], dict]] = None,
        role: Optional[str] = None,
        parent_instance_id: Optional[str] = None,
    ):
        self._host = host
        self._connection_id = connection_id
        self._token_getter = token_getter
        self._blender_version = blender_version
        self._addon_version = addon_version
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
        self._on_sandbox_control = on_sandbox_control
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
                self._on_disconnected("Authentication failed - please login again")
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

            if not token:
                logger.warning("No auth token available - connection may fail")

            self._ws = websocket.create_connection(
                self.ws_url, timeout=10, header=headers
            )
            self._connected = True
            self._current_delay = self._reconnect_delay
            self._auth.reset()

            # Perform handshake
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
            self._last_ping_time = time.time()

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
        request_id = f"handshake_{self._next_request_id()}"

        params = {
            "blender_version": self._blender_version,
            "addon_version": self._addon_version,
            "capabilities": ["script_execution", "notifications"],
        }
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
                            self._on_disconnected("Authentication failed - please login again")
                        if self._auth.max_failures_reached:
                            self._running.clear()
                        return
                    logger.info("WebSocket connection closed by server")
                    break

                if data:
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

        elif method == JSONRPCMethod.AGENT_SANDBOX_CONTROL:
            self._handle_sandbox_control(params, request_id)

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

        else:
            logger.warning(f"Unknown JSON-RPC method: {method}")

    def _handle_execute_script(self, params: dict, request_id: Optional[str]) -> None:
        """Handle script execution request.

        The callback may return None to indicate async handling - in that case,
        the response will be sent later via the execution response queue.
        """
        script = params.get("script", "")
        tool_name = params.get("tool_name", "unknown")
        session_id = params.get("session_id", "")

        if self._on_script_execute:
            try:
                result = self._on_script_execute(script, request_id, tool_name, session_id)
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

    _jsonrpc_client = JSONRPCWebSocketClient(host, connection_id, **kwargs)
    return _jsonrpc_client


def cleanup_jsonrpc_client() -> None:
    """Clean up the global JSON-RPC WebSocket client."""
    global _jsonrpc_client

    if _jsonrpc_client is not None:
        _jsonrpc_client.disconnect()
        _jsonrpc_client = None
