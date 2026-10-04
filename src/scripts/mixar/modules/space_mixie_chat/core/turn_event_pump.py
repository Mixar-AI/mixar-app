# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Demand-driven main-thread delivery, with no timer while the inbox is empty."""

import threading

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class TurnEventPump:
    """Fence deferred starts and give every wake-up a fresh timer identity.

    A producer can arrive after a timer decides to stop but before Blender
    removes it. Reusing that timer function would lose the new registration.
    The request counter also covers arrivals during the last drain pass.
    """

    def __init__(self, drain):
        self._drain = drain
        self._lock = threading.Lock()
        self._enabled = False
        self._callback = None
        self._requests = 0

    def enable(self):
        """Main thread: rearm after load, including a dropped one-shot start."""
        with self._lock:
            self._enabled = True
            if self._callback is not None:
                import bpy
                # Blender drops nonpersistent scheduler wrappers on file load.
                # Supersede a deferred start as well as an unexpectedly removed
                # consumer; arm() requests a replacement if the inbox is nonempty.
                if not bpy.app.timers.is_registered(self._callback):
                    self._callback = None

    def pending(self):
        with self._lock:
            return self._callback is not None

    def request(self):
        """Safe on the socket thread: dispatch registration to the main thread."""
        with self._lock:
            if not self._enabled:
                return
            self._requests += 1
            if self._callback is not None:
                return
            failures = 0

            def tick():
                nonlocal failures
                with self._lock:
                    if self._callback is not tick:
                        return None
                    requests = self._requests
                try:
                    interval = self._drain()
                    failures = 0
                except Exception:
                    failures += 1
                    if failures == 1:
                        logger.exception('Agent event pump failed; retrying delivery')
                    # Keep the backlog live without flooding logs or spinning
                    # the main loop if a recovery dependency stays unavailable.
                    interval = min(2.0, 0.1 * 2 ** min(failures - 1, 5))
                with self._lock:
                    if self._callback is not tick:
                        return None
                    if interval is not None or requests != self._requests:
                        return interval if interval is not None else 0.02
                    self._callback = None
                return None

            self._callback = tick

        def start():
            import bpy
            with self._lock:
                if self._callback is not tick:
                    return
                try:
                    bpy.app.timers.register(tick, first_interval=0.0, persistent=True)
                except Exception:
                    self._callback = None
                    logger.exception('Agent event pump could not start')

        from .main_thread_executor import run_on_main_thread
        if run_on_main_thread(start) is False:
            with self._lock:
                if self._callback is tick:
                    self._callback = None

    def stop(self, *, app_exit=False):
        with self._lock:
            self._enabled = False
            callback, self._callback = self._callback, None
        if callback is not None and not app_exit:
            import bpy
            if bpy.app.timers.is_registered(callback):
                bpy.app.timers.unregister(callback)
