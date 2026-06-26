# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Thread-safe request/response queues for async HTTP communication.

Provides communication between background executor threads and
Blender's main thread via queue-based message passing.

IMPORTANT: Response data is passed as-is since APIResponse is
already a simple dataclass. Callbacks and Blender operations
must only happen on the main thread.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from queue import Empty, Queue
from typing import Any, Callable, Dict, List, Optional


class ResponseStatus(Enum):
    """Status of an async response."""

    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class AsyncResponse:
    """
    Response from an async HTTP request.

    Attributes:
        request_id: Original request ID
        status: Response status
        result: APIResponse if successful
        error: Exception if failed
        callback_id: ID for routing to specific callback
        metadata: Original request metadata
        elapsed_ms: Request duration in milliseconds
    """

    request_id: str
    status: ResponseStatus
    result: Any = None
    error: Optional[Exception] = None
    callback_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0


@dataclass
class PendingCallback:
    """
    Registered callback waiting for a response.

    Attributes:
        callback_id: Unique callback identifier
        on_success: Called with APIResponse on success
        on_error: Called with exception on error
        on_complete: Called regardless of outcome
        timeout: Timeout in seconds (0 = no timeout)
        created_at: Registration timestamp
        metadata: User-provided metadata
    """

    callback_id: str
    on_success: Optional[Callable[[Any], None]] = None
    on_error: Optional[Callable[[Exception], None]] = None
    on_complete: Optional[Callable[[AsyncResponse], None]] = None
    timeout: float = 0.0
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class RequestQueues:
    """
    Singleton holding response queue and callback registry.

    Thread-safe via Python's queue.Queue and threading locks.
    """

    _instance: Optional["RequestQueues"] = None

    def __new__(cls) -> "RequestQueues":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def _initialize(self) -> None:
        """Initialize queue state."""
        if self._initialized:
            return
        self._response_queue: Queue[AsyncResponse] = Queue()
        self._callbacks: Dict[str, PendingCallback] = {}
        self._expired_callbacks: Dict[str, PendingCallback] = {}
        self._callback_lock = threading.Lock()
        self._initialized = True

    def __init__(self):
        self._initialize()

    def register_callback(
        self,
        on_success: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        timeout: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Register a callback for an async request.

        Args:
            on_success: Called with result on success
            on_error: Called with exception on error
            on_complete: Called with full AsyncResponse
            timeout: Callback timeout in seconds
            metadata: User metadata to pass through

        Returns:
            Callback ID to associate with request
        """
        callback_id = str(uuid.uuid4())

        callback = PendingCallback(
            callback_id=callback_id,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
            timeout=timeout,
            metadata=metadata or {},
        )

        with self._callback_lock:
            self._callbacks[callback_id] = callback

        return callback_id

    def get_callback(self, callback_id: str) -> Optional[PendingCallback]:
        """Get and remove a registered callback.

        Checks both active and expired callbacks to handle late responses
        from slow requests that completed after timeout cleanup.
        """
        with self._callback_lock:
            callback = self._callbacks.pop(callback_id, None)
            if callback is not None:
                return callback
            return self._expired_callbacks.pop(callback_id, None)

    def peek_expired_callback(self, callback_id: str) -> Optional[PendingCallback]:
        """Return an expired callback without consuming it.

        Timeout notifications are advisory. Keeping the expired callback allows
        the real late HTTP response to reconcile the original operation.
        """
        with self._callback_lock:
            return self._expired_callbacks.get(callback_id)

    def cancel_callback(self, callback_id: str) -> bool:
        """Cancel a pending callback."""
        with self._callback_lock:
            return self._callbacks.pop(callback_id, None) is not None

    def put_response(self, response: AsyncResponse) -> None:
        """
        Queue a response for main thread processing.

        Called by executor threads when requests complete.

        Args:
            response: The async response to queue
        """
        self._response_queue.put(response)

    def get_response(self) -> Optional[AsyncResponse]:
        """
        Non-blocking get from response queue.

        Returns:
            AsyncResponse if available, None otherwise
        """
        try:
            return self._response_queue.get_nowait()
        except Empty:
            return None

    def get_responses(self, max_count: int = 10) -> List[AsyncResponse]:
        """
        Get multiple responses from queue.

        Args:
            max_count: Maximum responses to retrieve

        Returns:
            List of AsyncResponse objects
        """
        responses = []
        for _ in range(max_count):
            response = self.get_response()
            if response is None:
                break
            responses.append(response)
        return responses

    def response_count(self) -> int:
        """Get approximate number of pending responses."""
        return self._response_queue.qsize()

    def callback_count(self) -> int:
        """Get number of registered callbacks."""
        with self._callback_lock:
            return len(self._callbacks)

    def expired_callback_count(self) -> int:
        """Get number of expired callbacks awaiting late responses."""
        with self._callback_lock:
            return len(self._expired_callbacks)

    def cleanup_expired_callbacks(self, current_time: Optional[float] = None) -> int:
        """
        Handle expired callbacks and queue timeout responses.

        Moves expired callbacks to _expired_callbacks dict for late response
        handling (fixes race condition where slow requests complete after timeout).

        Args:
            current_time: Current timestamp (default: time.time())

        Returns:
            Number of callbacks that timed out
        """
        if current_time is None:
            current_time = time.time()

        expired_callbacks: List[PendingCallback] = []

        with self._callback_lock:
            expired_ids = []
            for callback_id, callback in self._callbacks.items():
                if callback.timeout > 0:
                    elapsed = current_time - callback.created_at
                    if elapsed > callback.timeout:
                        expired_ids.append(callback_id)
                        expired_callbacks.append(callback)

            # Move to expired dict instead of deleting (allows late response handling)
            for callback_id in expired_ids:
                callback = self._callbacks.pop(callback_id)
                self._expired_callbacks[callback_id] = callback

        # Queue timeout responses with callback data embedded
        for callback in expired_callbacks:
            self.put_response(
                AsyncResponse(
                    request_id="",
                    status=ResponseStatus.TIMEOUT,
                    callback_id=callback.callback_id,
                    metadata={"_expired_callback": callback},
                )
            )

        return len(expired_callbacks)

    def cleanup_abandoned_callbacks(
        self,
        current_time: Optional[float] = None,
        grace_multiplier: float = 2.0,
    ) -> int:
        """
        Remove expired callbacks that have exceeded their grace period.

        Handles cases where requests never complete (connection dropped, etc.)

        Args:
            current_time: Current timestamp (default: time.time())
            grace_multiplier: How many times the original timeout to wait

        Returns:
            Number of abandoned callbacks removed
        """
        if current_time is None:
            current_time = time.time()

        with self._callback_lock:
            abandoned_ids = [
                cid
                for cid, cb in self._expired_callbacks.items()
                if cb.timeout > 0
                and (current_time - cb.created_at) > cb.timeout * (1 + grace_multiplier)
            ]
            for callback_id in abandoned_ids:
                del self._expired_callbacks[callback_id]

        return len(abandoned_ids)

    def clear(self) -> tuple:
        """
        Clear all queues and callbacks.

        Returns:
            Tuple of (responses_cleared, callbacks_cleared)
        """
        responses_cleared = 0
        while True:
            try:
                self._response_queue.get_nowait()
                responses_cleared += 1
            except Empty:
                break

        with self._callback_lock:
            callbacks_cleared = len(self._callbacks) + len(self._expired_callbacks)
            self._callbacks.clear()
            self._expired_callbacks.clear()

        return responses_cleared, callbacks_cleared

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance."""
        if cls._instance is not None:
            cls._instance.clear()
            cls._instance._initialized = False
            cls._instance._initialize()


def get_request_queues() -> RequestQueues:
    """Get the global RequestQueues singleton."""
    return RequestQueues()
