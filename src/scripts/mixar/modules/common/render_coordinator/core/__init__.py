# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main-thread reservations for in-process renders, including their cleanup.

The native RENDER job flag does not cover setup or result collection. Keep a
reservation across both. No waits, threads, scene references or global script
gate: callers keep their own queues and retry when acquisition returns None.
Separate headless processes have independent render state.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import threading

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)
_active = None


class RenderBusy(RuntimeError):
    """A native render or another owner still uses the render state."""


@dataclass(eq=False)
class Reservation:
    owner: str
    phase: str = "preparing"


def _main_thread():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Render reservations require the main thread")


@persistent
def _before_load(_unused, _extra=None):
    global _active
    _active = None  # No RNA access: old callbacks cannot release a new token.


def busy():
    _main_thread()
    return _active is not None or bpy.app.is_job_running("RENDER")


def acquire(owner):
    """Reserve before scene mutation; None means the caller must defer."""
    global _active
    if busy():
        return None
    if _before_load not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_before_load)
    _active = Reservation(owner)
    logger.debug("[RenderSlot] acquired %s", owner)
    return _active


def owns(token):
    return token is not None and token is _active


def phase(token, value):
    _main_thread()
    if not owns(token):
        raise RenderBusy("Render reservation expired")
    token.phase = value
    logger.debug("[RenderSlot] %s %s", token.owner, value)


def release(token):
    global _active
    _main_thread()
    if owns(token):
        logger.debug("[RenderSlot] released %s", token.owner)
        _active = None


@contextmanager
def reserve(owner, token=None):
    """Borrow an explicit parent's token, or own a synchronous operation."""
    _main_thread()
    borrowed = token is not None
    if borrowed:
        if not owns(token) or bpy.app.is_job_running("RENDER"):
            raise RenderBusy("Another render is already in progress")
    else:
        token = acquire(owner)
        if token is None:
            raise RenderBusy("Another render is already in progress")
    try:
        yield token
    finally:
        if not borrowed:
            release(token)
