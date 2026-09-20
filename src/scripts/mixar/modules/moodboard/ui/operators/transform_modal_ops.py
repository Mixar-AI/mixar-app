# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Modal Transform Operators

Interactive modal operators for grab, rotate and scale of moodboard items.
"""

import math

import bpy
from bpy.types import Operator

from .transform_ops import (
    get_all_items_to_transform,
    calculate_selection_pivot,
    tag_mixie_redraw,
)


class MIXIE_OT_moodboard_grab(Operator):
    """Move selected moodboard items interactively"""

    bl_idname = "mixie.moodboard_grab"
    bl_label = "Grab/Move"
    bl_description = "Move selected images and text boxes (G)"
    bl_options = {'REGISTER', 'UNDO'}

    # Store initial View2D mouse position and item positions
    _initial_view_x: float = 0.0
    _initial_view_y: float = 0.0

    def _get_view_coords(self, context, event):
        """Convert screen coordinates to View2D coordinates."""
        region = context.region
        if region and hasattr(region, 'view2d'):
            return region.view2d.region_to_view(
                event.mouse_region_x, event.mouse_region_y
            )
        return event.mouse_region_x, event.mouse_region_y

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            # Get current mouse position in View2D coordinates
            view_x, view_y = self._get_view_coords(context, event)

            # Calculate delta in View2D space (1:1 with item positions)
            delta_x = view_x - self._initial_view_x
            delta_y = view_y - self._initial_view_y

            scene = context.scene

            # Update positions of all selected items (with bounds checking)
            for item_type, index, init_x, init_y in self._initial_positions:
                if item_type == 'IMAGE':
                    if index < len(scene.mixie_moodboard_images):
                        img = scene.mixie_moodboard_images[index]
                        img.position_x = init_x + delta_x
                        img.position_y = init_y + delta_y
                elif item_type == 'TEXTBOX':
                    if index < len(scene.mixie_moodboard_textboxes):
                        tb = scene.mixie_moodboard_textboxes[index]
                        tb.position_x = init_x + delta_x
                        tb.position_y = init_y + delta_y

            tag_mixie_redraw(context)
            return {'RUNNING_MODAL'}

        elif event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            # Confirm the move
            count = len(self._initial_positions)
            self.report({'INFO'}, f"Moved {count} item(s)")
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            # Cancel - restore original positions
            scene = context.scene
            for item_type, index, init_x, init_y in self._initial_positions:
                if item_type == 'IMAGE':
                    if index < len(scene.mixie_moodboard_images):
                        img = scene.mixie_moodboard_images[index]
                        img.position_x = init_x
                        img.position_y = init_y
                elif item_type == 'TEXTBOX':
                    if index < len(scene.mixie_moodboard_textboxes):
                        tb = scene.mixie_moodboard_textboxes[index]
                        tb.position_x = init_x
                        tb.position_y = init_y

            tag_mixie_redraw(context)
            self.report({'INFO'}, "Move cancelled")
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        scene = context.scene

        # Store initial mouse position in View2D coordinates
        self._initial_view_x, self._initial_view_y = self._get_view_coords(context, event)

        # Get all items to transform (including groups)
        image_indices, textbox_indices = get_all_items_to_transform(scene)

        # Store initial positions of all items to be transformed
        self._initial_positions = []

        for i in image_indices:
            if i < len(scene.mixie_moodboard_images):
                img = scene.mixie_moodboard_images[i]
                self._initial_positions.append(
                    ('IMAGE', i, img.position_x, img.position_y)
                )

        for i in textbox_indices:
            if i < len(scene.mixie_moodboard_textboxes):
                tb = scene.mixie_moodboard_textboxes[i]
                self._initial_positions.append(
                    ('TEXTBOX', i, tb.position_x, tb.position_y)
                )

        if not self._initial_positions:
            self.report({'WARNING'}, "No items selected to move")
            return {'CANCELLED'}

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


class MIXIE_OT_moodboard_rotate(Operator):
    """Rotate selected moodboard items interactively based on mouse movement"""

    bl_idname = "mixie.moodboard_rotate"
    bl_label = "Rotate"
    bl_description = "Rotate selected images and text boxes interactively (R)"
    bl_options = {'REGISTER', 'UNDO'}

    # Store initial state
    _pivot_x: float = 0.0
    _pivot_y: float = 0.0
    _prev_mouse_angle: float = 0.0
    _cumulative_rotation: float = 0.0  # Track total rotation to avoid atan2 wrap issues

    def _get_mouse_angle(self, event):
        """Calculate the angle from pivot to mouse position."""
        dx = event.mouse_region_x - self._pivot_x
        dy = event.mouse_region_y - self._pivot_y
        return math.degrees(math.atan2(dy, dx))

    def _normalize_angle_delta(self, delta):
        """Normalize angle delta to handle wrap-around at +/-180 degrees."""
        # Bring delta into -180 to +180 range
        while delta > 180.0:
            delta -= 360.0
        while delta < -180.0:
            delta += 360.0
        return delta

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            # Calculate angle delta from PREVIOUS mouse position (not initial)
            current_angle = self._get_mouse_angle(event)
            raw_delta = current_angle - self._prev_mouse_angle

            # Normalize to handle +/-180 degree wrap-around
            normalized_delta = self._normalize_angle_delta(raw_delta)

            # Accumulate the rotation
            self._cumulative_rotation += normalized_delta

            # Update previous angle for next frame
            self._prev_mouse_angle = current_angle

            # Use cumulative rotation for the actual transformation
            angle_rad = math.radians(self._cumulative_rotation)

            scene = context.scene

            # Update rotations and positions of all items (with bounds checking)
            for item_type, index, init_rotation, init_x, init_y in self._initial_states:
                # Calculate new rotation
                new_rotation = (init_rotation + self._cumulative_rotation) % 360.0

                # Calculate new position (rotate around pivot)
                dx = init_x - self._pivot_x
                dy = init_y - self._pivot_y
                cos_a = math.cos(angle_rad)
                sin_a = math.sin(angle_rad)
                new_x = self._pivot_x + dx * cos_a - dy * sin_a
                new_y = self._pivot_y + dx * sin_a + dy * cos_a

                if item_type == 'IMAGE':
                    if index < len(scene.mixie_moodboard_images):
                        img = scene.mixie_moodboard_images[index]
                        img.rotation = new_rotation
                        img.position_x = new_x
                        img.position_y = new_y
                elif item_type == 'TEXTBOX':
                    if index < len(scene.mixie_moodboard_textboxes):
                        tb = scene.mixie_moodboard_textboxes[index]
                        tb.rotation = new_rotation
                        tb.position_x = new_x
                        tb.position_y = new_y

            tag_mixie_redraw(context)
            return {'RUNNING_MODAL'}

        elif event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            # Confirm the rotation
            count = len(self._initial_states)
            self.report({'INFO'}, f"Rotated {count} item(s)")
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            # Cancel - restore original rotations and positions
            scene = context.scene
            for item_type, index, init_rotation, init_x, init_y in self._initial_states:
                if item_type == 'IMAGE':
                    if index < len(scene.mixie_moodboard_images):
                        img = scene.mixie_moodboard_images[index]
                        img.rotation = init_rotation
                        img.position_x = init_x
                        img.position_y = init_y
                elif item_type == 'TEXTBOX':
                    if index < len(scene.mixie_moodboard_textboxes):
                        tb = scene.mixie_moodboard_textboxes[index]
                        tb.rotation = init_rotation
                        tb.position_x = init_x
                        tb.position_y = init_y

            tag_mixie_redraw(context)
            self.report({'INFO'}, "Rotation cancelled")
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        scene = context.scene

        # Get all items to transform (including groups)
        image_indices, textbox_indices = get_all_items_to_transform(scene)

        # Store initial states (rotation and position) of all items to be transformed
        self._initial_states = []

        for i in image_indices:
            if i < len(scene.mixie_moodboard_images):
                img = scene.mixie_moodboard_images[i]
                self._initial_states.append(
                    ('IMAGE', i, img.rotation, img.position_x, img.position_y)
                )

        for i in textbox_indices:
            if i < len(scene.mixie_moodboard_textboxes):
                tb = scene.mixie_moodboard_textboxes[i]
                self._initial_states.append(
                    ('TEXTBOX', i, tb.rotation, tb.position_x, tb.position_y)
                )

        if not self._initial_states:
            self.report({'WARNING'}, "No items selected to rotate")
            return {'CANCELLED'}

        # Calculate pivot point (center of selection) using shared utility
        self._pivot_x, self._pivot_y = calculate_selection_pivot(scene)

        # Initialize rotation tracking
        self._prev_mouse_angle = self._get_mouse_angle(event)
        self._cumulative_rotation = 0.0

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


class MIXIE_OT_moodboard_scale(Operator):
    """Scale selected moodboard items interactively based on mouse movement"""

    bl_idname = "mixie.moodboard_scale"
    bl_label = "Scale"
    bl_description = "Scale selected images and text boxes interactively (S)"
    bl_options = {'REGISTER', 'UNDO'}

    # Scale sensitivity - pixels of mouse movement for 1x scale change
    # Lower = more sensitive, Higher = less sensitive
    SCALE_PIXELS_PER_UNIT = 100.0

    # Store initial state
    _pivot_x: float = 0.0
    _pivot_y: float = 0.0
    _initial_mouse_x: float = 0.0

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            # Calculate scale factor from horizontal mouse movement
            # Moving right = scale up, moving left = scale down
            delta_x = event.mouse_region_x - self._initial_mouse_x

            # Convert pixel movement to scale factor
            # 100 pixels right = 2x scale, 100 pixels left = 0.5x scale (approx)
            scale_factor = 1.0 + (delta_x / self.SCALE_PIXELS_PER_UNIT)

            # Clamp scale factor to reasonable range
            scale_factor = max(0.1, min(10.0, scale_factor))

            scene = context.scene

            # Update scales and positions (with bounds checking)
            for item_type, index, init_scale, init_width, init_height, init_x, init_y in self._initial_states:
                # Calculate new position (scale distance from pivot)
                dx = init_x - self._pivot_x
                dy = init_y - self._pivot_y
                new_x = self._pivot_x + dx * scale_factor
                new_y = self._pivot_y + dy * scale_factor

                if item_type == 'IMAGE':
                    if index < len(scene.mixie_moodboard_images):
                        img = scene.mixie_moodboard_images[index]
                        img.scale = init_scale * scale_factor
                        img.position_x = new_x
                        img.position_y = new_y
                elif item_type == 'TEXTBOX':
                    if index < len(scene.mixie_moodboard_textboxes):
                        tb = scene.mixie_moodboard_textboxes[index]
                        # For textboxes, scale width and height
                        tb.width = init_width * scale_factor
                        tb.height = init_height * scale_factor
                        tb.position_x = new_x
                        tb.position_y = new_y

            tag_mixie_redraw(context)
            return {'RUNNING_MODAL'}

        elif event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            # Confirm the scale
            count = len(self._initial_states)
            self.report({'INFO'}, f"Scaled {count} item(s)")
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            # Cancel - restore original scales and positions
            scene = context.scene
            for item_type, index, init_scale, init_width, init_height, init_x, init_y in self._initial_states:
                if item_type == 'IMAGE':
                    if index < len(scene.mixie_moodboard_images):
                        img = scene.mixie_moodboard_images[index]
                        img.scale = init_scale
                        img.position_x = init_x
                        img.position_y = init_y
                elif item_type == 'TEXTBOX':
                    if index < len(scene.mixie_moodboard_textboxes):
                        tb = scene.mixie_moodboard_textboxes[index]
                        tb.width = init_width
                        tb.height = init_height
                        tb.position_x = init_x
                        tb.position_y = init_y

            tag_mixie_redraw(context)
            self.report({'INFO'}, "Scale cancelled")
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        scene = context.scene

        # Get all items to transform (including groups)
        image_indices, textbox_indices = get_all_items_to_transform(scene)

        # Store initial states (scale/size and position) of all items to be transformed
        self._initial_states = []

        for i in image_indices:
            if i < len(scene.mixie_moodboard_images):
                img = scene.mixie_moodboard_images[i]
                # For images: store scale and position
                self._initial_states.append(
                    ('IMAGE', i, img.scale, 0, 0, img.position_x, img.position_y)
                )

        for i in textbox_indices:
            if i < len(scene.mixie_moodboard_textboxes):
                tb = scene.mixie_moodboard_textboxes[i]
                # For textboxes: store width, height and position
                self._initial_states.append(
                    ('TEXTBOX', i, 1.0, tb.width, tb.height, tb.position_x, tb.position_y)
                )

        if not self._initial_states:
            self.report({'WARNING'}, "No items selected to scale")
            return {'CANCELLED'}

        # Calculate pivot point (center of selection) using shared utility
        self._pivot_x, self._pivot_y = calculate_selection_pivot(scene)

        # Store initial mouse x position for horizontal movement scaling
        self._initial_mouse_x = event.mouse_region_x

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


classes = (
    MIXIE_OT_moodboard_grab,
    MIXIE_OT_moodboard_rotate,
    MIXIE_OT_moodboard_scale,
)
