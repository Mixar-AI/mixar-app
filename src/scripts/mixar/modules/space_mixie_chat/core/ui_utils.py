# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI utility functions for Mixie Chat."""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_sync_timers_pending = False
_deferred_force_attachment = False
# Pending-attachment count at the last executed sync. The deferred sync
# runs after every SSE batch via redraw_chat_areas(); invoking the C++
# operator unconditionally forced an ED_screen_refresh of the bubble
# window every ~0.1 s during streaming. Skipping when the count is
# unchanged keeps the refresh for real attachment changes only.
_last_synced_attachment_count = -1


def _pending_attachment_count() -> int:
    try:
        scene = bpy.context.scene
        attachments = getattr(scene, "mixie_chat_pending_attachments", None)
        return len(attachments) if attachments is not None else 0
    except Exception:
        return -1


def _sync_bubble_attachment_size(force_attachment_height=False):
    sync_op = getattr(getattr(bpy.ops, "mixar", None),
                      "bubble_sync_attachment_size",
                      None)
    if sync_op is None:
        return None
    # The C++ operator locates the bubble window/region itself via
    # g_bubble_ghostwin, so we deliberately avoid temp_override here:
    # invoking it from a timer with an override context while the
    # operator synchronously calls ED_screen_refresh re-enters Python
    # context resolution with a half-applied override stack, which
    # corrupts interpreter state and segfaults inside PyUnicode_New.
    try:
        sync_op(force_attachment_height=force_attachment_height)
    except Exception:
        logger.debug("bubble attachment sync failed", exc_info=True)
    return None


def _tag_chat_and_bubble_areas():
    """Tag all MIXIE_CHAT and AGENT_BUBBLE areas for redraw."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'MIXIE_CHAT', 'AGENT_BUBBLE'}:
                    area.tag_redraw()
    except Exception:
        pass


def _deferred_sync_callback():
    global _sync_timers_pending, _deferred_force_attachment
    global _last_synced_attachment_count
    _sync_timers_pending = False
    force = _deferred_force_attachment
    _deferred_force_attachment = False
    count = _pending_attachment_count()
    if force or count != _last_synced_attachment_count:
        _last_synced_attachment_count = count
        _sync_bubble_attachment_size(force_attachment_height=force)
    # Always tag areas for redraw so thumbnails render even when the
    # bubble size didn't change (the C++ sync early-returns in that case
    # without tagging a redraw).
    _tag_chat_and_bubble_areas()
    return None


def sync_bubble_attachment_size_deferred(force_attachment_height=False):
    """Run bubble attachment sizing now and again after UI state settles.

    When *force_attachment_height* is True the sync runs immediately so the
    bubble pre-sizes in the same frame as the image add — before the pending-
    attachment list has settled.  A deferred follow-up handles the final
    adjustment once the UI layout is up to date.
    """
    global _sync_timers_pending, _deferred_force_attachment

    if force_attachment_height:
        # Pre-size immediately — the attachment count may not reflect the
        # new image yet, so only the force path can trigger the height floor.
        _sync_bubble_attachment_size(force_attachment_height=True)
        # Escalate the deferred pass to force mode even if the timer was
        # already registered by a non-force caller.
        _deferred_force_attachment = True

    if _sync_timers_pending:
        return
    _sync_timers_pending = True
    if force_attachment_height:
        _deferred_force_attachment = True
    try:
        bpy.app.timers.register(
            _deferred_sync_callback,
            first_interval=0.1,
        )
    except Exception:
        _sync_timers_pending = False
        logger.debug("failed to register bubble sync timer", exc_info=True)


def bump_layout_epoch(scene) -> None:
    """Force the C++ chat layout cache to rebuild on the next draw.

    The cache only invalidates on message-count / width / stream changes, so
    anything that changes a bubble's height in place (collapse toggles, step
    rows appearing, thinking finalization) must bump this scene counter.
    """
    try:
        scene.mixie_chat_layout_epoch = scene.mixie_chat_layout_epoch + 1
    except Exception:
        logger.debug("failed to bump chat layout epoch", exc_info=True)


def redraw_chat_areas():
    """Redraw all Mixie chat surfaces across all windows.

    Safe to call from any context (timers, operators, callbacks).
    Uses window_manager.windows to handle multi-window setups.
    """
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'MIXIE_CHAT', 'AGENT_BUBBLE'}:
                    area.tag_redraw()
                    for region in area.regions:
                        region.tag_redraw()
        sync_bubble_attachment_size_deferred()
    except Exception:
        pass
