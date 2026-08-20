# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Toast Timer

Manages the bpy.app.timers callback that drives toast expiry and
viewport redraws. The timer self-stops when no toasts remain and
is restarted by NotificationStore.push().
"""

import threading
from typing import Optional

import bpy

from .constants import TIMER_INTERVAL, TOASTS_VISIBLE_WM_PROP

_timer_lock = threading.Lock()
_timer_active = False


def _set_toasts_visible_flag(visible: bool) -> None:
    """Mirror toast visibility into a WM ID property.

    Read by the C++ UI handler (view3d_toast_click.cc) to gate MOUSEMOVE
    forwarding for hover highlights — keeps the per-mousemove cost at zero
    when no toasts are on screen.
    """
    try:
        for wm in bpy.data.window_managers:
            wm[TOASTS_VISIBLE_WM_PROP] = 1 if visible else 0
    except Exception:
        pass


def _tag_redraw_view3d() -> None:
    """Request a redraw of all VIEW_3D areas so toasts update visually."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass


def _toast_tick() -> Optional[float]:
    """Timer callback — expire old toasts and request viewport redraws.

    Returns TIMER_INTERVAL to keep running while toasts exist,
    or None to self-stop when the queue is empty.
    """
    global _timer_active

    from .store import get_notification_store
    store = get_notification_store()

    remaining = store.expire_old()

    if remaining > 0:
        visible = store.get_visible()
        # If all remaining toasts are sticky, use a slower tick rate
        all_sticky = all(item.is_sticky for item in visible)
        _tag_redraw_view3d()
        return TIMER_INTERVAL * 5 if all_sticky else TIMER_INTERVAL

    # No more toasts — stop the timer and remove the draw handler
    with _timer_lock:
        _timer_active = False

    _set_toasts_visible_flag(False)

    from .toast_renderer import remove_draw_handler
    remove_draw_handler()

    # One final redraw to clear the last frame
    _tag_redraw_view3d()
    return None


def ensure_toast_timer_running() -> None:
    """Start the toast timer and install the draw handler if not already active.

    Thread-safe — safe to call from the WebSocket thread. The actual timer
    registration is scheduled on the main thread via bpy.app.timers.register().
    """
    global _timer_active

    with _timer_lock:
        if _timer_active:
            return
        _timer_active = True

    def _start_on_main() -> None:
        """Deferred setup that runs on the main thread."""
        from .toast_renderer import install_draw_handler
        install_draw_handler()
        _set_toasts_visible_flag(True)

        if not bpy.app.timers.is_registered(_toast_tick):
            bpy.app.timers.register(_toast_tick, first_interval=TIMER_INTERVAL)

    # bpy.app.timers.register is main-thread-only, so schedule it
    bpy.app.timers.register(_start_on_main, first_interval=0)


def cleanup_toast_timer() -> None:
    """Unregister the timer and draw handler, and clear all notifications."""
    global _timer_active

    with _timer_lock:
        _timer_active = False

    if bpy.app.timers.is_registered(_toast_tick):
        bpy.app.timers.unregister(_toast_tick)

    _set_toasts_visible_flag(False)

    from .toast_renderer import remove_draw_handler
    remove_draw_handler()

    from .store import get_notification_store
    get_notification_store().reset()
