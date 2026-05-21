# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer menu classes for Mixar layers system"""

import bpy


class LAYERS_MT_MoreOptionsMenu(bpy.types.Menu):
    """More layer options menu"""

    bl_idname = "LAYERS_MT_more_options_menu"
    bl_label = "More Options"
    bl_description = "More layer creation options"

    def draw(self, context):
        """Draw menu with advanced layer type options.

        Args:
            context: Blender context.
        """
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'

        # Advanced layer types
        op = layout.operator("layers.add_advanced_layer", text="New Vertex Color", icon='VPAINT_HLT')
        op.layer_type = 'VCOL'

        layout.separator()

        # Vector displacement - calls wm.y_new_vector_disp_layer if it exists
        try:
            if hasattr(bpy.ops.wm, 'y_new_vector_disp_layer'):
                layout.operator("wm.m_new_vector_disp_layer", text="Vector Displacement Image", icon='EMPTY_AXIS')
            else:
                layout.label(text="Vector Displacement (Not available)", icon='INFO')
        except:
            layout.label(text="Vector Displacement (Not available)", icon='INFO')

        layout.separator()

        op = layout.operator("layers.add_advanced_layer", text="Fake Lighting", icon='LIGHT_SUN')
        op.layer_type = 'HEMI'

        op = layout.operator("layers.add_advanced_layer", text="Ambient Occlusion", icon='SHADING_RENDERED')
        op.layer_type = 'AO'

        op = layout.operator("layers.add_advanced_layer", text="Edge Detect", icon='MESH_DATA')
        op.layer_type = 'EDGE_DETECT'


# Classes for registration
classes = (
    LAYERS_MT_MoreOptionsMenu,
)
