# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Procedural pattern layer operators for Mixar layers system.

This module provides operators and menus for adding built-in procedural patterns
like Brick, Checker, Noise, Voronoi, etc.
"""

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from .....config.logging_config import get_logger
from ..utils.ui_refresh import request_ui_refresh

logger = get_logger(__name__)


class LAYERS_OT_AddProceduralLayer(Operator):
    """Add a procedural texture layer"""

    bl_idname = "layers.add_procedural_layer"
    bl_label = "Add Procedural Layer"
    bl_description = "Add a procedural texture layer"
    bl_options = {"INTERNAL"}

    layer_type: EnumProperty(
        name="Type",
        items=[
            ('BRICK', 'Brick', 'Procedural brick pattern'),
            ('CHECKER', 'Checker', 'Procedural checkerboard pattern'),
            ('GRADIENT', 'Gradient', 'Procedural gradient'),
            ('MAGIC', 'Magic', 'Procedural magic texture'),
            ('NOISE', 'Noise', 'Procedural noise texture'),
            ('VORONOI', 'Voronoi', 'Procedural Voronoi pattern'),
            ('WAVE', 'Wave', 'Procedural wave pattern'),
        ],
        default='NOISE'
    )

    def execute(self, context):
        """Create a new procedural texture layer.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        # Call wm.y_new_layer with the selected procedural type
        # Use INVOKE_DEFAULT to ensure invoke() is called to set the layer name
        logger.debug(f"LAYERS_OT_AddProceduralLayer.execute() - calling y_new_layer with type: '{self.layer_type}'")
        try:
            result = bpy.ops.wm.m_new_layer('INVOKE_DEFAULT', type=self.layer_type)
            logger.debug(f"y_new_layer returned: {result}")
        except Exception as e:
            logger.error(f"Exception calling y_new_layer: {e}")
            self.report({'ERROR'}, f"Failed to create {self.layer_type} layer: {e}")
            return {'CANCELLED'}

        request_ui_refresh()
        return {"FINISHED"}


class LAYERS_MT_ProceduralLayerMenu(bpy.types.Menu):
    """Procedural layer menu"""

    bl_idname = "LAYERS_MT_procedural_layer_menu"
    bl_label = "Procedural Patterns"
    bl_description = "Add procedural texture layer (Brick, Checker, Voronoi, etc.)"

    def draw(self, context):
        """Draw menu with procedural pattern options.

        Args:
            context: Blender context.
        """
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'

        # Procedural patterns
        op = layout.operator("layers.add_procedural_layer", text="Brick", icon='TEXTURE')
        op.layer_type = 'BRICK'

        op = layout.operator("layers.add_procedural_layer", text="Checker", icon='TEXTURE')
        op.layer_type = 'CHECKER'

        op = layout.operator("layers.add_procedural_layer", text="Gradient", icon='TEXTURE')
        op.layer_type = 'GRADIENT'

        op = layout.operator("layers.add_procedural_layer", text="Magic", icon='TEXTURE')
        op.layer_type = 'MAGIC'

        op = layout.operator("layers.add_procedural_layer", text="Noise", icon='TEXTURE')
        op.layer_type = 'NOISE'

        op = layout.operator("layers.add_procedural_layer", text="Voronoi", icon='TEXTURE')
        op.layer_type = 'VORONOI'

        op = layout.operator("layers.add_procedural_layer", text="Wave", icon='TEXTURE')
        op.layer_type = 'WAVE'


# Classes for registration
classes = (
    LAYERS_OT_AddProceduralLayer,
    LAYERS_MT_ProceduralLayerMenu,
)
