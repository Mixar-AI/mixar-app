# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar Layers Space Panel

Panel definition for the Mixar Layers workspace space.
Integrated with the paint module backend for functional texture painting.
"""

import bpy
from bpy.types import Header, Panel

from ..utils.ui_helpers import (
    draw_top_toolbar,
    draw_materials_section,
)
from ..utils.ui_refresh import update_mixar_ui
from ..lists.layer_uilist import draw_nested_layer_list


# ========== HEADER (Top Bar - Toolbar Buttons) ==========
class MIXAR_LAYERS_HT_header(Header):
    """Header containing toolbar buttons"""
    bl_idname = "MIXAR_LAYERS_HT_header"
    bl_space_type = 'MIXAR_LAYERS'
    bl_region_type = 'TOOL_PROPS'

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        # Title on the left
        layout.label(text="Layers")

        # Check if mixar_ui exists
        if not hasattr(wm, 'mixar_ui'):
            return

        mixar_ui = wm.mixar_ui

        # Only show toolbar when layers exist
        if len(mixar_ui.ui_layers) == 0:
            return

        # Push toolbar to the right
        layout.separator_spacer()
        draw_top_toolbar(context, layout)


# ========== FOOTER (Bottom Bar - Move Buttons) ==========
class MIXAR_LAYERS_HT_footer(Header):
    """Footer containing move up/down buttons"""
    bl_idname = "MIXAR_LAYERS_HT_footer"
    bl_space_type = 'MIXAR_LAYERS'
    bl_region_type = 'EXECUTE'

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        # Check if mixar_ui exists
        if not hasattr(wm, 'mixar_ui'):
            return

        mixar_ui = wm.mixar_ui

        # Only show when layers exist
        if len(mixar_ui.ui_layers) == 0:
            return

        # Get backend mp
        obj = context.active_object
        mp = None
        if obj and obj.active_material and obj.active_material.use_nodes:
            mat = obj.active_material
            for n in mat.node_tree.nodes:
                if n.type == 'GROUP' and n.node_tree and hasattr(n.node_tree, 'mp'):
                    mp = n.node_tree.mp
                    break

        if not mp:
            return

        # Center the move buttons using spacers
        layout.separator_spacer()

        # Move buttons row
        move_row = layout.row(align=True)

        # Check if a mask is being edited
        is_editing_mask = (
            hasattr(mixar_ui, 'editing_mask_index')
            and mixar_ui.editing_mask_index >= 0
        )

        if is_editing_mask:
            # Get the active layer and mask for context
            active_layer = None
            active_mask = None

            if mp.active_layer_index >= 0 and mp.active_layer_index < len(mp.layers):
                active_layer = mp.layers[mp.active_layer_index]
                mask_idx = mixar_ui.editing_mask_index
                if mask_idx < len(active_layer.masks):
                    active_mask = active_layer.masks[mask_idx]

            if active_layer and active_mask:
                # Set context pointers for mask move operator
                move_row.context_pointer_set('layer', active_layer)
                move_row.context_pointer_set('mask', active_mask)

                # Use mask move operators
                move_row.operator(
                    "wm.m_move_layer_mask",
                    icon='TRIA_UP',
                    text="Move Up"
                ).direction = 'UP'
                move_row.operator(
                    "wm.m_move_layer_mask",
                    icon='TRIA_DOWN',
                    text="Move Down"
                ).direction = 'DOWN'
            else:
                # Fallback to layer move if mask context not available
                move_row.operator(
                    "wm.m_move_layer",
                    icon='TRIA_UP',
                    text="Move Up"
                ).direction = 'UP'
                move_row.operator(
                    "wm.m_move_layer",
                    icon='TRIA_DOWN',
                    text="Move Down"
                ).direction = 'DOWN'
        else:
            # Layer move mode
            move_row.operator(
                "wm.m_move_layer",
                icon='TRIA_UP',
                text="Move Up"
            ).direction = 'UP'
            move_row.operator(
                "wm.m_move_layer",
                icon='TRIA_DOWN',
                text="Move Down"
            ).direction = 'DOWN'

        layout.separator_spacer()


class MIXAR_LAYERS_PT_main(Panel):
    """Texture Layer Stack Panel - Integrated with paint backend"""
    bl_label = ""
    bl_idname = "MIXAR_LAYERS_PT_main"
    bl_space_type = 'MIXAR_LAYERS'
    bl_region_type = 'WINDOW'
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout

        # Top padding
        # for _ in range(1):
        #     layout.separator()

        # UPDATE UI PROPS FIRST - Mixar Paint pattern
        update_mixar_ui()

        wm = context.window_manager

        # Check if mixar_ui exists
        if not hasattr(wm, 'mixar_ui'):
            layout.label(text="Paint backend not initialized", icon='ERROR')
            return

        # Check if mpui exists (required for materials section)
        if not hasattr(wm, 'mpui'):
            layout.label(text="Paint UI not initialized", icon='ERROR')
            return

        mixar_ui = wm.mixar_ui

        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=True)

        # Materials section
        # draw_materials_section(context, main_col)

        # No layers - show create material button
        if len(mixar_ui.ui_layers) == 0:
            main_col.separator(factor=2)

            # Info box
            info_box = main_col.box()
            info_col = info_box.column(align=True)
            info_col.scale_y = 1.2
            info_col.label(text="No layer based material", icon="INFO")
            info_col.label(text="Create one to start working with layers")

            main_col.separator(factor=1)

            # Create button
            create_row = main_col.row(align=True)
            create_row.scale_y = 2.0
            create_row.operator(
                "layers.create_material", text="Create Layer Based Material", icon="ADD"
            )

            # Poll check - only enabled for mesh objects
            obj = context.active_object
            is_valid_mesh = obj is not None and obj.type == "MESH"
            create_row.enabled = is_valid_mesh

            if not is_valid_mesh:
                main_col.separator(factor=0.5)
                warning_box = main_col.box()
                warning_box.label(
                    text="Select a mesh object to create material", icon="ERROR"
                )

            return

        # Get backend mp for UIList
        obj = context.active_object
        mp = None
        if obj and obj.active_material and obj.active_material.use_nodes:
            mat = obj.active_material
            for n in mat.node_tree.nodes:
                if n.type == 'GROUP' and n.node_tree and hasattr(n.node_tree, 'mp'):
                    mp = n.node_tree.mp
                    break

        if not mp:
            main_col.label(text="No Mixar material found", icon='INFO')
            return

        # ========== NESTED LAYER LIST (Substance 3D Painter style with masks) ==========
        # Create a box for the layer list
        list_box = main_col.box()
        list_col = list_box.column(align=True)

        # Draw nested layer list with masks
        draw_nested_layer_list(context, list_col, mp)


classes = (
    MIXAR_LAYERS_HT_header,
    MIXAR_LAYERS_HT_footer,
    MIXAR_LAYERS_PT_main,
)
