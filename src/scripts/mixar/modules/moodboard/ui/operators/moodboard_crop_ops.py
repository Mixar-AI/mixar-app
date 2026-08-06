# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Crop Tool Operators

Operators for cropping images in the moodboard.
Uses a transform-style 8-handle interaction for defining the crop region.
"""

import bpy
from bpy.types import Operator

from ...core.moodboard_utils import (
    validate_selection_region,
    reset_tool_state,
    find_crop_handle_at_mouse,
    mouse_to_image_coords_unclamped,
)
from ...core.media_utils import is_still_item


# Minimum gap to prevent handles from crossing each other (in 0-1 space)
_MIN_CROP_SIZE = 0.02

# Cursor type per handle index, matching C++ resize handle convention
# Corners: 4-way scroll, Edges: axis-constrained scroll
_HANDLE_CURSORS = {
    0: 'SCROLL_XY',   # bottom-left corner
    1: 'SCROLL_XY',   # bottom-right corner
    2: 'SCROLL_XY',   # top-right corner
    3: 'SCROLL_XY',   # top-left corner
    4: 'SCROLL_Y',    # bottom edge
    5: 'SCROLL_X',    # right edge
    6: 'SCROLL_Y',    # top edge
    7: 'SCROLL_X',    # left edge
}


def _apply_handle_drag(state, handle, rel_x, rel_y):
    """
    Update crop box coordinates based on which handle is being dragged.

    Clamps values to 0-1 range and prevents handles from crossing.
    """
    x1 = min(state.box_start_x, state.box_end_x)
    x2 = max(state.box_start_x, state.box_end_x)
    y1 = min(state.box_start_y, state.box_end_y)
    y2 = max(state.box_start_y, state.box_end_y)

    # Clamp the incoming coordinate to image bounds
    rel_x = max(0.0, min(1.0, rel_x))
    rel_y = max(0.0, min(1.0, rel_y))

    if handle == 0:    # bottom-left corner
        x1 = min(rel_x, x2 - _MIN_CROP_SIZE)
        y1 = min(rel_y, y2 - _MIN_CROP_SIZE)
    elif handle == 1:  # bottom-right corner
        x2 = max(rel_x, x1 + _MIN_CROP_SIZE)
        y1 = min(rel_y, y2 - _MIN_CROP_SIZE)
    elif handle == 2:  # top-right corner
        x2 = max(rel_x, x1 + _MIN_CROP_SIZE)
        y2 = max(rel_y, y1 + _MIN_CROP_SIZE)
    elif handle == 3:  # top-left corner
        x1 = min(rel_x, x2 - _MIN_CROP_SIZE)
        y2 = max(rel_y, y1 + _MIN_CROP_SIZE)
    elif handle == 4:  # bottom edge
        y1 = min(rel_y, y2 - _MIN_CROP_SIZE)
    elif handle == 5:  # right edge
        x2 = max(rel_x, x1 + _MIN_CROP_SIZE)
    elif handle == 6:  # top edge
        y2 = max(rel_y, y1 + _MIN_CROP_SIZE)
    elif handle == 7:  # left edge
        x1 = min(rel_x, x2 - _MIN_CROP_SIZE)

    state.box_start_x = x1
    state.box_start_y = y1
    state.box_end_x = x2
    state.box_end_y = y2


def _set_cursor_for_handle(context, handle):
    """Set the window cursor to match the handle being hovered/dragged."""
    cursor = _HANDLE_CURSORS.get(handle, 'CROSSHAIR')
    context.window.cursor_modal_set(cursor)


class MIXIE_OT_moodboard_crop_tool(Operator):
    """Activate crop tool - drag handles to define crop region, Enter to apply"""
    bl_idname = "mixie.moodboard_crop_tool"
    bl_label = "Crop Tool"
    bl_options = {'REGISTER', 'BLOCKING'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'mixie_moodboard_images'):
            return False
        selected = [i for i, img in enumerate(context.scene.mixie_moodboard_images)
                    if img.selected and is_still_item(img)]
        return len(selected) == 1

    def modal(self, context, event):
        state = context.scene.mixie_edit_tool_state

        # ESC to cancel
        if event.type == 'ESC':
            context.window.cursor_modal_restore()
            state.active_tool = 'NONE'
            state.is_drawing = False
            state.active_handle = -1
            state.target_image_index = -1
            context.area.tag_redraw()
            return {'CANCELLED'}

        # Enter to apply crop
        if event.type == 'RET' and event.value == 'PRESS':
            context.window.cursor_modal_restore()
            bpy.ops.mixie.moodboard_apply_crop()
            return {'FINISHED'}

        # Left mouse press - find handle and start dragging
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            handle = find_crop_handle_at_mouse(
                context, event, state, state.target_image_index
            )
            if handle >= 0:
                state.active_handle = handle
                state.is_drawing = True
                _set_cursor_for_handle(context, handle)
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Left mouse release - stop dragging
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            state.active_handle = -1
            state.is_drawing = False
            # Check if still hovering a handle after release
            hover = find_crop_handle_at_mouse(
                context, event, state, state.target_image_index
            )
            if hover >= 0:
                _set_cursor_for_handle(context, hover)
            else:
                context.window.cursor_modal_set('CROSSHAIR')
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Mouse move
        if event.type == 'MOUSEMOVE':
            if state.is_drawing and state.active_handle >= 0:
                # Dragging a handle - update crop bounds
                coords = mouse_to_image_coords_unclamped(
                    context, event, state.target_image_index
                )
                if coords:
                    _apply_handle_drag(state, state.active_handle, coords[0], coords[1])
                    context.area.tag_redraw()
            else:
                # Not dragging - update hover cursor
                hover = find_crop_handle_at_mouse(
                    context, event, state, state.target_image_index
                )
                if hover >= 0:
                    _set_cursor_for_handle(context, hover)
                else:
                    context.window.cursor_modal_set('CROSSHAIR')
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        # Find the selected image
        selected_idx = -1
        for i, img in enumerate(scene.mixie_moodboard_images):
            if img.selected and is_still_item(img):
                selected_idx = i
                break

        if selected_idx < 0:
            self.report({'WARNING'}, "No image selected")
            return {'CANCELLED'}

        # Initialize state - crop frame starts inset from the image edges
        # so the user can clearly see the crop region is active and distinct
        # from the image border. User can still drag handles to the edges.
        _INITIAL_INSET = 0.05
        state.active_tool = 'CROP'
        state.target_image_index = selected_idx
        state.box_start_x = _INITIAL_INSET
        state.box_start_y = _INITIAL_INSET
        state.box_end_x = 1.0 - _INITIAL_INSET
        state.box_end_y = 1.0 - _INITIAL_INSET
        state.is_drawing = False
        state.active_handle = -1

        # Set initial cursor to crosshair to indicate crop mode
        context.window.cursor_modal_set('CROSSHAIR')

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        self.report({'INFO'}, "Drag handles to adjust crop region. Enter to apply, ESC to cancel.")
        return {'RUNNING_MODAL'}


class MIXIE_OT_moodboard_apply_crop(Operator):
    """Apply the crop to the selected image"""
    bl_idname = "mixie.moodboard_apply_crop"
    bl_label = "Apply Crop"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'mixie_edit_tool_state'):
            return False
        state = context.scene.mixie_edit_tool_state
        return state.active_tool == 'CROP' and state.target_image_index >= 0

    def execute(self, context):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        if state.target_image_index < 0 or state.target_image_index >= len(scene.mixie_moodboard_images):
            self.report({'ERROR'}, "Invalid image index")
            return {'CANCELLED'}

        # Validate crop region has minimum size
        is_valid, x1, y1, x2, y2 = validate_selection_region(state)
        if not is_valid:
            self.report({'WARNING'}, "Crop region too small. Please draw a larger selection.")
            reset_tool_state(state, context)
            return {'CANCELLED'}

        # Call the C++ accelerated operator
        bpy.ops.mixie.moodboard_crop_image(
            image_index=state.target_image_index,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2
        )

        reset_tool_state(state, context)
        self.report({'INFO'}, "Cropped image (C++ accelerated)")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_crop_tool,
    MIXIE_OT_moodboard_apply_crop,
)
