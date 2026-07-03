# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Timer-based queue processor for handling async HTTP responses.

Uses bpy.app.timers to poll the response queue on Blender's main
thread and dispatch results to registered callbacks.
"""

import time
from typing import Callable, Optional

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from .constants import (
    CALLBACK_CLEANUP_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    MAX_RESPONSES_PER_TICK,
)
from .exceptions import TimeoutError
from .request_queue import (
    AsyncResponse,
    ResponseStatus,
    get_request_queues,
)


class APIQueueProcessor:
    """
    Processes async HTTP responses on Blender's main thread.

    Uses bpy.app.timers for periodic polling, dispatches responses
    to registered callbacks, and handles cleanup of expired callbacks.
    """

    _instance: Optional["APIQueueProcessor"] = None

    def __new__(cls) -> "APIQueueProcessor":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def _initialize(self) -> None:
        """Initialize processor state."""
        if self._initialized:
            return
        self._processing = False
        self._poll_interval = DEFAULT_POLL_INTERVAL
        self._max_per_tick = MAX_RESPONSES_PER_TICK
        self._queues = get_request_queues()
        self._last_cleanup = 0.0

        # Global error handler
        self._global_error_handler: Optional[Callable[[Exception], None]] = None

        # Stats
        self._responses_processed = 0
        self._errors_count = 0
        self._initialized = True

    def __init__(self):
        self._initialize()

    @property
    def is_processing(self) -> bool:
        """Check if processor is running and timer is registered."""
        if not self._processing:
            return False
        # Also verify timer is actually registered
        try:
            return bpy.app.timers.is_registered(self._poll_callback)
        except Exception:
            return False

    def set_global_error_handler(
        self,
        handler: Optional[Callable[[Exception], None]],
    ) -> None:
        """
        Set a global error handler for uncaught callback exceptions.

        Args:
            handler: Callable that receives the exception
        """
        self._global_error_handler = handler

    def start(
        self,
        poll_interval: Optional[float] = None,
        max_per_tick: Optional[int] = None,
    ) -> None:
        """
        Start processing responses.

        Args:
            poll_interval: How often to poll (seconds)
            max_per_tick: Max responses per timer tick
        """
        if self._processing:
            # Check if timer is still actually registered
            if bpy.app.timers.is_registered(self._poll_callback):
                return
            else:
                # Timer was unregistered unexpectedly, re-register it
                self._processing = False

        if poll_interval is not None:
            self._poll_interval = poll_interval
        if max_per_tick is not None:
            self._max_per_tick = max_per_tick

        self._processing = True
        self._last_cleanup = time.time()

        bpy.app.timers.register(
            self._poll_callback,
            first_interval=self._poll_interval,
        )

    def stop(self) -> None:
        """Stop processing responses."""
        self._processing = False
        try:
            if bpy.app.timers.is_registered(self._poll_callback):
                bpy.app.timers.unregister(self._poll_callback)
        except (ValueError, RuntimeError):
            pass  # Timer not registered or Blender shutting down

    def _poll_callback(self) -> Optional[float]:
        """
        Timer callback that processes queued responses.

        Returns:
            Interval for next call, or None to stop
        """
        try:
            if not self._processing:
                return None

            # Process responses
            for _ in range(self._max_per_tick):
                response = self._queues.get_response()
                if response is None:
                    break
                self._dispatch_response(response)

            # Periodic callback cleanup
            current_time = time.time()
            if current_time - self._last_cleanup > CALLBACK_CLEANUP_INTERVAL:
                self._queues.cleanup_expired_callbacks(current_time)
                self._queues.cleanup_abandoned_callbacks(current_time)
                self._last_cleanup = current_time

            return self._poll_interval
        except Exception:
            # Keep the timer running despite errors
            return self._poll_interval

    def _dispatch_response(self, response: AsyncResponse) -> None:
        """
        Dispatch a response to its registered callback.

        Args:
            response: The response to dispatch
        """
        self._responses_processed += 1

        # Get callback if registered. Timeout notifications must not consume
        # expired callbacks; a slow request may still complete and deliver the
        # accepted backend job later.
        callback = None
        if response.status == ResponseStatus.TIMEOUT:
            if response.callback_id:
                callback = self._queues.peek_expired_callback(response.callback_id)
            if callback is None:
                callback = response.metadata.get("_expired_callback")
        elif response.callback_id:
            callback = self._queues.get_callback(response.callback_id)

        if callback is None:
            # Fire-and-forget request or expired callback
            if response.callback_id:
                logger.debug("[API/Processor] No callback found for %s (status=%s) - may have expired",
                             response.callback_id, response.status.value)
            return

        try:
            # Call appropriate handler based on status
            if response.status == ResponseStatus.SUCCESS:
                if callback.on_success:
                    callback.on_success(response.result)
            elif response.status == ResponseStatus.ERROR:
                if callback.on_error:
                    callback.on_error(response.error)
                elif self._global_error_handler:
                    self._global_error_handler(response.error)
            elif response.status == ResponseStatus.TIMEOUT:
                if callback.on_error:
                    callback.on_error(TimeoutError("Request timed out"))
                elif self._global_error_handler:
                    self._global_error_handler(TimeoutError("Request timed out"))

            # Always call on_complete if provided
            if callback.on_complete:
                callback.on_complete(response)

        except Exception as e:
            self._errors_count += 1
            logger.error("[API/Processor] Callback exception: %s", e, exc_info=True)
            if self._global_error_handler:
                try:
                    self._global_error_handler(e)
                except Exception:
                    pass  # Prevent infinite loop

    def get_stats(self) -> dict:
        """Get processor statistics."""
        return {
            "responses_processed": self._responses_processed,
            "errors_count": self._errors_count,
            "pending_responses": self._queues.response_count(),
            "pending_callbacks": self._queues.callback_count(),
            "expired_callbacks": self._queues.expired_callback_count(),
        }

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance."""
        if cls._instance is not None:
            cls._instance.stop()
            cls._instance._initialized = False
            cls._instance._initialize()


def get_api_processor() -> APIQueueProcessor:
    """Get the global APIQueueProcessor singleton."""
    return APIQueueProcessor()


def start_api_processor(**kwargs) -> APIQueueProcessor:
    """Start and return the global processor."""
    processor = get_api_processor()
    processor.start(**kwargs)
    return processor


def stop_api_processor() -> None:
    """Stop the global processor."""
    get_api_processor().stop()
