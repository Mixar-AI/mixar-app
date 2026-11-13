# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update Checker Bootstrap Module

Hooks into Blender startup to schedule a delayed update check, and to
report the outcome of an update applied while the app was closed — unless
an update is still being installed, in which case this launch says so and
quits, or an update staged by a session that never quit normally is
installed now (``core/launch_install.py``). It also installs a ready
update when the user quits (an ``exit_pre`` handler,
``core/silent_install.py``). The actual logic lives in
``mixar.modules.common.updates.core``.

Loaded by bootstrap/__init__.py during the startup sequence.  Schedules
a delayed timer so the API infrastructure (executor + queue processor)
is fully running before the first HTTP call.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_init_timer_registered = False
# The version a helper was installing when this launch found it mid-install.
_blocked_version = ""
# Seconds before the first update check (mixar.json updates.check_delay_seconds).
_check_delay = 5


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
        from mixar.modules.common.updates.core.app_paths import running_target
        from mixar.modules.common.updates.core.install_marker import check_startup
        from mixar.modules.common.updates.core.update_checker import (
            get_runtime_version,
        )

        # Only a launch of the copy being installed is turned away.
        marker = check_startup(get_runtime_version() or "", running_target())
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

    try:
        # The helper waits for this launch to exit before it swaps or
        # reopens, and an install on quit reopens Mixar for it. A background
        # run (`Mixar -b`: a preview backfill, a render worker) opened no
        # window, so it must not reopen the one the user just quit; it only
        # quits (the helper's wait for the bundle covers its exit).
        if getattr(bpy.app, "background", False) is not True:
            import os

            from mixar.modules.common.updates.core.install_marker import request_reopen

            request_reopen(marker.get("directory") or "", os.getpid())
    except Exception:  # noqa: BLE001 - the update itself is unaffected
        logger.debug("Could not ask the update helper to reopen Mixar", exc_info=True)

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
# Installing without asking: on quit, and at launch
# ============================================================================


@persistent
def _on_exit_pre(user_exit) -> None:
    """``exit_pre``: Mixar is quitting — install a ready update now.

    Blender passes True for a normal quit of the UI (File > Quit, Cmd+Q,
    the last window closed, a quit after "Save changes?"; a macOS logout
    is cancelled and turned into the same quit),
    False for background mode, a failed start or ``sys.exit``. It runs
    first in ``WM_exit_ex``, while ``bpy`` and the update state are still
    intact — before the quit file is saved, add-ons unregister (which
    resets the update state) and analytics flushes its queue.
    """
    from mixar.modules.common.updates.core.silent_install import install_on_quit

    install_on_quit(user_exit)


def _set_exit_handler(enabled: bool) -> None:
    try:
        handlers = bpy.app.handlers.exit_pre
        if enabled and _on_exit_pre not in handlers:
            handlers.append(_on_exit_pre)
        elif not enabled and _on_exit_pre in handlers:
            handlers.remove(_on_exit_pre)
    except Exception:  # noqa: BLE001 - no handlers (tests, odd builds): no install on quit
        logger.debug("Could not %s the install-on-quit handler",
                     "add" if enabled else "remove", exc_info=True)


def _launch_install_started() -> bool:
    """Install an update a crashed / force-quit session left staged. True
    when this launch is doing so (the normal start-up then waits)."""
    try:
        from mixar.modules.common.updates.core import launch_install

        request = launch_install.launch_install_request()
        if request is None:
            return False
        launch_install.begin_launch_install(
            request, resume=_schedule_delayed_init, check_delay=_check_delay)
    except Exception:  # noqa: BLE001 - start normally
        logger.error("Could not start the install at launch", exc_info=True)
        return False
    return True


# ============================================================================
# Bootstrap lifecycle
# ============================================================================


def _schedule_delayed_init() -> None:
    bpy.app.timers.register(_delayed_init, first_interval=_check_delay, persistent=True)
    logger.info("Update checker timer scheduled (delay: %ss)", _check_delay)


def register() -> None:
    """Called by bootstrap during startup — schedule the delayed check."""
    global _init_timer_registered, _check_delay

    try:
        from mixar.config.config import get_config

        _check_delay = get_config().get("updates", {}).get(
            "check_delay_seconds", 5
        )
    except Exception:
        _check_delay = 5

    if not _init_timer_registered:
        _init_timer_registered = True
        if _install_in_progress():
            return
        _set_exit_handler(True)
        if _launch_install_started():
            return
        _schedule_delayed_init()


def unregister() -> None:
    """Called by bootstrap during shutdown — cancel pending work."""
    global _init_timer_registered

    _set_exit_handler(False)
    for timer in (_delayed_init, _announce_and_quit, _quit_for_update):
        try:
            if bpy.app.timers.is_registered(timer):
                bpy.app.timers.unregister(timer)
        except Exception:
            pass
    try:
        from mixar.modules.common.updates.core import launch_install

        launch_install.cancel()
    except Exception:
        pass

    try:
        from mixar.modules.common.updates.core.state import get_update_state

        get_update_state().set_idle()
    except Exception:
        pass

    _init_timer_registered = False
    logger.info("Update checker shutdown complete")
