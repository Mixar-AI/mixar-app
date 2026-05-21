# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
WebSocket client for background thread communication.

Manages WebSocket connection in a daemon thread, handling
message sending/receiving and automatic reconnection.
"""

import threading
import time
from typing import Callable, Optional

from .message_queue import get_message_queues
from .protocol import (
    Message,
    MessageType,
    create_ping_message,
    deserialize_message,
)

# Try to import websocket-client library
try:
    import websocket
except ImportError:
    websocket = None


class WebSocketClient:
    """
    Background-threaded WebSocket client.

    Features:
    - Runs in daemon thread (auto-terminates with Blender)
    - Pushes received messages to inbound queue
    - Sends messages from outbound queue
    - Automatic reconnection with exponential backoff
    """

    def __init__(
        self,
        url: str,
        instance_id: str,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
        ping_interval: float = 15.0,
        type_mapping: Optional[dict[str, MessageType]] = None,
        on_log: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Initialize WebSocket client.

        Args:
            url: WebSocket URL (e.g., ws://localhost:8000/agent/ws)
            instance_id: Unique identifier for this client instance
            reconnect_delay: Initial reconnection delay in seconds
            max_reconnect_delay: Maximum reconnection delay
            ping_interval: Interval between ping messages
            type_mapping: Custom message type mapping for deserialization
            on_log: Optional callback for logging (level, message)
        """
        self._url = url
        self._instance_id = instance_id
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._ping_interval = ping_interval
        self._type_mapping = type_mapping
        self._on_log = on_log

        self._queues = get_message_queues()
        self._ws: Optional["websocket.WebSocket"] = None
        self._thread: Optional[threading.Thread] = None
        self._send_thread: Optional[threading.Thread] = None
        self._running = threading.Event()  # Thread-safe running flag
        self._connected = False
        self._current_delay = reconnect_delay

        self._last_ping_time = 0.0
        self._lock = threading.Lock()

    def _log(self, level: str, message: str) -> None:
        """Log a message using the callback if provided."""
        if self._on_log:
            self._on_log(level, message)

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected."""
        return self._connected

    @property
    def is_running(self) -> bool:
        """Check if client thread is running."""
        return self._running.is_set()

    @property
    def instance_id(self) -> str:
        """Get the instance ID."""
        return self._instance_id

    def connect(self) -> bool:
        """
        Start background thread and establish connection.

        Returns:
            True if thread started successfully
        """
        if websocket is None:
            self._log("error", "websocket-client library not available")
            return False

        if self._running.is_set():
            self._log("debug", "WebSocket client already running")
            return True

        self._running.set()

        # Start main receive thread
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.name = "MixarWebSocket"
        self._thread.start()

        self._log("info", f"WebSocket client started for {self._url}")
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
        self._log("info", "WebSocket client stopped")

    def send(self, message: Message) -> None:
        """
        Queue a message to be sent to the server.

        Args:
            message: Message to send
        """
        self._queues.send(message)

    def _run_loop(self) -> None:
        """Main loop running in background thread."""
        while self._running.is_set():
            try:
                # Close any leftover socket from a previous iteration before
                # we overwrite it in _connect_with_retry. Without this the
                # prior `websocket.WebSocket` (and its TCP/TLS resources) is
                # only reachable through the GC, so an unclean disconnect
                # (broken pipe, half-open socket) leaks a connection per
                # reconnect cycle.
                if self._ws is not None:
                    try:
                        self._ws.close()
                    except Exception:
                        pass
                    self._ws = None

                # Join the previous send thread so its closure (and the
                # outbound queue handle it pinned) is released before we
                # spawn a fresh one.
                prev_send = self._send_thread
                if prev_send is not None and prev_send.is_alive():
                    prev_send.join(timeout=1.0)
                self._send_thread = None

                # Attempt connection
                if not self._connect_with_retry():
                    continue

                # Start send thread
                self._send_thread = threading.Thread(
                    target=self._send_loop, daemon=True
                )
                self._send_thread.name = "MixarWebSocketSend"
                self._send_thread.start()

                # Run receive loop
                self._receive_loop()

            except Exception as e:
                self._log("error", f"WebSocket run loop error: {e}")
                self._handle_disconnect(str(e))

            # Wait before reconnecting
            if self._running.is_set():
                self._log("info", f"Reconnecting in {self._current_delay:.1f}s...")
                time.sleep(self._current_delay)
                # Exponential backoff
                self._current_delay = min(
                    self._current_delay * 2, self._max_reconnect_delay
                )

    def _connect_with_retry(self) -> bool:
        """
        Attempt to connect with exponential backoff.

        Returns:
            True if connected successfully
        """
        if not self._running.is_set():
            return False

        try:
            self._log("info", f"Connecting to {self._url}")

            self._ws = websocket.create_connection(
                self._url,
                timeout=10,
            )

            self._connected = True
            self._current_delay = self._reconnect_delay  # Reset delay on success
            self._last_ping_time = time.time()

            self._log("info", "WebSocket connected successfully")

            # Notify about connection
            self._queues.put_inbound(
                Message(
                    type=MessageType.CONNECTED,
                    instance_id=self._instance_id,
                    payload={"message": "Connected to server"},
                )
            )

            return True

        except Exception as e:
            self._log("warning", f"Connection failed: {e}")

            # Notify about disconnect
            self._queues.put_inbound(
                Message(
                    type=MessageType.DISCONNECTED,
                    instance_id=self._instance_id,
                    payload={
                        "reason": str(e),
                        "retry_in": self._current_delay,
                    },
                )
            )

            self._connected = False
            return False

    def _receive_loop(self) -> None:
        """Receive loop - reads messages and pushes to inbound queue."""
        while self._running.is_set() and self._connected:
            try:
                # Check for ping interval
                if time.time() - self._last_ping_time > self._ping_interval:
                    self._send_ping()

                # Set timeout for receive
                self._ws.settimeout(1.0)

                try:
                    data = self._ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except websocket.WebSocketConnectionClosedException:
                    self._log("info", "WebSocket connection closed by server")
                    break

                if data:
                    message = deserialize_message(data, self._type_mapping)
                    if message:
                        self._queues.put_inbound(message)

            except Exception as e:
                self._log("error", f"Receive error: {e}")
                break

        self._connected = False

    def _send_loop(self) -> None:
        """Send loop - reads from outbound queue and sends pre-serialized messages."""
        while self._running.is_set() and self._connected:
            try:
                # Messages are pre-serialized to JSON strings by the main thread
                # to avoid thread safety issues with Python object access
                data = self._queues.get_outbound(timeout=0.1)
                if data and self._ws:
                    self._log("debug", "Sending message")
                    self._ws.send(data)

            except Exception as e:
                self._log("error", f"Send error: {e}")
                self._handle_disconnect(f"Send thread error: {e}")
                # Close the socket to unblock the receive loop
                if self._ws:
                    try:
                        self._ws.close()
                    except Exception:
                        pass
                break

    def _send_ping(self) -> None:
        """Send ping message for keep-alive via queue (thread-safe)."""
        try:
            if self._connected:
                ping_msg = create_ping_message(self._instance_id)
                # Use queue instead of direct send to avoid race condition
                # with _send_loop() accessing self._ws.send() concurrently
                self._queues.send(ping_msg)
                self._last_ping_time = time.time()
                self._log("debug", "Queued ping")
        except Exception as e:
            self._log("warning", f"Failed to queue ping: {e}")

    def _handle_disconnect(self, reason: str) -> None:
        """Handle unexpected disconnect."""
        self._connected = False

        # Drain stale outbound messages to prevent them leaking into a new session
        cleared = self._queues.clear_outbound()
        if cleared:
            self._log("info", f"Cleared {cleared} stale outbound messages on disconnect")

        # Notify about disconnect
        self._queues.put_inbound(
            Message(
                type=MessageType.DISCONNECTED,
                instance_id=self._instance_id,
                payload={"reason": reason},
            )
        )


# Global client instance
_client: Optional[WebSocketClient] = None


def get_websocket_client() -> Optional[WebSocketClient]:
    """Get the global WebSocket client instance."""
    return _client


def create_websocket_client(
    url: str,
    instance_id: str,
    **kwargs,
) -> WebSocketClient:
    """
    Create and set the global WebSocket client.

    Args:
        url: WebSocket URL
        instance_id: Client instance ID
        **kwargs: Additional arguments for WebSocketClient

    Returns:
        Created WebSocketClient instance
    """
    global _client

    if _client is not None:
        _client.disconnect()

    _client = WebSocketClient(url, instance_id, **kwargs)
    return _client


def cleanup_websocket_client() -> None:
    """Clean up the global WebSocket client."""
    global _client

    if _client is not None:
        _client.disconnect()
        _client = None
