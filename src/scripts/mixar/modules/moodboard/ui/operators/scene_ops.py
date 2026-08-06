# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Scene Operators

Cross-mode operators for applying images to scene.
"""

import bpy
from bpy.types import Operator


class MIXIE_OT_moodboard_apply_overlay(Operator):
    """Apply selected image to 3D scene"""

    bl_idname = "mixie.moodboard_apply_overlay"
    bl_label = "Apply to Scene"
    bl_description = "Apply selected image to the scene as camera background"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        selected_moodboard_items = [img for img in scene.mixie_moodboard_images if img.selected and img.image]

        if not selected_moodboard_items:
            self.report({'WARNING'}, "No image selected")
            return {'CANCELLED'}

        # Use the first selected image
        selected_item = selected_moodboard_items[0]
        selected_image = selected_item.image

        # Apply as camera background
        return self._apply_as_camera_background(context, selected_image)

    def _apply_as_camera_background(self, context, selected_image):
        """Apply image as camera background (regular workflow)"""
        scene = context.scene

        # Get active camera
        camera = scene.camera
        if not camera:
            self.report({'WARNING'}, "No active camera in scene")
            return {'CANCELLED'}

        # Configure background image
        camera.data.show_background_images = True
        bg_images = camera.data.background_images

        if not bg_images:
            bg_img = bg_images.new()
        else:
            bg_img = bg_images[0]

        bg_img.image = selected_image
        bg_img.frame_method = 'CROP'
        bg_img.alpha = 0.5
        bg_img.source = 'IMAGE'

        # Switch 3D View to Camera
        area_3d = None
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area_3d = area
                break

        if area_3d:
            space_data = area_3d.spaces.active
            if space_data:
                space_data.region_3d.view_perspective = 'CAMERA'
                area_3d.tag_redraw()
                self.report({'INFO'}, f"Overlay applied to camera '{camera.name}'")
        else:
            self.report({'INFO'}, f"Overlay applied to camera '{camera.name}'. Switch to 3D View to see it.")

        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_apply_overlay,
)
