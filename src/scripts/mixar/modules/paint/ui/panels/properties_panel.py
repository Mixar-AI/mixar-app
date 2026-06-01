# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar Properties Space Panel

Panel definition for the Mixar Properties workspace space.
Shows CHANNELS/BRUSH tabs with active layer/mask properties.
"""

from bpy.types import Header, Panel

from ..utils.ui_helpers import draw_layer_settings
from ..utils.ui_helpers_mask import draw_mask_settings
from ..utils.ui_helpers_unified_transform import draw_unified_transform_panel
from ..utils.ui_refresh import update_mixar_ui
from ..utils.ui_brush_panels import draw_brush_tab, _draw_brush_texture_generation
from ..utils.ui_channel_panels import draw_channels_tab


class MIXAR_PROPERTIES_HT_header(Header):
    """Header for the Mixar Properties space (hosts the space-switch dropdown)."""
    bl_space_type = 'MIXAR_PROPERTIES'

    def draw(self, context):
        layout = self.layout
        layout.template_header()


class MIXAR_PROPERTIES_PT_main(Panel):
    """Active Layer Properties Panel - Integrated with paint backend"""
    bl_label = ""
    bl_idname = "MIXAR_PROPERTIES_PT_main"
    bl_space_type = 'MIXAR_PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout

        # Top padding
        for _ in range(1):
            layout.separator()

        # Sync UI state
        update_mixar_ui()

        wm = context.window_manager

        if not hasattr(wm, 'mixar_ui'):
            layout.label(text="No UI state", icon='INFO')
            return

        mixar_ui = wm.mixar_ui

        # Check for active layer
        if len(mixar_ui.ui_layers) == 0:
            layout.label(text="No layers", icon='INFO')
            layout.label(text="Create a layer to see properties")
            return

        if mixar_ui.active_layer_index < 0 or mixar_ui.active_layer_index >= len(mixar_ui.ui_layers):
            layout.label(text="No layer selected", icon='INFO')
            return

        # Get UI layer
        ui_layer = mixar_ui.ui_layers[mixar_ui.active_layer_index]

        # Get backend layer
        obj = context.active_object
        if not obj or not obj.active_material or not obj.active_material.use_nodes:
            layout.label(text="No active material", icon='INFO')
            return

        mat = obj.active_material
        node = None
        for n in mat.node_tree.nodes:
            if n.type == 'GROUP' and n.node_tree and hasattr(n.node_tree, 'mp'):
                node = n
                break

        if not node:
            layout.label(text="No Mixar node found", icon='INFO')
            return

        tree = node.node_tree
        mp = tree.mp

        if ui_layer.mixar_layer_idx < 0 or ui_layer.mixar_layer_idx >= len(mp.layers):
            layout.label(text="Backend layer not found", icon='INFO')
            return

        # Get backend layer
        backend_layer = mp.layers[ui_layer.mixar_layer_idx]

        # Check if we're editing a mask (Substance Painter-style sub-layer selection)
        editing_idx = mixar_ui.editing_mask_index
        if editing_idx >= 0 and editing_idx < len(backend_layer.masks):
            mask = backend_layer.masks[editing_idx]

            # Show MASK SETTINGS/BRUSH tabs
            tab_row = layout.row(align=True)
            tab_row.scale_y = 1.5
            tab_row.prop(mixar_ui, "mask_panel_tab", expand=True)

            layout.separator(factor=0.5)

            if mixar_ui.mask_panel_tab == 'MASK':
                # Draw full mask settings
                draw_mask_settings(layout, mask, editing_idx, backend_layer)

                # Draw unified transform panel for mask (only in MASK tab, not BRUSH)
                layout.separator()
                draw_unified_transform_panel(context, layout, backend_layer, mp)
            elif mixar_ui.mask_panel_tab == 'BRUSH':
                # Brush Texture Generation - visible in BRUSH tab
                _draw_brush_texture_generation(context, layout)
                layout.separator(factor=0.5)

                # Draw brush tab (same as main brush panel)
                draw_brush_tab(context, layout, mixar_ui, mp, backend_layer)

            return

        # ========== DRAW CONTENT BASED ON LAYER TYPE ==========
        if backend_layer.type == 'IMAGE':
            # Paint layer: Show brush color picker above tabs
            # if hasattr(context, 'tool_settings') and context.tool_settings.image_paint:
            #     settings = context.tool_settings.image_paint
            #     brush = settings.brush
            #     if brush and brush.image_paint_capabilities.has_color:
            #         ups = settings.unified_paint_settings

            #         color_box = layout.box()
            #         color_row = color_box.row(align=True)
            #         color_row.scale_y = 1.5
            #         color_row.label(text="Brush Color")

            #         # Primary and secondary colors (respect unified color setting)
            #         if ups.use_unified_color:
            #             color_row.prop(ups, "color", text="")
            #             color_row.prop(ups, "secondary_color", text="")
            #         else:
            #             color_row.prop(brush, "color", text="")
            #             color_row.prop(brush, "secondary_color", text="")

            #         # Image picker for brush texture
            #         # Check for both texture existence AND image to avoid black painting
            #         if brush.texture and brush.texture.image:
            #             color_row.template_ID(brush.texture, "image", open="image.open")
            #             color_row.operator("wm.m_clear_brush_texture", text="", icon='X')
            #         else:
            #             color_row.operator("wm.m_open_image_to_brush_texture", text="", icon='IMAGE_DATA')

            # layout.separator(factor=0.5)

            # Show CHANNELS/BRUSH tabs
            tab_row = layout.row(align=True)
            tab_row.scale_y = 1.5
            tab_row.prop(mixar_ui, "main_panel_tab", expand=True)

            layout.separator(factor=0.5)

            if mixar_ui.main_panel_tab == 'CHANNELS':
                draw_channels_tab(context, layout, mixar_ui, mp, backend_layer)

                # Draw unified transform panel for paint layer (only in CHANNELS tab)
                layout.separator()
                draw_unified_transform_panel(context, layout, backend_layer, mp)
            elif mixar_ui.main_panel_tab == 'BRUSH':
                # Brush Texture Generation - visible in BRUSH tab
                _draw_brush_texture_generation(context, layout)
                layout.separator(factor=0.5)

                draw_brush_tab(context, layout, mixar_ui, mp, backend_layer)
        elif backend_layer.type == 'PROCEDURAL':
            # Procedural layer: Material info, parameters, channels
            from ..utils.ui_helpers_layer_settings import _draw_procedural_layer_settings
            _draw_procedural_layer_settings(context, layout, backend_layer, mp, mixar_ui)
        elif backend_layer.type == 'COLOR':
            # Fill layer: Use layer settings UI
            draw_layer_settings(context, layout, backend_layer)

            # Draw unified transform panel for fill layer
            layout.separator()
            draw_unified_transform_panel(context, layout, backend_layer, mp)
        else:
            # Group layer (GROUP): Use layer settings UI, no Transform panel
            draw_layer_settings(context, layout, backend_layer)


classes = (
    MIXAR_PROPERTIES_HT_header,
    MIXAR_PROPERTIES_PT_main,
)
