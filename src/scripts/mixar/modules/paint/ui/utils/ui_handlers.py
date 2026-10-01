# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI update handlers for Mixar layers system

Since Properties panels have read-only context during draw, we use:
1. Depsgraph handlers to detect backend changes
2. msgbus subscriptions to monitor property changes
3. Timers to trigger UI updates outside of draw context
"""

import bpy
from bpy.app.handlers import persistent

from .ui_refresh import simple_update_mixar_tree_ui
from .....config.logging_config import get_logger

logger = get_logger(__name__)


_update_timer_registered = False
_needs_update = False

# State tracking for targeted depsgraph handler
_prev_active_object_name = ""
_prev_material_slots_count = 0


def mark_ui_needs_update():
    """Mark that UI needs update - safe to call from anywhere"""
    global _needs_update
    _needs_update = True


def _ui_update_timer():
    """Timer function that runs UI updates outside of draw context"""
    global _needs_update

    if not _needs_update:
        return 0.1  # Check again in 0.1 seconds

    # Import here to avoid circular imports

    try:
        context = bpy.context
        # Only update if we have a valid context
        wm = getattr(context, 'window_manager', None)
        if context and context.scene and wm:
            # Check if mixar_ui exists
            if hasattr(wm, 'mixar_ui'):
                mixar_ui = wm.mixar_ui

                # Only proceed if an update is actually needed
                if mixar_ui.needs_ui_refresh or _needs_update:
                    simple_update_mixar_tree_ui(context)
                    mixar_ui.needs_ui_refresh = False
                    _needs_update = False
    except KeyboardInterrupt:
        # Gracefully stop the timer on shutdown
        return None
    except BaseException as e:
        # Catch all exceptions including SystemExit - don't break Blender
        logger.error("Mixar UI update error: %s", e)

    return 0.1  # Check again in 0.1 seconds


@persistent
def on_depsgraph_update_post(scene, depsgraph):
    """Handler for depsgraph updates - detects backend changes

    This is called after any scene changes. We check if Mixar-relevant
    data has changed (materials, nodes, etc.) and request UI refresh.
    """
    # Check if any updates affect Mixar
    for update in depsgraph.updates:
        # Check for material or node tree changes
        if update.id.bl_rtype in {'MATERIAL', 'NODETREE', 'OBJECT'}:
            mark_ui_needs_update()
            break


@persistent
def on_depsgraph_update_post_targeted(scene, depsgraph):
    """Targeted depsgraph handler for object/material changes only.

    Unlike on_depsgraph_update_post which iterates over all updates,
    this handler only checks if the active object or its material slots
    have changed. This is much more lightweight and catches:
    - Model imports (new objects get auto-selected)
    - Object selection changes
    - Material slot additions/removals
    """
    global _prev_active_object_name, _prev_material_slots_count

    try:
        obj = bpy.context.active_object
        current_name = obj.name if obj else ""
        current_slots = len(obj.material_slots) if obj else 0

        if (current_name != _prev_active_object_name or
                current_slots != _prev_material_slots_count):
            _prev_active_object_name = current_name
            _prev_material_slots_count = current_slots
            mark_ui_needs_update()
            # Force redraw of Texture Sets space and other relevant areas
            _tag_texture_sets_redraw()
    except Exception:
        pass  # Ignore errors during context access


def _tag_texture_sets_redraw():
    """Tag Texture Sets space regions for redraw.

    Blender doesn't automatically redraw custom space types on depsgraph
    updates, so we need to manually tag them for redraw.
    """
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'TEXTURE_SETS':
                    area.tag_redraw()
    except Exception:
        pass  # Ignore errors if context is invalid


@persistent
def on_load_post(dummy):
    """Handler for file load - refresh UI and restore preferences after loading"""
    global _prev_active_object_name, _prev_material_slots_count
    _prev_active_object_name = ""
    _prev_material_slots_count = 0
    mark_ui_needs_update()

    # Restore persisted preferences into the newly loaded scene so that
    # user settings are not lost when switching .blend files.
    try:
        from ...utils.preferences_config import load_preferences
        load_preferences()
    except Exception as exc:
        logger.warning("Failed to load Mixar Paint preferences on file load: %s", exc)


@persistent
def on_undo_post(dummy):
    """Handler for undo - refresh UI after undo"""
    mark_ui_needs_update()


@persistent
def on_redo_post(dummy):
    """Handler for redo - refresh UI after redo"""
    mark_ui_needs_update()


def register():
    """Register UI update handlers.

    This function is idempotent - safe to call multiple times.
    """
    global _update_timer_registered

    # Register depsgraph handler (commented out for now - too aggressive)
    # bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update_post)

    # Register targeted depsgraph handler (lightweight - only tracks object/material changes)
    if on_depsgraph_update_post_targeted not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update_post_targeted)

    # Register file handlers (only if not already registered)
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)
    if on_undo_post not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(on_undo_post)
    if on_redo_post not in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.append(on_redo_post)

    # Register timer for periodic UI updates
    if not _update_timer_registered:
        bpy.app.timers.register(_ui_update_timer, persistent=True)
        _update_timer_registered = True

    # Load persisted preferences into the current scene at startup so that
    # settings are immediately available without requiring a file reload.
    try:
        from ...utils.preferences_config import load_preferences
        load_preferences()
    except Exception as exc:
        logger.warning("Failed to load Mixar Paint preferences at startup: %s", exc)


def unregister():
    """Unregister UI update handlers"""
    global _update_timer_registered

    # Unregister depsgraph handler
    # if on_depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
    #     bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_update_post)

    # Unregister targeted depsgraph handler
    if on_depsgraph_update_post_targeted in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_update_post_targeted)

    # Unregister file handlers
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)

    if on_undo_post in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.remove(on_undo_post)

    if on_redo_post in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.remove(on_redo_post)

    # Unregister timer
    if _update_timer_registered and bpy.app.timers.is_registered(_ui_update_timer):
        bpy.app.timers.unregister(_ui_update_timer)
        _update_timer_registered = False
