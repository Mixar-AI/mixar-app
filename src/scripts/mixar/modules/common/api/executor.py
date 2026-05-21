# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Thread pool executor for background HTTP requests.

Manages a pool of daemon threads that execute HTTP requests
without blocking Blender's main thread.
"""

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

from .constants import DEFAULT_POOL_SIZE


class RequestPriority(Enum):
    """Priority levels for async requests."""

    LOW = 0
    NORMAL = 1
    HIGH = 2


@dataclass
class AsyncRequest:
    """
    Represents an async HTTP request to be executed.

    Attributes:
        request_id: Unique identifier for tracking
        callable: The function to execute (pre-bound with args)
        priority: Execution priority
        callback_id: Optional ID for callback routing
        created_at: Timestamp for timeout tracking
        metadata: Additional data for callback processing
    """

    request_id: str
    callable: Callable[[], Any]
    priority: RequestPriority = RequestPriority.NORMAL
    callback_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class HTTPExecutor:
    """
    Thread pool executor for background HTTP requests.

    Features:
    - Configurable pool size
    - Daemon threads (auto-terminate with Blender)
    - Request tracking for cancellation
    - Graceful shutdown support
    """

    _instance: Optional["HTTPExecutor"] = None

    def __new__(cls) -> "HTTPExecutor":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def _initialize(self) -> None:
        """Initialize executor state."""
        if self._initialized:
            return
        self._pool: Optional[ThreadPoolExecutor] = None
        self._pool_size = DEFAULT_POOL_SIZE
        self._pending_futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        self._shutdown = False
        self._initialized = True

    def start(self, pool_size: Optional[int] = None) -> None:
        """
        Start the executor thread pool.

        Args:
            pool_size: Number of worker threads (default: 4)
        """
        self._initialize()

        if self._pool is not None:
            return

        if pool_size is not None:
            self._pool_size = pool_size

        self._shutdown = False
        self._pool = ThreadPoolExecutor(
            max_workers=self._pool_size,
            thread_name_prefix="MixarAPI",
        )

    def stop(self, wait: bool = False) -> None:
        """
        Stop the executor and optionally wait for pending requests.

        Args:
            wait: Whether to wait for pending requests to complete
        """
        self._shutdown = True

        if self._pool is not None:
            self._pool.shutdown(wait=wait, cancel_futures=not wait)
            self._pool = None

        with self._lock:
            self._pending_futures.clear()

    @property
    def is_running(self) -> bool:
        """Check if executor is running."""
        return self._pool is not None and not self._shutdown

    def submit(
        self,
        request: AsyncRequest,
        on_complete: Callable[[str, Any, Optional[Exception]], None],
    ) -> str:
        """
        Submit a request for background execution.

        Args:
            request: The async request to execute
            on_complete: Callback invoked when request completes
                        Signature: (request_id, result, exception)

        Returns:
            Request ID for tracking/cancellation

        Raises:
            RuntimeError: If executor is not running
        """
        if not self.is_running:
            raise RuntimeError("HTTPExecutor is not running. Call start() first.")

        def _execute():
            result = None
            exception = None
            try:
                result = request.callable()
            except Exception as e:
                exception = e
            finally:
                # Clean up tracking
                with self._lock:
                    self._pending_futures.pop(request.request_id, None)
                # Invoke completion callback
                on_complete(request.request_id, result, exception)

        future = self._pool.submit(_execute)

        with self._lock:
            self._pending_futures[request.request_id] = future

        return request.request_id

    def cancel(self, request_id: str) -> bool:
        """
        Attempt to cancel a pending request.

        Args:
            request_id: ID of request to cancel

        Returns:
            True if cancelled, False if already running/completed
        """
        with self._lock:
            future = self._pending_futures.pop(request_id, None)

        if future is not None:
            return future.cancel()
        return False

    def pending_count(self) -> int:
        """Get number of pending requests."""
        with self._lock:
            return len(self._pending_futures)

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance."""
        if cls._instance is not None:
            cls._instance.stop(wait=False)
            cls._instance._initialized = False
            cls._instance._initialize()


def get_executor() -> HTTPExecutor:
    """Get the global HTTPExecutor singleton."""
    return HTTPExecutor()


def start_executor(pool_size: Optional[int] = None) -> HTTPExecutor:
    """Start and return the global executor."""
    executor = get_executor()
    executor.start(pool_size)
    return executor


def stop_executor(wait: bool = False) -> None:
    """Stop the global executor."""
    get_executor().stop(wait)
