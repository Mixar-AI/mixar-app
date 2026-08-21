# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update Checker Bootstrap Module

Hooks into Blender startup to schedule a delayed update check, and to
report the outcome of an update applied while the app was closed.  The
actual logic lives in ``mixar.modules.common.updates.core``.

Loaded by bootstrap/__init__.py during the startup sequence.  Schedules
a delayed timer so the API infrastructure (executor + queue processor)
is fully running before the first HTTP call.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_init_timer_registered = False


# ============================================================================
# Timer callback — fires once after startup delay
# ============================================================================


def _delayed_init() -> None:
    """Report the last install's outcome, then check for a new update.

    Runs on the **main thread** (bpy.app.timers callback).
    Returns ``None`` so the timer does not repeat.

    Order matters: the outcome toast is about the update the user already
    asked for, so it goes up before a check can push a new one over it.
    """
    from mixar.modules.common.updates.core.toasts import (
        report_previous_update_result,
    )
    from mixar.modules.common.updates.core.trigger import trigger_update_check

    try:
        report_previous_update_result()
    except Exception as e:  # noqa: BLE001 - never block the update check
        logger.debug("Could not report the previous update result: %s", e)

    trigger_update_check()
    return None


# ============================================================================
# Bootstrap lifecycle
# ============================================================================


def register() -> None:
    """Called by bootstrap during startup — schedule the delayed check."""
    global _init_timer_registered

    try:
        from mixar.config.config import get_config

        delay = get_config().get("updates", {}).get(
            "check_delay_seconds", 5
        )
    except Exception:
        delay = 5

    if not _init_timer_registered:
        bpy.app.timers.register(
            _delayed_init,
            first_interval=delay,
            persistent=True,
        )
        _init_timer_registered = True
        logger.info("Update checker timer scheduled (delay: %ss)", delay)


def unregister() -> None:
    """Called by bootstrap during shutdown — cancel pending work."""
    global _init_timer_registered

    try:
        if bpy.app.timers.is_registered(_delayed_init):
            bpy.app.timers.unregister(_delayed_init)
            logger.debug("Update checker timer unregistered")
    except Exception:
        pass

    try:
        from mixar.modules.common.updates.core.state import get_update_state

        get_update_state().set_idle()
    except Exception:
        pass

    _init_timer_registered = False
    logger.info("Update checker shutdown complete")
