# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded outbound requests, responses and callback deadlines."""
import json
import threading
import time
from queue import Full
from typing import Any, Callable, Optional
from mixar.config.logging_config import get_logger
from ..constants import JSONRPCMethod
logger = get_logger(__name__)


class SocketRequests:
    def _expire_pending(self):
        now = time.monotonic()
        with self._pending_lock:
            expired = [key for key, deadline in self._pending_deadlines.items() if deadline <= now]
            callbacks = [self._pending_callbacks.pop(key, None) for key in expired]
            for key in expired:
                self._pending_deadlines.pop(key, None)
        for callback in callbacks:
            if callback:
                try:
                    callback({"code": -32020, "message": "Request timed out; delivery is uncertain", "data": {"uncertain": True}})
                except Exception:
                    logger.debug("Expired request callback failed", exc_info=True)

    def send_request(
        self,
        method: str,
        params: dict,
        on_result: Optional[Callable[[Any], None]] = None,
        timeout: float = 35.0,
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
                self._pending_deadlines[request_id] = time.monotonic() + timeout
        try:
            encoded = json.dumps(request)
            if len(encoded.encode('utf-8')) > 32 * 1024 * 1024:
                raise ValueError("Agent request exceeds the socket message limit")
            self._outbound.put_nowait(encoded)
        except Exception:
            with self._pending_lock:
                self._pending_callbacks.pop(request_id, None)
                self._pending_deadlines.pop(request_id, None)
            raise
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
        return self._enqueue_frame(notification)

    def _send_ping(self) -> None:
        """Send ping request."""
        request_id = f"ping_{self._next_request_id()}"
        ping = {
            "jsonrpc": "2.0",
            "method": JSONRPCMethod.SYSTEM_PING,
            "id": request_id,
        }
        self._enqueue_frame(ping, required=True)
        self._last_ping_time = time.time()
        logger.debug("Sent ping")

    def _enqueue_frame(self, frame, *, required=False):
        """Never block the UI or reader on backpressure; force recovery if needed."""
        try:
            encoded = json.dumps(frame)
            if len(encoded.encode('utf-8')) > 32 * 1024 * 1024:
                raise ValueError('Agent response exceeds the socket message limit')
            self._outbound.put_nowait(encoded)
            return True
        except (Full, ValueError):
            if required and self._ws:
                # A tool result cannot be silently lost or replayed as execution.
                self._connected = False
                threading.Thread(target=self._ws.close, daemon=True).start()
            return False

    def queue_response(self, request_id: str, result: dict) -> None:
        """Queue a JSON-RPC response for sending (thread-safe)."""
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        self._enqueue_frame(response, required=True)
        logger.debug(f"Response queued for request {request_id}")

    def _next_request_id(self) -> int:
        """Get next request ID (thread-safe)."""
        with self._request_id_lock:
            self._request_id += 1
            return self._request_id
