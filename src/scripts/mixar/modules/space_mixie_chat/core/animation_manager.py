# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat Animation Manager

Manages the unified loader animation for slot-based rendering.
Spinner rotates at 0.5s, text rotates based on per-message loader_rotate_ms.
"""

import json
import time
from mixar.config.logging_config import get_logger
import bpy

logger = get_logger(__name__)

# Timer state
_loader_timer = None
# Per-bubble tracking: bubble_id -> last text rotation timestamp
_text_rotate_times = {}

SPINNER_INTERVAL = 0.5  # Spinner rotation every 0.5s


def _update_loader():
    """
    Timer callback at 0.5s interval.

    - Always rotates spinner for all active loaders.
    - Rotates text only when elapsed time >= loader_rotate_ms.
    """
    try:
        now = time.monotonic()
        needs_animation = False

        for scene in bpy.data.scenes:
            if not hasattr(scene, 'mixie_chat_messages'):
                continue

            for msg in scene.mixie_chat_messages:
                has_loader = msg.loader_visible
                has_active_todo = any(
                    todo.status == 'IN_PROGRESS' for todo in msg.todo_items
                )

                if not has_loader and not has_active_todo:
                    continue

                needs_animation = True

                msg.loader_spinner_index = (msg.loader_spinner_index + 1) % 4

                if has_loader:
                    bubble_id = msg.bubble_id if hasattr(msg, 'bubble_id') else ""
                    key = bubble_id or str(id(msg))

                    if key not in _text_rotate_times:
                        _text_rotate_times[key] = now

                    elapsed_ms = (now - _text_rotate_times[key]) * 1000
                    rotate_ms = msg.loader_rotate_ms if msg.loader_rotate_ms > 0 else 2000

                    if elapsed_ms >= rotate_ms:
                        try:
                            texts = json.loads(msg.loader_texts) if msg.loader_texts else []
                        except json.JSONDecodeError:
                            texts = []
                        if texts:
                            msg.loader_current_index = (msg.loader_current_index + 1) % len(texts)
                        _text_rotate_times[key] = now

        if not needs_animation:
            _text_rotate_times.clear()
            stop_loader_animation()
            return None

        from .queue_processor import is_sse_timer_active
        if not is_sse_timer_active():
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'MIXIE_CHAT':
                        area.tag_redraw()

        return SPINNER_INTERVAL

    except Exception as e:
        logger.error(f"Error in loader update: {e}")
        stop_loader_animation()
        return None


def start_loader_animation():
    """Start the loader animation timer (0.5s interval)."""
    global _loader_timer

    if _loader_timer is not None:
        return

    _loader_timer = True
    if not bpy.app.timers.is_registered(_update_loader):
        bpy.app.timers.register(_update_loader, first_interval=SPINNER_INTERVAL)
        logger.debug("Started loader animation timer (0.5s spinner)")


def stop_loader_animation():
    """Stop the loader animation timer."""
    global _loader_timer

    if _loader_timer is None:
        return

    if bpy.app.timers.is_registered(_update_loader):
        bpy.app.timers.unregister(_update_loader)

    _loader_timer = None
    _text_rotate_times.clear()


def cleanup():
    """Clean up animation resources on module unload."""
    stop_loader_animation()


# ---------------------------------------------------------------------------
# Slide-in redraw burst
# ---------------------------------------------------------------------------
# The C++ side animates a 0.25s slide-in when a new bubble appears, advancing
# it per draw and tagging its own region for redraw. But a tag from inside a
# draw callback does NOT wake Blender's idle event loop — with no input
# events, the next draw only happens on the next timer tick (~250ms), so the
# slide renders ~2 frames and looks stuck. This short ~60fps timer burst
# wakes the loop for the animation window so the slide gets real frames.

SLIDE_REDRAW_INTERVAL = 1.0 / 60.0
SLIDE_REDRAW_DURATION = 0.35  # covers the 0.25s slide with margin
_slide_burst_until = 0.0
_slide_burst_active = False


def _slide_redraw_burst():
    global _slide_burst_active
    try:
        from .ui_utils import redraw_chat_areas
        redraw_chat_areas()
    except Exception:
        _slide_burst_active = False
        return None
    if time.monotonic() >= _slide_burst_until:
        _slide_burst_active = False
        return None
    return SLIDE_REDRAW_INTERVAL


def start_slide_redraw_burst():
    """Drive ~60fps chat redraws briefly after a new bubble is added."""
    global _slide_burst_until, _slide_burst_active
    _slide_burst_until = time.monotonic() + SLIDE_REDRAW_DURATION
    if _slide_burst_active:
        return
    _slide_burst_active = True
    try:
        bpy.app.timers.register(
            _slide_redraw_burst, first_interval=SLIDE_REDRAW_INTERVAL
        )
    except Exception:
        _slide_burst_active = False
