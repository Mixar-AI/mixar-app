# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Start the Python stall watchdog (see ``common/utils/stall_watchdog.py``).

The heartbeat is the native main-loop iteration counter exposed as
``aud._mixar_main_loop_iteration``; a binary without it (an older build, ``--background``)
runs no watchdog. ``MIXAR_STALL_LOG=off`` disables it with the native log;
``MIXAR_STALL_STACK_MS`` sets the capture threshold (default 500 ms).
"""

import logging
import os

import bpy

logger = logging.getLogger(__name__)

_ENV_THRESHOLD_MS = "MIXAR_STALL_STACK_MS"
_ENV_LOG = "MIXAR_STALL_LOG"
_thread = None
_stop = None


def _enabled() -> bool:
    if bpy.app.background:
        return False
    return os.environ.get(_ENV_LOG, "") not in ("off", "0")


def _threshold_s() -> float:
    try:
        value = float(os.environ.get(_ENV_THRESHOLD_MS, "") or 0)
    except ValueError:
        value = 0.0
    return value / 1000.0 if value > 0 else 0.5


def register() -> None:
    global _thread, _stop
    if _thread is not None or not _enabled():
        return
    try:
        import aud
        iteration_fn = getattr(aud, "_mixar_main_loop_iteration", None)
        if iteration_fn is None:
            logger.debug("stall watchdog: no native heartbeat in this build")
            return
        from mixar.modules.common.utils import stall_log, stall_watchdog
        _thread, _stop = stall_watchdog.start(
            iteration_fn, stall_log.stall_log_path(), threshold_s=_threshold_s())
    except Exception as exc:   # never break startup for a diagnostic
        logger.debug("stall watchdog not started: %s", exc)


def unregister() -> None:
    global _thread, _stop
    if _stop is not None:
        _stop.set()
    if _thread is not None:
        _thread.join(1.0)
    _thread = _stop = None
