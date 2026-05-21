# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Panel Toggle Operators

Operators for toggling panel visibility in the Mixie space sidebar.
These create mutually exclusive toggle button behavior.
"""

import bpy
from bpy.types import Operator


class MIXIE_OT_toggle_mesh_segment_panel(Operator):
    """Toggle Mesh Segment panel visibility"""
    bl_idname = "mixie.toggle_mesh_segment_panel"
    bl_label = "Toggle Mesh Segment Panel"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        # Toggle: if already MESH_SEGMENT, set to NONE; otherwise set to MESH_SEGMENT
        if scene.mixie_active_panel == 'MESH_SEGMENT':
            scene.mixie_active_panel = 'NONE'
        else:
            scene.mixie_active_panel = 'MESH_SEGMENT'

        # Force UI region to redraw immediately
        for area in context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_toggle_lookdev_panel(Operator):
    """Toggle Lookdev panel visibility"""
    bl_idname = "mixie.toggle_lookdev_panel"
    bl_label = "Toggle Lookdev Panel"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        # Toggle: if already LOOKDEV, set to NONE; otherwise set to LOOKDEV
        if scene.mixie_active_panel == 'LOOKDEV':
            scene.mixie_active_panel = 'NONE'
        else:
            scene.mixie_active_panel = 'LOOKDEV'

        # Force UI region to redraw immediately
        for area in context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_toggle_lookdev360_panel(Operator):
    """Toggle Lookdev360 panel visibility"""
    bl_idname = "mixie.toggle_lookdev360_panel"
    bl_label = "Toggle Lookdev360 Panel"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        # Toggle: if already LOOKDEV360, set to NONE; otherwise set to LOOKDEV360
        if scene.mixie_active_panel == 'LOOKDEV360':
            scene.mixie_active_panel = 'NONE'
        else:
            scene.mixie_active_panel = 'LOOKDEV360'

        # Force UI region to redraw immediately
        for area in context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_toggle_imagegen_panel(Operator):
    """Toggle Image Gen panel visibility"""
    bl_idname = "mixie.toggle_imagegen_panel"
    bl_label = "Toggle Image Gen Panel"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        # Toggle: if already IMAGEGEN, set to NONE; otherwise set to IMAGEGEN
        if scene.mixie_active_panel == 'IMAGEGEN':
            scene.mixie_active_panel = 'NONE'
        else:
            scene.mixie_active_panel = 'IMAGEGEN'

        # Force UI region to redraw immediately
        for area in context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_toggle_image_to_3d_panel(Operator):
    """Toggle Image to 3D panel visibility"""
    bl_idname = "mixie.toggle_image_to_3d_panel"
    bl_label = "Toggle Image to 3D Panel"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        # Toggle: if already IMAGE_TO_3D, set to NONE; otherwise set to IMAGE_TO_3D
        if scene.mixie_active_panel == 'IMAGE_TO_3D':
            scene.mixie_active_panel = 'NONE'
        else:
            scene.mixie_active_panel = 'IMAGE_TO_3D'

        # Force UI region to redraw immediately
        for area in context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()
        return {'FINISHED'}


classes = (
    MIXIE_OT_toggle_mesh_segment_panel,
    MIXIE_OT_toggle_lookdev_panel,
    MIXIE_OT_toggle_lookdev360_panel,
    MIXIE_OT_toggle_imagegen_panel,
    MIXIE_OT_toggle_image_to_3d_panel,
)
