# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Pie Menu

Pie menu for quick access to moodboard features (Tab key).
"""

import bpy
from bpy.types import Menu, Operator


from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE
from mixar.modules.moodboard.core.canvas_context import is_moodboard_context


class MIXIE_MT_moodboard_pie_menu(Menu):
    """Pie menu for moodboard features"""
    bl_idname = "MIXIE_MT_moodboard_pie_menu"
    bl_label = "Moodboard Features"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()
        # Menus default to INVOKE_REGION_WIN, which replaces the drawer with
        # View3D's WINDOW region and makes all moodboard popup polls fail.
        pie.operator_context = 'INVOKE_DEFAULT'

        # Pie menu positions (in order):
        # 4(W), 6(E), 2(S), 8(N), 7(NW), 9(NE), 1(SW), 3(SE)

        # West (4) - Mesh Segment
        pie.operator("mixie.mesh_segment_popup", text="Mesh Segment", icon='MESH_GRID')

        # East (6) - From Depth (formerly Lookdev)
        pie.operator("mixie.lookdev_popup", text="From Depth", icon='SHADING_RENDERED')

        # South (2) - ImageGen
        pie.operator("mixie.imagegen_popup", text="ImageGen", icon='IMAGE_DATA')

        # North (8) - Lookdev360
        pie.operator("mixie.lookdev360_popup", text="Generate PBR Maps", icon='SPHERE')

        # Northwest (7) - Segment to 3D
        pie.operator("mixie.segment_to_3d_popup", text="Segment to 3D", icon='MOD_MASK')

        # Northeast (9) - Image to 3D
        pie.operator("mixie.image_to_3d_popup", text="Image to 3D", icon='VIEW3D')

        # Southwest (1) - Scene Reconstruction
        pie.operator("mixie.scene_recon_popup", text="Generate Scene", icon='SCENE_DATA')

        # Southeast (3) - Empty slot (8th position required for proper pie menu layout)
        pie.separator()


class MIXIE_OT_moodboard_pie_menu_call(Operator):
    """Call the moodboard pie menu"""
    bl_idname = "mixie.moodboard_pie_menu_call"
    bl_label = "Moodboard Pie Menu"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return is_moodboard_context(context)

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="MIXIE_MT_moodboard_pie_menu")
        return {'FINISHED'}


# Only include classes if MIXIE space is available
classes = (
    MIXIE_MT_moodboard_pie_menu,
    MIXIE_OT_moodboard_pie_menu_call,
) if MIXIE_SPACE_AVAILABLE else ()
