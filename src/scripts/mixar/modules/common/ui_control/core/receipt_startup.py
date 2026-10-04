# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Initialize durable UI receipts without waiting for SQLite on Blender's UI."""

import threading
import time

from mixar.config.logging_config import get_logger

from .receipts import Receipts

logger = get_logger(__name__)


class ReceiptInitializer:
    """One worker, bounded retry frequency, and no Blender access.

    The main thread polls for an initialized connection. Cancel invalidates
    in-flight results; an obsolete worker closes its own connection and can
    never publish into a later enable cycle. The journal is never bypassed.
    """

    def __init__(self, factory=None, clock=None):
        self._factory = factory or Receipts
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._generation = 0
        self._path = None
        self._thread = None
        self._ready = None
        self._finished = False
        self._retry_at = 0.0
        self._failures = 0
        self._error = None
        self._logged_error = None

    def poll(self, path):
        """Return ready receipts or None immediately; start at most one worker."""
        with self._lock:
            if self._path is not None and self._path != path:
                raise ValueError('Cancel receipt initialization before changing its path')
            self._path = path
            if self._ready is not None:
                ready, self._ready = self._ready, None
                return ready
            if self._finished or self._thread is not None or self._clock() < self._retry_at:
                return None
            generation = self._generation
            thread = threading.Thread(target=self._initialize, args=(path, generation),
                                      name='MixarUIReceipts', daemon=True)
            self._thread = thread
        try:
            thread.start()
        except Exception as exc:
            with self._lock:
                if self._thread is thread:
                    self._thread = None
                if generation == self._generation:
                    self._failed(exc)
        return None

    def _failed(self, exc):
        """Update retry state under the lock, logging each failure signature once."""
        self._failures += 1
        self._retry_at = self._clock() + min(60.0, 2.0 ** min(self._failures, 6))
        signature = (type(exc).__name__, str(exc))
        self._error = signature
        if signature != self._logged_error:
            self._logged_error = signature
            logger.warning('UI receipt storage unavailable (%s): %s; retrying in background',
                           *signature)

    def _initialize(self, path, generation):
        receipt = None
        try:
            with self._lock:
                if generation != self._generation:
                    return
            receipt = self._factory(path)
            with self._lock:
                if generation == self._generation:
                    self._ready, receipt = receipt, None
                    self._finished = True
                    self._failures = 0
                    self._retry_at = 0.0
                    self._error = self._logged_error = None
        except Exception as exc:
            with self._lock:
                if generation == self._generation:
                    self._failed(exc)
        finally:
            # Do not release the single-flight guard until a cancelled worker
            # has closed its result. A rapid disable/re-enable cannot overlap it.
            try:
                if receipt is not None:
                    receipt.close()
            finally:
                with self._lock:
                    self._thread = None

    def status(self):
        with self._lock:
            if self._path is None:
                state = 'disabled'
            elif self._finished:
                state = 'ready'
            elif self._error is not None:
                state = 'retrying'
            else:
                state = 'starting'
            return {'state': state,
                    'error_type': self._error[0] if self._error else None,
                    'error': self._error[1] if self._error else None,
                    'retry_in_seconds': max(0.0, self._retry_at - self._clock())}

    def cancel(self):
        """Invalidate pending work without joining a worker blocked in SQLite."""
        with self._lock:
            self._generation += 1
            self._path = None
            ready, self._ready = self._ready, None
            self._finished = False
            self._retry_at = 0.0
            self._failures = 0
            self._error = self._logged_error = None
        if ready is not None:
            ready.close()
