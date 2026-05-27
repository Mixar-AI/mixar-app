# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bubble window lifecycle helpers.

Window detection, closing restored windows, load/save handlers, and
the _load_autoshow_tick retry loop.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.agent_bubble.core import pill_icons
from mixar.modules.agent_bubble.core.bubble_state import (
    LOAD_AUTOSHOW_RETRY_LIMIT,
)
from . import bubble_state as _st

logger = get_logger(__name__)


def _is_app_exiting() -> bool:
    """Best-effort check for Blender shutting down.

    Blender has no ``bpy.app.is_quitting`` flag, so we probe the window
    manager instead.  If it is gone, unreachable, or empty the app is
    tearing down and no window operations should be attempted.
    """
    try:
        wm = bpy.context.window_manager
        if wm is None or not wm.windows:
            return True
    except Exception:  # noqa: BLE001
        return True
    return False


def is_agent_bubble_window(window) -> bool:
    """Return True when a Blender window contains the runtime bubble UI."""
    try:
        return any(area.type == 'AGENT_BUBBLE' for area in window.screen.areas)
    except ReferenceError:
        return False


def has_agent_bubble_windows() -> bool:
    """Return True when any runtime/saved AGENT_BUBBLE window exists."""
    return any(
        is_agent_bubble_window(window)
        for window in bpy.context.window_manager.windows
    )


def close_restored_agent_bubble_windows() -> int:
    """Close AGENT_BUBBLE windows restored from saved .mixar files.

    Returns the number of windows closed.
    """
    wm = bpy.context.window_manager
    had_bubble = any(is_agent_bubble_window(window) for window in wm.windows)

    native_purge = getattr(
        getattr(bpy.ops, "mixar", None),
        "agent_bubble_purge_windows",
        None,
    )
    if native_purge is not None:
        try:
            result = native_purge()
            if 'CANCELLED' not in result and not any(
                is_agent_bubble_window(window) for window in wm.windows
            ):
                return 1 if had_bubble else 0
            logger.warning("agent_bubble: native purge left bubble windows behind")
        except Exception as e:  # noqa: BLE001
            logger.warning("agent_bubble: native purge failed, falling back: %s", e)

    closed = 0
    for window in list(wm.windows):
        if not is_agent_bubble_window(window):
            continue

        try:
            area = next(
                (area for area in window.screen.areas if area.type == 'AGENT_BUBBLE'),
                None,
            )
            region = None
            if area is not None:
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region is None and area.regions:
                    region = area.regions[0]

            override = {"window": window, "screen": window.screen}
            if area is not None:
                override["area"] = area
            if region is not None:
                override["region"] = region

            with bpy.context.temp_override(**override):
                result = bpy.ops.wm.window_close()
            if 'CANCELLED' not in result:
                closed += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("agent_bubble: failed to close restored bubble window: %s", e)

    return closed


def reset_restored_bubbles_after_load():
    """One-shot load-post timer: purge saved bubble windows, then autoshow."""
    if _is_app_exiting():
        return None

    # Import from the actual definition site, not bootstrap (avoids circular ref).
    from mixar.modules.agent_bubble.core.bubble_autoshow import autoshow_bubble

    if bpy.app.timers.is_registered(autoshow_bubble):
        bpy.app.timers.unregister(autoshow_bubble)
    closed = close_restored_agent_bubble_windows()
    if closed:
        logger.info("agent_bubble: closed %d restored bubble window(s)", closed)
    pill_icons.refresh()
    _st.load_autoshow_attempts = 0
    if not bpy.app.timers.is_registered(load_autoshow_tick):
        bpy.app.timers.register(load_autoshow_tick, first_interval=0.1)
    return None


_load_autoshow_in_progress = False


def load_autoshow_tick():
    """Retry opening a clean bubble after loading an existing .mixar file."""
    global _load_autoshow_in_progress
    if _load_autoshow_in_progress:
        return 0.3
    _load_autoshow_in_progress = True
    try:
        return _load_autoshow_tick_inner()
    finally:
        _load_autoshow_in_progress = False


def _load_autoshow_tick_inner():
    if _is_app_exiting():
        _st.load_autoshow_attempts = 0
        return None

    from mixar.modules.agent_bubble.core.bubble_autoshow import try_invoke_bubble as _try_invoke_bubble

    _st.load_autoshow_attempts += 1

    try:
        from mixar.bootstrap import splash_menu
        if splash_menu.is_splash_visible():
            _st.load_autoshow_attempts -= 1
            return 0.3
    except Exception:  # noqa: BLE001
        pass

    if has_agent_bubble_windows():
        closed = close_restored_agent_bubble_windows()
        if closed:
            return 0.25  # let close settle before invoke

    if _try_invoke_bubble(start_minimised=False):
        logger.info(
            "agent_bubble: shown after file load on attempt %d",
            _st.load_autoshow_attempts,
        )
        _st.load_autoshow_attempts = 0
        return None

    if _st.load_autoshow_attempts >= LOAD_AUTOSHOW_RETRY_LIMIT:
        logger.warning(
            "agent_bubble: file-load autoshow gave up after %d attempts",
            _st.load_autoshow_attempts,
        )
        _st.load_autoshow_attempts = 0
        return None

    return 0.25


@persistent
def on_save_pre(_dummy_arg) -> None:
    """Prevent runtime bubble/pill windows from being serialized."""
    closed = close_restored_agent_bubble_windows()
    _st.closed_for_save = closed > 0
    if closed:
        logger.info("agent_bubble: closed %d runtime bubble window(s) before save", closed)


def restore_bubble_after_save():
    """One-shot timer used after save so the overlay returns cleanly."""
    _st.closed_for_save = False
    if _is_app_exiting():
        return None
    pill_icons.refresh()
    _st.load_autoshow_attempts = 0
    if not bpy.app.timers.is_registered(load_autoshow_tick):
        bpy.app.timers.register(load_autoshow_tick, first_interval=0.1)
    return None


@persistent
def on_save_post(_dummy_arg) -> None:
    """Recreate the bubble after save if save_pre removed it."""
    if not _st.closed_for_save:
        return
    if not bpy.app.timers.is_registered(restore_bubble_after_save):
        bpy.app.timers.register(restore_bubble_after_save, first_interval=0.1)
