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
from bpy.app.handlers import persistent

from .constants import (
    ANIMATION_INTERVAL,
    FADE_DURATION_MS,
    TIMER_INTERVAL,
    TOASTS_VISIBLE_WM_PROP,
)

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
        # Wake at the next fade boundary, then paint every frame only while
        # fading. Expiry polling must not quantize a short dissolve to 1–2 frames.
        fades_in = [item.remaining_ms - FADE_DURATION_MS
                    for item in visible if not item.is_sticky]
        _tag_redraw_view3d()
        if not fades_in:
            return TIMER_INTERVAL * 5
        until_fade = min(fades_in) / 1000.0
        return max(ANIMATION_INTERVAL, min(TIMER_INTERVAL, until_fade))

    # No more toasts — stop the timer and remove the draw handler
    with _timer_lock:
        _timer_active = False

    _set_toasts_visible_flag(False)

    from .toast_renderer import remove_draw_handler
    remove_draw_handler()

    # One final redraw to clear the last frame
    _tag_redraw_view3d()
    return None


@persistent
def _resume_after_load(*_args) -> None:
    """A file load (open, revert, checkpoint restore) drops non-persistent timers
    and replaces the WindowManager, taking the WM visibility flag with it. A toast
    still in the store kept drawing but never expired, and the C++ click gate read
    the missing flag as "no toasts": clicks on its buttons fell through to the
    viewport. Restart the machinery for any toast that survived the load."""
    try:
        from .store import get_notification_store
        if get_notification_store().get_visible():
            ensure_toast_timer_running()
        else:
            _set_toasts_visible_flag(False)
    except Exception:
        pass


def _install_load_handler() -> None:
    try:
        if _resume_after_load not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(_resume_after_load)
    except Exception:
        pass


def ensure_toast_timer_running() -> None:
    """Start the toast timer and install the draw handler if not already active.

    Thread-safe — safe to call from the WebSocket thread. The actual timer
    registration is scheduled on the main thread via bpy.app.timers.register().
    """
    global _timer_active

    with _timer_lock:
        _timer_active = True

    def _start_on_main() -> None:
        """Deferred setup that runs on the main thread."""
        from .toast_renderer import install_draw_handler
        install_draw_handler()
        _set_toasts_visible_flag(True)
        _install_load_handler()

        if not bpy.app.timers.is_registered(_toast_tick):
            bpy.app.timers.register(_toast_tick, first_interval=TIMER_INTERVAL)

    # bpy.app.timers.register is main-thread-only, so schedule it. This runs
    # on EVERY push (no _timer_active gate): gating here raced with a tick
    # that was about to self-stop, silently dropping the toast that arrived
    # in that window. _start_on_main is idempotent — install_draw_handler
    # guards on its stored handle and is_registered guards the tick — so
    # re-scheduling is always safe.
    bpy.app.timers.register(_start_on_main, first_interval=0)


def cleanup_toast_timer(app_exit: bool = False) -> None:
    """Unregister the timer and draw handler, and clear all notifications.

    ``app_exit=True`` marks the atexit path: Python finalizes AFTER
    ``BKE_blender_free()`` (see WM_exit_ex), so ``bpy.data`` and the
    spacetype draw-handler registries are already freed — writing the WM
    visibility flag or removing the draw handler there is a use-after-free
    segfault, and neither matters for a dying process. Only silence the
    timer and drop the pure-Python store.
    """
    global _timer_active

    with _timer_lock:
        _timer_active = False

    if bpy.app.timers.is_registered(_toast_tick):
        bpy.app.timers.unregister(_toast_tick)

    if not app_exit:
        _set_toasts_visible_flag(False)

        from .toast_renderer import remove_draw_handler
        remove_draw_handler()

    from .store import get_notification_store
    get_notification_store().reset()
