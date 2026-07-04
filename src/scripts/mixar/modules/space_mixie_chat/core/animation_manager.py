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

                # Subscript write: skips rna_property_update, which would
                # otherwise tag the Scene depsgraph and broadcast NC_WINDOW
                # (full-app redraw) twice a second for the whole duration of
                # an agent run. The explicit tag_redraw below repaints the
                # chat surfaces; nothing else reads this property.
                msg["loader_spinner_index"] = (msg.loader_spinner_index + 1) % 4

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
                            msg["loader_current_index"] = (msg.loader_current_index + 1) % len(texts)
                        _text_rotate_times[key] = now

        if not needs_animation:
            _text_rotate_times.clear()
            stop_loader_animation()
            return None

        from .queue_processor import is_sse_timer_active
        if not is_sse_timer_active():
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    # The loader/spinner renders both in the MIXIE_CHAT
                    # editor and in the floating agent bubble. Tag both (and
                    # the bubble's regions) so the animation advances no
                    # matter which surface is on screen — in Zen Mode only
                    # the bubble is visible, so tagging MIXIE_CHAT alone left
                    # the dots static until the user interacted.
                    if area.type == 'MIXIE_CHAT':
                        area.tag_redraw()
                    elif area.type == 'AGENT_BUBBLE':
                        area.tag_redraw()
                        for region in area.regions:
                            region.tag_redraw()

        return SPINNER_INTERVAL

    except Exception as e:
        logger.error(f"Error in loader update: {e}")
        stop_loader_animation()
        return None


def start_loader_animation():
    """Start the loader animation timer (0.5s interval).

    Keys off the real ``bpy.app.timers.is_registered`` state rather than
    the ``_loader_timer`` flag. Blender silently unregisters non-persistent
    timers on file load, which leaves ``_loader_timer`` stale-True while no
    timer is actually running — a plain flag guard would then early-return
    and the loader would never animate in the new file ("sometimes the
    running animation doesn't work"). Re-deriving from is_registered makes
    this self-healing across file loads while staying idempotent.
    """
    global _loader_timer

    if not bpy.app.timers.is_registered(_update_loader):
        bpy.app.timers.register(_update_loader, first_interval=SPINNER_INTERVAL)
        logger.debug("Started loader animation timer (0.5s spinner)")

    _loader_timer = True


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
# Slide-in kick-off
# ---------------------------------------------------------------------------
# The C++ side animates a 0.25s slide-in when a new bubble appears. Animation
# FRAMES are delivered natively by the C++ animation pump (a TIMERNOTIFIER
# wmTimer in mixie_chat_main_region.cc) — this function only guarantees the
# FIRST draw happens right after the message is added, which is the draw that
# detects the new message, starts the slide, and spins the pump up.
#
# Historical note: this used to be a ~60fps bpy.app.timers redraw burst. That
# frame pump was fragile (starved behind main-thread work, capped at 0.35s,
# and each tick scheduled bubble-resize sync work — see the post-submit-hang
# incident). Do NOT reintroduce a Python frame pump here; the C++ pump owns
# frame delivery.


def start_slide_redraw_burst():
    """Tag the chat surfaces once so the slide-in's first frame draws now."""
    try:
        from .ui_utils import _tag_chat_and_bubble_areas
        _tag_chat_and_bubble_areas()
    except Exception:
        pass
