# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Mask Tool Operators

Operators for creating box and lasso masks in the moodboard.
"""

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty

from ...constants import (
    MOODBOARD_IMAGE_BASE_SIZE,
    MOODBOARD_IMAGE_SPACING,
    LASSO_MIN_DISTANCE_THRESHOLD,
    LASSO_MIN_POINTS,
)
from ...core.moodboard_utils import (
    mouse_to_image_coords,
    validate_selection_region,
    reset_tool_state,
)


def _auto_trigger_box_sam():
    """Auto-trigger box SAM segmentation after box mask is drawn."""
    try:
        if bpy.ops.mixie.box_select_sam.poll():
            bpy.ops.mixie.box_select_sam('INVOKE_DEFAULT')
    except Exception:
        pass
    return None  # one-shot timer


class MIXIE_OT_moodboard_box_mask_tool(Operator):
    """Activate box mask tool - click and drag on image to draw mask region"""
    bl_idname = "mixie.moodboard_box_mask_tool"
    bl_label = "Box Mask Tool"
    bl_description = "Activate box mask tool - click and drag to draw mask region (M)"
    bl_options = {'REGISTER', 'BLOCKING'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'mixie_moodboard_images'):
            return False
        selected = [i for i, img in enumerate(context.scene.mixie_moodboard_images)
                    if img.selected and img.image]
        return len(selected) == 1

    def modal(self, context, event):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        # Handle ESC to cancel
        if event.type == 'ESC':
            state.active_tool = 'NONE'
            state.is_drawing = False
            state.target_image_index = -1
            state.box_select_has_selection = False
            state.box_select_pending = False
            context.area.tag_redraw()
            return {'CANCELLED'}

        # Handle left mouse for drawing
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                # Start drawing - convert mouse to image-relative coords
                img_rel = mouse_to_image_coords(context, event, state.target_image_index)
                if img_rel:
                    state.box_start_x = img_rel[0]
                    state.box_start_y = img_rel[1]
                    state.box_end_x = img_rel[0]
                    state.box_end_y = img_rel[1]
                    state.is_drawing = True
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            elif event.value == 'RELEASE':
                if state.is_drawing:
                    state.is_drawing = False
                    # Apply mask on mouse release
                    bpy.ops.mixie.moodboard_apply_box_mask(invert=False)
                    # Mark selection as ready for SAM processing
                    state.box_select_has_selection = True
                    context.area.tag_redraw()
                    # Auto-trigger SAM segmentation
                    bpy.app.timers.register(
                        lambda: _auto_trigger_box_sam(), first_interval=0.0
                    )
                    return {'FINISHED'}
                return {'RUNNING_MODAL'}

        # Handle mouse move while drawing
        if event.type == 'MOUSEMOVE' and state.is_drawing:
            img_rel = mouse_to_image_coords(context, event, state.target_image_index)
            if img_rel:
                state.box_end_x = img_rel[0]
                state.box_end_y = img_rel[1]
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Handle Enter to apply mask (non-inverted) - kept as fallback
        if event.type == 'RET' and event.value == 'PRESS':
            bpy.ops.mixie.moodboard_apply_box_mask(invert=False)
            return {'FINISHED'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        # Track active tab for operator state
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            scene.mixie_moodboard_sidebar.active_tab = 'SEGMENTATION'
            scene.mixie_moodboard_sidebar.segmentation_subtab = 'SEGMENT_TO_3D'

        # Find the selected image
        selected_idx = -1
        for i, img in enumerate(scene.mixie_moodboard_images):
            if img.selected and img.image:
                selected_idx = i
                break

        if selected_idx < 0:
            self.report({'WARNING'}, "No image selected")
            return {'CANCELLED'}

        # Initialize state
        state.active_tool = 'BOX_MASK'
        state.target_image_index = selected_idx
        state.box_start_x = 0.0
        state.box_start_y = 0.0
        state.box_end_x = 1.0
        state.box_end_y = 1.0
        state.is_drawing = False

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        self.report({'INFO'}, "Click and drag on image to draw mask region. Enter to apply, ESC to cancel.")
        return {'RUNNING_MODAL'}


class MIXIE_OT_moodboard_apply_box_mask(Operator):
    """Apply box mask to create a masked image"""
    bl_idname = "mixie.moodboard_apply_box_mask"
    bl_label = "Apply Box Mask"
    bl_options = {'REGISTER', 'UNDO'}

    invert: BoolProperty(
        name="Invert",
        description="Invert the mask (keep outside, remove inside)",
        default=False
    )

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'mixie_edit_tool_state'):
            return False
        state = context.scene.mixie_edit_tool_state
        return state.active_tool == 'BOX_MASK' and state.target_image_index >= 0

    def execute(self, context):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        if state.target_image_index < 0 or state.target_image_index >= len(scene.mixie_moodboard_images):
            self.report({'ERROR'}, "Invalid image index")
            return {'CANCELLED'}

        # Validate mask region has minimum size
        is_valid, x1, y1, x2, y2 = validate_selection_region(state)
        if not is_valid:
            self.report({'WARNING'}, "Mask region too small. Please draw a larger selection.")
            reset_tool_state(state, context)
            return {'CANCELLED'}

        img_item = scene.mixie_moodboard_images[state.target_image_index]

        # Track moodboard count before C++ operator
        count_before = len(scene.mixie_moodboard_images)

        # Calculate offset for placing mask next to original
        offset_x = (MOODBOARD_IMAGE_BASE_SIZE * img_item.scale) + MOODBOARD_IMAGE_SPACING

        # Call the C++ accelerated operator
        result = bpy.ops.mixie.moodboard_generate_box_mask(
            image_index=state.target_image_index,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            invert=self.invert,
            offset_x=offset_x
        )

        # Remove mask from moodboard (we don't want to display it)
        # The mask is created by C++ but we only need the selection coords for SAM
        if result == {'FINISHED'} and len(scene.mixie_moodboard_images) > count_before:
            # Get the newly added mask item (last one)
            mask_item = scene.mixie_moodboard_images[-1]
            mask_image = mask_item.image
            # Remove from moodboard collection
            scene.mixie_moodboard_images.remove(len(scene.mixie_moodboard_images) - 1)
            # Remove the mask image from bpy.data.images
            if mask_image:
                try:
                    bpy.data.images.remove(mask_image)
                except:
                    pass

        # Don't reset tool state - keep box coords for SAM processing
        # The SAM operator will reset state after processing
        context.area.tag_redraw()
        self.report({'INFO'}, "Box selection ready for segmentation")
        return {'FINISHED'}


class MIXIE_OT_moodboard_lasso_tool(Operator):
    """Activate lasso tool - click and drag to draw freeform mask region"""
    bl_idname = "mixie.moodboard_lasso_tool"
    bl_label = "Lasso Tool"
    bl_description = "Activate lasso tool - click and drag to draw freeform mask region (L)"
    bl_options = {'REGISTER', 'BLOCKING'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'mixie_moodboard_images'):
            return False
        selected = [i for i, img in enumerate(context.scene.mixie_moodboard_images)
                    if img.selected and img.image]
        return len(selected) == 1

    def modal(self, context, event):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        # Handle ESC to cancel
        if event.type == 'ESC':
            state.active_tool = 'NONE'
            state.is_drawing = False
            state.target_image_index = -1
            state.lasso_points.clear()
            state.lasso_select_has_selection = False
            state.lasso_select_pending = False
            context.area.tag_redraw()
            return {'CANCELLED'}

        # Handle left mouse for drawing
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                # Start drawing - clear previous points
                state.lasso_points.clear()
                state.is_drawing = True
                # Add first point
                img_rel = mouse_to_image_coords(context, event, state.target_image_index)
                if img_rel:
                    point = state.lasso_points.add()
                    point.x = img_rel[0]
                    point.y = img_rel[1]
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            elif event.value == 'RELEASE':
                if state.is_drawing:
                    state.is_drawing = False
                    # Apply mask on mouse release if we have enough points
                    if len(state.lasso_points) >= LASSO_MIN_POINTS:
                        bpy.ops.mixie.moodboard_apply_lasso_mask(invert=False)
                        # Mark selection as ready for SAM refinement
                        state.lasso_select_has_selection = True
                        context.area.tag_redraw()
                        return {'FINISHED'}
                    else:
                        self.report({'WARNING'}, f"Need at least {LASSO_MIN_POINTS} points to create lasso mask")
                        state.lasso_points.clear()
                        state.active_tool = 'NONE'
                        state.target_image_index = -1
                        context.area.tag_redraw()
                        return {'CANCELLED'}
                return {'RUNNING_MODAL'}

        # Handle mouse move while drawing - add points
        if event.type == 'MOUSEMOVE' and state.is_drawing:
            img_rel = mouse_to_image_coords(context, event, state.target_image_index)
            if img_rel:
                # Add point (limit point density to avoid too many points)
                if len(state.lasso_points) == 0:
                    point = state.lasso_points.add()
                    point.x = img_rel[0]
                    point.y = img_rel[1]
                else:
                    last_point = state.lasso_points[-1]
                    # Only add point if it's far enough from last point
                    dist_sq = (img_rel[0] - last_point.x)**2 + (img_rel[1] - last_point.y)**2
                    if dist_sq > LASSO_MIN_DISTANCE_THRESHOLD:
                        point = state.lasso_points.add()
                        point.x = img_rel[0]
                        point.y = img_rel[1]
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Handle Enter to apply mask (non-inverted) - kept as fallback
        if event.type == 'RET' and event.value == 'PRESS':
            if len(state.lasso_points) >= LASSO_MIN_POINTS:
                bpy.ops.mixie.moodboard_apply_lasso_mask(invert=False)
            else:
                self.report({'WARNING'}, f"Need at least {LASSO_MIN_POINTS} points to create lasso mask")
            return {'FINISHED'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        # Track active tab for operator state
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            scene.mixie_moodboard_sidebar.active_tab = 'SEGMENTATION'
            scene.mixie_moodboard_sidebar.segmentation_subtab = 'SEGMENT_TO_3D'

        # Find the selected image
        selected_idx = -1
        for i, img in enumerate(scene.mixie_moodboard_images):
            if img.selected and img.image:
                selected_idx = i
                break

        if selected_idx < 0:
            self.report({'WARNING'}, "No image selected")
            return {'CANCELLED'}

        # Initialize state
        state.active_tool = 'LASSO'
        state.target_image_index = selected_idx
        state.is_drawing = False
        state.lasso_points.clear()

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        self.report({'INFO'}, "Click and drag to draw freeform selection. Enter to apply mask, ESC to cancel.")
        return {'RUNNING_MODAL'}


class MIXIE_OT_moodboard_apply_lasso_mask(Operator):
    """Apply lasso mask to create a masked image"""
    bl_idname = "mixie.moodboard_apply_lasso_mask"
    bl_label = "Apply Lasso Mask"
    bl_options = {'REGISTER', 'UNDO'}

    invert: BoolProperty(
        name="Invert",
        description="Invert the mask",
        default=False
    )

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'mixie_edit_tool_state'):
            return False
        state = context.scene.mixie_edit_tool_state
        return (state.active_tool == 'LASSO' and
                state.target_image_index >= 0 and
                len(state.lasso_points) >= LASSO_MIN_POINTS)

    def execute(self, context):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        if state.target_image_index < 0 or state.target_image_index >= len(scene.mixie_moodboard_images):
            self.report({'ERROR'}, "Invalid image index")
            return {'CANCELLED'}

        img_item = scene.mixie_moodboard_images[state.target_image_index]

        # Track moodboard count before C++ operator
        count_before = len(scene.mixie_moodboard_images)

        # Calculate offset for placing mask next to original
        offset_x = (MOODBOARD_IMAGE_BASE_SIZE * img_item.scale) + MOODBOARD_IMAGE_SPACING

        # Call the C++ accelerated operator
        # The C++ operator reads lasso points directly from scene.mixie_edit_tool_state.lasso_points
        result = bpy.ops.mixie.moodboard_generate_lasso_mask(
            image_index=state.target_image_index,
            invert=self.invert,
            offset_x=offset_x
        )

        # Remove mask from moodboard (we don't want to display it)
        # The mask is created by C++ but we only need the lasso points for SAM
        if result == {'FINISHED'} and len(scene.mixie_moodboard_images) > count_before:
            # Get the newly added mask item (last one)
            mask_item = scene.mixie_moodboard_images[-1]
            mask_image = mask_item.image
            # Remove from moodboard collection
            scene.mixie_moodboard_images.remove(len(scene.mixie_moodboard_images) - 1)
            # Remove the mask image from bpy.data.images
            if mask_image:
                try:
                    bpy.data.images.remove(mask_image)
                except:
                    pass

        # Don't reset tool state - keep lasso points for SAM refinement
        # The SAM operator will reset state after processing
        context.area.tag_redraw()
        self.report({'INFO'}, "Lasso selection ready for segmentation")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_box_mask_tool,
    MIXIE_OT_moodboard_apply_box_mask,
    MIXIE_OT_moodboard_lasso_tool,
    MIXIE_OT_moodboard_apply_lasso_mask,
)
