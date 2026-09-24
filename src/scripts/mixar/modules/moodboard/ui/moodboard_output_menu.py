# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The continuation menu opened from a node's output plus.

Split out of `moodboard_menus.py` when that file crossed the 500-line rule. It
is a second, much smaller menu that happens to ask the same availability
questions as the right-click menu; those live in `moodboard_menu_actions.py`.
"""

from bpy.types import Menu

from ..core.node_templates import template_available

from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE

from .moodboard_menu_actions import (
    capability_available,
    connected_action,
    draw_character_sheet_entry,
    link_drop_anchor,
    mesh_continuations_for,
)


class MIXIE_MT_moodboard_output_menu(Menu):
    """Compact continuation menu opened from a node's output plus."""

    bl_label = "Create Next Node"
    bl_idname = "MIXIE_MT_moodboard_output_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        scene = context.scene
        try:
            from mixar.modules.moodboard.core.node_graph import node_output_type

            source_id = str(scene.mixie_moodboard_output_source_id or "")
            source_type = node_output_type(scene, source_id)
        except Exception:
            source_id = ""
            source_type = ""
        drop = link_drop_anchor(scene)

        added = False
        if source_type == 'IMAGE' and capability_available("image_gen"):
            connected_action(
                layout, 'IMAGE_GEN', "Generate Image", 'IMAGE_DATA', source_id, drop
            )
            added = True
        if source_type == 'IMAGE' and capability_available("model_gen"):
            connected_action(
                layout, 'MODEL_3D', "Generate 3D", 'MESH_DATA', source_id, drop
            )
            added = True
        if source_type == 'IMAGE' and template_available('CHARACTER_PARTS'):
            connected_action(layout, 'CHARACTER_PARTS', "Character Parts",
                             'OUTLINER_OB_ARMATURE', source_id, drop)
            added = True
        if source_type == 'IMAGE' and template_available('CHARACTER_SHEET_3D'):
            draw_character_sheet_entry(layout, source_id, drop)
            added = True
        if source_type == 'IMAGE' and capability_available("world_labs"):
            connected_action(
                layout, 'WORLD_LABS', "Generate Splat", 'WORLD', source_id, drop
            )
            added = True
        if source_type in {'IMAGE', 'VIDEO'} and capability_available("video_gen"):
            connected_action(
                layout, 'VIDEO_GEN', "Generate Video", 'FILE_MOVIE', source_id, drop
            )
            added = True
        if source_type == 'VIDEO' and capability_available("video_upscale"):
            connected_action(
                layout, 'VIDEO_UPSCALE', "Upscale Video", 'FULLSCREEN_ENTER',
                source_id, drop,
            )
            added = True
        # A 3D mesh output continues into the mesh -> mesh features, matching the
        # right-click "Continue in 3D" section.
        if source_type == 'MESH':
            drew_mesh = False
            for action_type, text, icon, _capability in mesh_continuations_for(scene, source_id):
                if not drew_mesh:
                    layout.label(text="Continue in 3D")
                    drew_mesh = True
                connected_action(layout, action_type, text, icon, source_id, drop)
                added = True
        if not added:
            layout.label(text="No compatible continuation", icon='INFO')


# Only include menu if MIXIE space is available


classes = (MIXIE_MT_moodboard_output_menu,) if MIXIE_SPACE_AVAILABLE else ()
