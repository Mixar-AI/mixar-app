# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local models bootstrap.

register():
- ``paths.initialize()`` — resolve the bpy.utils storage dir ON THE MAIN
  THREAD once, so background download/supervisor threads never touch bpy
  (generation_catalog storage pattern).
- A delayed one-shot timer (update_checker pattern, ~6 s so the API
  executor and UI modules are up first) that restores the relay's
  approved bases from the manifest and — when the saved BYOK provider is
  local+managed — restarts the llama-server so chat works immediately,
  then arms a light periodic health watch (auto-restart of a crashed
  managed server, capped at the supervisor's budget of 2; a port change
  on restart silently re-registers the credential — both handled in
  ``local_models/core/orchestrator.py``).

unregister(): stop the managed server (a llama-server holding gigabytes
of RAM must never outlive Blender). The atexit mirror lives in
``bootstrap/shutdown_hooks._run_all_cleanups`` alongside the sandbox
kill_all.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_STARTUP_DELAY_S = 6.0
_WATCH_INTERVAL_S = 30.0

_init_timer_registered = False
_watch_registered = False


def _delayed_init():
    """Main-thread one-shot: resume the registered local setup."""
    global _watch_registered
    try:
        from mixar.modules.local_models.core import orchestrator
        orchestrator.resume_registered()
    except Exception as exc:
        logger.warning("Local models resume failed: %s", exc)
    if not _watch_registered:
        try:
            bpy.app.timers.register(
                _watch_tick, first_interval=_WATCH_INTERVAL_S, persistent=True
            )
            _watch_registered = True
        except Exception as exc:
            logger.warning("Local models health watch not started: %s", exc)
    return None  # one-shot


def _watch_tick():
    """Main-thread periodic self-heal (see orchestrator.watch_tick)."""
    try:
        from mixar.modules.local_models.core import orchestrator
        orchestrator.watch_tick()
    except Exception as exc:
        logger.debug("Local models watch tick failed: %s", exc)
    return _WATCH_INTERVAL_S


def register() -> None:
    global _init_timer_registered
    try:
        from mixar.modules.local_models.core import paths
        paths.initialize()
    except Exception as exc:
        logger.warning("Local models path init failed: %s", exc)
    if not _init_timer_registered:
        bpy.app.timers.register(
            _delayed_init, first_interval=_STARTUP_DELAY_S, persistent=True
        )
        _init_timer_registered = True
        logger.info("Local models bootstrap scheduled (delay: %ss)",
                    _STARTUP_DELAY_S)


def unregister() -> None:
    global _init_timer_registered, _watch_registered
    for callback in (_delayed_init, _watch_tick):
        try:
            if bpy.app.timers.is_registered(callback):
                bpy.app.timers.unregister(callback)
        except Exception:
            pass
    _init_timer_registered = False
    _watch_registered = False
    try:
        from mixar.modules.local_models.core import orchestrator
        orchestrator.shutdown()
    except Exception as exc:
        logger.debug("Local models shutdown failed: %s", exc)
    logger.info("Local models bootstrap shut down")
