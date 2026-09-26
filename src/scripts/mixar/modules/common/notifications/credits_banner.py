# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Out-of-Credits Banner

Every "you ran out of credits" signal — the backend's ``credit_upgrade``
push, a REST 402 from any service, the agent chat's 402 fallbacks — asks for
the same whole-window banner here instead of a toast. The banner itself is
native (``MIXAR_OT_credits_banner``, a blocking modal with a window draw
callback); this module decides WHEN it opens and owns what its buttons do
(``ui/operators/credits_banner_ops.py``).

Thread-safe: ``request_credits_banner`` may run on the WebSocket or a job
thread; the open always happens on the main thread through a timer.

Rules:
* one banner at a time (the native operator refuses a second);
* a burst of failures (a batch of jobs, the push + the chat fallback for the
  same turn) opens it once — requests inside ``BURST_COOLDOWN_S`` of the last
  open or close are dropped;
* the backend push is not deduplicated server-side (one failed action can
  push more than once) and carries no id today, so the burst window is what
  collapses it; a push that does carry an id opens it at most once per
  session;
* it waits for the onboarding tour, like toasts do.
"""

import os
import threading
import time
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger

from .constants import (
    CREDITS_BANNER_ASSET,
    CREDITS_BANNER_BURST_COOLDOWN_S,
    CREDITS_BANNER_TOUR_POLL_S,
)

logger = get_logger(__name__)

_lock = threading.Lock()
_last_activity = 0.0  # monotonic time of the last open or close
_pending_trigger: Optional[str] = None
_seen_push_ids: set = set()


def banner_image_path() -> str:
    """Absolute path of the bundled banner art."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CREDITS_BANNER_ASSET)


def request_credits_banner(
    trigger: str,
    action_url: Optional[str] = None,
    push_id: Optional[str] = None,
) -> None:
    """Ask for the out-of-credits banner (any thread).

    Args:
        trigger: Short content-free source tag for telemetry
            (``push``, ``http_402``, ``chat``, ``job``, ``mask_tool``).
        action_url: Backend-supplied manage-subscription URL, if any; the
            Upgrade button opens it.
        push_id: Backend notification id, if the push carries one; the same
            id never reopens the banner.
    """
    global _pending_trigger
    if action_url:
        try:
            from .credit_upgrade import set_pending_upgrade_url

            set_pending_upgrade_url(action_url)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Credits banner: upgrade URL stash skipped: %s", exc)

    if getattr(bpy.app, "background", False):
        return
    with _lock:
        if push_id:
            if push_id in _seen_push_ids:
                return
            _seen_push_ids.add(push_id)
        if time.monotonic() - _last_activity < CREDITS_BANNER_BURST_COOLDOWN_S:
            return
        if _pending_trigger is not None:
            return
        _pending_trigger = trigger
    try:
        bpy.app.timers.register(_open_on_main, first_interval=0)
    except Exception as exc:  # noqa: BLE001 — timers unavailable at shutdown
        with _lock:
            _pending_trigger = None
        logger.debug("Credits banner: open not scheduled: %s", exc)


def note_banner_closed() -> None:
    """Start the burst cooldown from the moment the user closed the banner."""
    global _last_activity
    with _lock:
        _last_activity = time.monotonic()


def _main_window():
    """The window the user is working in when it is a main window (not the
    island's temporary overlay), else the first main window."""
    wm = bpy.context.window_manager
    if wm is None:
        return None
    active = getattr(bpy.context, "window", None)
    if active is not None and active.screen is not None and not active.screen.is_temporary:
        return active
    for window in wm.windows:
        screen = window.screen
        if screen is not None and not screen.is_temporary:
            return window
    return None


def _minimise_agent_island() -> None:
    """The island is an always-on-top OS window; tuck it into its pill so it
    never covers the banner."""
    try:
        op = getattr(bpy.ops.mixar, "bubble_minimise", None)
        if op is not None and op.poll():
            op()
    except Exception as exc:  # noqa: BLE001 — cosmetic, never block the banner
        logger.debug("Credits banner: island minimise skipped: %s", exc)


def _open_on_main():
    global _pending_trigger, _last_activity
    try:
        from mixar.modules.common.utils.tour import tour_running

        if tour_running():
            return CREDITS_BANNER_TOUR_POLL_S
    except Exception:  # noqa: BLE001
        pass

    with _lock:
        trigger = _pending_trigger or "unknown"
        _pending_trigger = None

    window = _main_window()
    if window is None:
        logger.warning("Credits banner: no main window to show it in")
        return None

    _minimise_agent_island()
    try:
        with bpy.context.temp_override(window=window):
            result = bpy.ops.mixar.credits_banner(
                'INVOKE_DEFAULT', image_path=banner_image_path(),
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("Credits banner failed to open: %s", exc)
        return None

    if 'RUNNING_MODAL' not in result:
        return None  # already open
    with _lock:
        _last_activity = time.monotonic()
    logger.info("Credits banner shown (trigger=%s)", trigger)
    try:
        from mixar.modules.common.analytics.credits_events import (
            capture_credits_banner_shown,
        )

        capture_credits_banner_shown(trigger, context=bpy.context)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Credits banner telemetry skipped: %s", exc)
    return None


def reset_state() -> None:
    """Forget cooldown and replay state (tests and the manual show operator)."""
    global _last_activity, _pending_trigger
    with _lock:
        _last_activity = 0.0
        _pending_trigger = None
        _seen_push_ids.clear()
