# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update Checker Bootstrap Module

Hooks into Blender startup to schedule a delayed update check, and to
report the outcome of an update applied while the app was closed — unless
an update is still being installed, in which case this launch says so and
quits.  The
actual logic lives in ``mixar.modules.common.updates.core``.

Loaded by bootstrap/__init__.py during the startup sequence.  Schedules
a delayed timer so the API infrastructure (executor + queue processor)
is fully running before the first HTTP call.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_init_timer_registered = False
# The version a helper was installing when this launch found it mid-install.
_blocked_version = ""


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
# A launch while an update is being installed
# ============================================================================


def _install_in_progress() -> bool:
    """True when a helper is installing an update: say so and quit.

    Checked before anything reads or purges the staging directory (the
    result report, the update check), which are then never scheduled. Any
    failure starts normally.
    """
    try:
        from mixar.modules.common.updates.core.install_marker import check_startup
        from mixar.modules.common.updates.core.update_checker import (
            get_runtime_version,
        )

        marker = check_startup(get_runtime_version() or "")
    except Exception as e:  # noqa: BLE001 - fail open
        logger.debug("Could not check for an update in progress: %s", e)
        return False
    if marker is None:
        return False
    try:
        # This launch quits again: its relay (mcp_bridge ticks before this
        # module's timers fire) must not end the connector's "updating"
        # window, or a fresh connector would cold-start the old binary.
        from mixar.modules.mcp_bridge.core import installation as connector_installation

        connector_installation.keep_updating()
    except Exception:  # noqa: BLE001 - the marker then expires on its own
        logger.debug("Could not keep the connector's updating marker", exc_info=True)

    global _blocked_version
    _blocked_version = str(marker.get("target_version") or "")
    logger.warning(
        "Mixar %s is being installed (helper pid %s) - quitting this launch",
        _blocked_version, marker.get("helper_pid"),
    )
    bpy.app.timers.register(_announce_and_quit, first_interval=0.0, persistent=True)
    return True


def _announce_and_quit() -> None:
    """Show "Mixar is finishing an update", then quit a few seconds later."""
    from mixar.modules.common.updates.constants import MID_INSTALL_QUIT_DELAY_S

    try:
        from mixar.modules.common.updates.core.toasts import (
            push_finishing_update_toast,
        )

        push_finishing_update_toast()
    except Exception:  # noqa: BLE001 - quit regardless
        logger.debug("Could not show the finishing-update toast", exc_info=True)
    try:
        from mixar.modules.common.analytics.update_events import capture_update_blocked

        capture_update_blocked(_blocked_version)
    except Exception:  # noqa: BLE001 - telemetry is fail-open
        logger.debug("Update blocked telemetry failed", exc_info=True)
    bpy.app.timers.register(
        _quit_for_update, first_interval=MID_INSTALL_QUIT_DELAY_S, persistent=True)
    return None


def _quit_for_update() -> None:
    try:
        bpy.ops.wm.quit_blender()
    except Exception:  # noqa: BLE001 - nothing to recover; the app stays open
        logger.error("Quit while an update is being installed failed", exc_info=True)
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
        if _install_in_progress():
            _init_timer_registered = True
            return
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

    for timer in (_delayed_init, _announce_and_quit, _quit_for_update):
        try:
            if bpy.app.timers.is_registered(timer):
                bpy.app.timers.unregister(timer)
        except Exception:
            pass

    try:
        from mixar.modules.common.updates.core.state import get_update_state

        get_update_state().set_idle()
    except Exception:
        pass

    _init_timer_registered = False
    logger.info("Update checker shutdown complete")
