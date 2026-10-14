# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The one browser sign-in in flight, and when it holds the bubble autoshow.

The automatic startup auth check and the manual Sign in button both hand
the user to the browser (loopback OAuth/PKCE) and block a daemon thread on
the callback. At most ONE such attempt is in flight:

- ``begin_sign_in(supersede=True)`` (the button, the MCP dialog, F3)
  replaces a pending attempt: its ``cancel`` event ends the old callback
  wait within a second, so a closed browser tab is never a dead end.
- ``begin_sign_in(supersede=False)`` (the automatic path) returns None
  while one is in flight, so a second browser never opens on its own.
- ``finish_sign_in(attempt_id)`` releases only the attempt that is still
  current; a superseded or stale attempt's exit touches nothing.
- ``cancel_sign_in()`` (the login panel's Cancel) releases the attempt in
  flight at once; its exit then touches nothing either.

Reservation is thread-safe and happens BEFORE the browser opens, so the
autoshow gate needs no main-thread round trip. ``wm.mixie_chat_is_logging_in``
is the UI's mirror of "in flight" (the login panel draws from it), written
on the main thread through ``sync_pending_flag``.

``sign_in_holds_autoshow()`` is the gate the Agent Bubble autoshow entry
points share: opening a bubble window activates the app, so once a sign-in
handed the user to the browser the autoshow waits until Mixar is the active
app again — after a success (``activate_app``), or when the user comes back
on their own after a cancel, a failure or while the browser is still open.
"""

import threading

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

PENDING_FLAG = "mixie_chat_is_logging_in"
APP_ACTIVE_PROP = "mixar_app_active"

_lock = threading.Lock()
_attempt_id = 0
_cancel = None  # the in-flight attempt's cancel Event; None when idle
_browser_handoff = False  # a sign-in sent the user away; cleared once Mixar is active


def begin_sign_in(*, supersede: bool):
    """Reserve the in-flight sign-in. Any thread.

    Returns ``(attempt_id, cancel_event)``, or None when ``supersede`` is
    False and another attempt is already in flight.
    """
    global _attempt_id, _cancel, _browser_handoff
    with _lock:
        if _cancel is not None:
            if not supersede:
                return None
            _cancel.set()
            logger.info("Sign-in attempt %s replaced by a new one", _attempt_id)
        _attempt_id += 1
        _cancel = threading.Event()
        _browser_handoff = True
        return _attempt_id, _cancel


def finish_sign_in(attempt_id, *, cancel: bool = False) -> bool:
    """Release ``attempt_id`` if it is the one in flight. Any thread.

    True when it was (the caller owns the UI outcome); False for a
    superseded or already-finished attempt. ``cancel`` also signals its
    callback wait to stop (the stuck-login watchdog).
    """
    global _cancel
    with _lock:
        if attempt_id != _attempt_id or _cancel is None:
            return False
        if cancel:
            _cancel.set()
        _cancel = None
        return True


def cancel_sign_in() -> bool:
    """The user cancelled the sign-in in flight (the login panel). Any thread.

    Releases it at once, so the panel offers Login with Browser again, and
    signals its callback wait to stop; the flow's own exit then finds it no
    longer current and stays silent. False when nothing was in flight.
    """
    global _cancel
    with _lock:
        if _cancel is None:
            return False
        _cancel.set()
        _cancel = None
        logger.info("Sign-in attempt %s cancelled by the user", _attempt_id)
        return True


def is_current_sign_in(attempt_id) -> bool:
    """``attempt_id`` is still the attempt in flight."""
    with _lock:
        return attempt_id == _attempt_id and _cancel is not None


def sign_in_pending() -> bool:
    """True while a browser sign-in is in flight."""
    with _lock:
        return _cancel is not None


def sync_pending_flag(wm) -> None:
    """Mirror "in flight" onto the UI flag. Main thread only (a bpy write).

    Tolerates a missing window manager and a build without the property;
    every exit of a sign-in flow calls this and none of them may raise.
    """
    if wm is None or not hasattr(wm, PENDING_FLAG):
        return
    try:
        setattr(wm, PENDING_FLAG, sign_in_pending())
    except Exception as exc:  # noqa: BLE001
        logger.debug("sign-in pending flag write failed: %s", exc)


def redraw_sign_in_surfaces(wm) -> None:
    """Redraw everything that shows sign-in state. Main thread only.

    The top bar hosts the Login button and its popover: it is a global area,
    invisible to ``screen.areas``, so it goes through the shared top-bar
    redraw; the Agent Bubble windows are ordinary areas.
    """
    try:
        from mixar.modules.common.updates.ui.topbar_badge import tag_topbar_redraw
        tag_topbar_redraw()
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'AGENT_BUBBLE':
                    area.tag_redraw()
    except Exception as exc:  # noqa: BLE001
        logger.debug("sign-in redraw failed: %s", exc)


def app_is_active():
    """True/False from the native ``wm.mixar_app_active``; None when unknown
    (no context, a build without the property, a MagicMock outside Blender)."""
    try:
        value = getattr(bpy.context.window_manager, APP_ACTIVE_PROP, None)
    except Exception:  # noqa: BLE001
        return None
    return value if isinstance(value, bool) else None


def sign_in_holds_autoshow() -> bool:
    """True while opening a bubble window would pull Mixar over the browser.

    Main thread (reads the window manager). Without a focus signal it falls
    back to holding only while an attempt is in flight.
    """
    global _browser_handoff
    active = app_is_active()
    with _lock:
        in_flight = _cancel is not None
        if active is None:
            return in_flight
        if active:
            # The user is in Mixar: an open bubble steals nothing.
            if not in_flight:
                _browser_handoff = False
            return False
        return in_flight or _browser_handoff
