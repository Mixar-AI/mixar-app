# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Texel Density Panel

Texel density panel wrapper for the Mixar UV Properties space.
Delegates drawing to the texel_density module.
"""

from bpy.types import Panel

from mixar.modules.uv_editor.ui.base.panels import poll_header_panel
from mixar.modules.texel_density.texel.ui import panel_draw


class MIXAR_UV_PT_texel_density(Panel):
    """Texel Density panel for Mixar UV Properties space"""
    bl_label = "Texel Density"
    bl_idname = "MIXAR_UV_PT_texel_density"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # Header-driven panels sort in the middle band (above Selection /
    # UV Tool / Functions / Transform = 100, below UV Sculpt Tools /
    # Annotate = -10).
    bl_order = 50

    @classmethod
    def poll(cls, context):
        return poll_header_panel(
            context, 'TEXEL_DENSITY', requires_mesh_data=True)

    def draw(self, context):
        layout = self.layout

        # Top padding for parent panel
        layout.separator(factor=0.5)

        layout.use_property_split = True
        layout.use_property_decorate = False

        panel_draw(layout, context)


classes = (
    MIXAR_UV_PT_texel_density,
)
