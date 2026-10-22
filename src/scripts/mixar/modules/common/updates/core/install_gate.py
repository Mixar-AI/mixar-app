# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Windows Pre-Quit Gate

Restart & Update quits only once nothing else runs from the install
directory: Windows Installer replaces an in-use file only at the next
reboot, so the relaunch would start the old build. :mod:`win_processes`
says who holds it; this module acts on the answer, on the main thread:

- another Mixar window or any other program is the user's to close: the
  "Close other apps to update" toast names them;
- Mixar's own background work ends by itself: the "Finishing background
  work" toast stays up while a timer re-checks every BACKGROUND_POLL_S and
  continues the update once it is clear. Cancel stops it. A wait that
  outlasts BACKGROUND_WAIT_MAX_S stops waiting here and leaves what is
  left to the helper's own bounded wait;
- a Mixar connector (the python an AI app such as Claude or Codex keeps
  running as its MCP server, or one whose AI app is gone) holds no user
  work and is stale once Mixar restarts, so it is ended — but only once
  the two checks above have let the update go ahead, never while the
  update then stops anyway or on every poll of a background wait. One
  that cannot be ended is named.

Other platforms pass straight through.
"""

import os
import time

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ..constants import BACKGROUND_POLL_S, BACKGROUND_WAIT_MAX_S, InstallState
from .state import get_update_state

logger = get_logger(__name__)

# apply_and_restart's messages when it stopped here. The toast saying why
# is already up, so the caller must not replace it.
BLOCKED_BY_OTHER_APPS = n_("Close the apps listed in the notification, then try again")
WAITING_FOR_BACKGROUND = n_("Mixar will update once its background tasks finish")

# time.monotonic() when the current wait began; None while not waiting.
_wait_since = None
# A wait ran out: the next check lets background work through to the helper.
_waited_out = False


def _is_windows() -> bool:
    return os.name == "nt"


def _holders(install_dir):
    from . import win_processes

    return win_processes.blocking_apps(install_dir, os.getpid())


def _end_connectors(holders):
    """End every Mixar connector, live or abandoned; one still running is named instead.

    A live connector keeps its kind so the toast names the AI app behind it;
    an abandoned one has no app to name and is shown by its basename.
    """
    from . import win_processes

    remaining = []
    for holder in holders:
        if holder.kind not in win_processes.ENDED_BY_UPDATE:
            remaining.append(holder)
            continue
        live = holder.kind == win_processes.CONNECTOR
        what = "Mixar connector of %s" % holder.name if live else (
            "abandoned Mixar connector %s" % holder.name)
        if win_processes.terminate(holder):
            logger.info("Ended %s (pid %s)", what, holder.pid)
        else:
            logger.warning("Could not end %s (pid %s)", what, holder.pid)
            remaining.append(holder if live else holder._replace(kind=win_processes.OTHER))
    return remaining


def _stop() -> None:
    global _wait_since, _waited_out
    _wait_since, _waited_out = None, False


def is_waiting() -> bool:
    """True while Restart & Update waits for Mixar's background work."""
    return _wait_since is not None


def check(eligibility) -> str:
    """May the install go ahead? Main thread.

    Returns ``""`` when it may; otherwise the toast saying why is up and
    the value is apply_and_restart's message. Connectors are ended only
    on the way to ``""``: the AI app would lose its MCP server for nothing
    if the update then stopped, and a background wait polls this every
    BACKGROUND_POLL_S while the user keeps working with that app.
    """
    global _wait_since, _waited_out
    if not _is_windows() or eligibility.location is None:
        return ""
    from . import win_processes

    holders = _holders(eligibility.location.target)
    connectors = [holder for holder in holders if holder.kind in win_processes.ENDED_BY_UPDATE]
    others = [holder for holder in holders if holder.kind not in win_processes.ENDED_BY_UPDATE]
    closable = [holder for holder in others if holder.kind in win_processes.USER_CLOSABLE]
    if closable:
        _stop()
        from .toasts import push_close_apps_toast

        push_close_apps_toast(closable)
        return BLOCKED_BY_OTHER_APPS
    if others and not _waited_out:
        names = ", ".join(sorted({holder.name for holder in others}))
        now = time.monotonic()
        if _wait_since is None:
            _wait_since = now
            logger.info("Update waiting for Mixar background work: %s", names)
            from .toasts import push_background_wait_toast

            push_background_wait_toast()
        elif now - _wait_since >= BACKGROUND_WAIT_MAX_S:
            logger.warning(
                "Mixar background work (%s) still running after %.0fs - updating anyway; "
                "the helper waits for it", names, now - _wait_since)
            # One-shot: the caller re-checks at once, and that check proceeds.
            _wait_since, _waited_out = None, True
            return ""
        if not bpy.app.timers.is_registered(_poll):
            # Persistent: opening a file while waiting would otherwise drop
            # the timer and leave the wait toast up with nothing polling.
            bpy.app.timers.register(_poll, first_interval=BACKGROUND_POLL_S, persistent=True)
        return WAITING_FOR_BACKGROUND

    # The update goes ahead: now the connectors are ended.
    survivors = _end_connectors(connectors)
    _stop()
    if survivors:
        from .toasts import push_close_apps_toast

        push_close_apps_toast(survivors)
        return BLOCKED_BY_OTHER_APPS
    return ""


def reset() -> None:
    """The helper has started: nothing is waiting any more."""
    _stop()


def cancel_wait() -> None:
    """The waiting toast's Cancel: stop waiting. The update stays ready."""
    _stop()
    if bpy.app.timers.is_registered(_poll):
        bpy.app.timers.unregister(_poll)
    info = get_update_state().update_info
    if info is not None:
        from .toasts import push_update_available_toast

        push_update_available_toast(info)


def _poll():
    """Timer: while waiting, re-check; continue the update once it is clear."""
    if _wait_since is None:
        return None
    state = get_update_state()
    if state.install_state is not InstallState.READY:
        _stop()
        return None
    try:
        from .installer import check_eligibility

        verdict = check(check_eligibility(state.update_info))
        if verdict == WAITING_FOR_BACKGROUND:
            return BACKGROUND_POLL_S
        if verdict:
            return None  # a program the user must close appeared; its toast is up
        return _continue()
    except Exception:  # noqa: BLE001 - a timer that raises is unregistered
        logger.error("Update background wait failed", exc_info=True)
        _stop()
        return None


def _continue():
    from .install_flow import apply_and_restart, open_restart_prompt

    if bpy.data.is_dirty:
        # Edits made while waiting must not be quit away: the restart
        # prompt owns the unsaved-work handling.
        open_restart_prompt()
        return None
    started, message = apply_and_restart()
    if message == WAITING_FOR_BACKGROUND:
        return BACKGROUND_POLL_S  # new background work started in between
    if not started and message != BLOCKED_BY_OTHER_APPS:
        from .toasts import refresh_update_toast

        refresh_update_toast()
    return None
