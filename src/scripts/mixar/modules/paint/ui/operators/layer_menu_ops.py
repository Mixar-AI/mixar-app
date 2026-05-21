# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer operations menu for Mixar layers system.

This module provides the popup menu operator for layer operations including
duplicate, copy, remove, and group operations.
"""

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from ...core.node.node_utils import get_active_mpaint_node


class LAYERS_OT_SelectedLayersMenu(Operator):
    """Show menu for operations on selected layers"""

    bl_idname = "layers.selected_layers_menu"
    bl_label = "Layer Operations"
    bl_description = "Show operations menu for selected layers"
    bl_options = {"INTERNAL"}

    layer_index: IntProperty(default=-1)

    def invoke(self, context, event):
        """Show operations menu popup.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Result from popup invocation.
        """
        wm = context.window_manager
        return wm.invoke_popup(self, width=280)

    def draw(self, context):
        """Draw operations menu UI with single and batch operations.

        Args:
            context: Blender context.
        """
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        wm = context.window_manager

        if not hasattr(wm, 'mixar_ui'):
            layout.label(text="UI not initialized", icon='ERROR')
            return

        main_col = layout.column(align=False)

        # Count selected layers
        selected_count = sum(1 for layer in wm.mixar_ui.ui_layers if layer.selected)

        # Header
        header_row = main_col.row(align=True)
        header_row.scale_y = 1.2
        if selected_count > 0:
            header_row.label(text=f"Operations on {selected_count} Layer(s)", icon='THREE_DOTS')
        else:
            header_row.label(text="Layer Operations", icon='THREE_DOTS')

        main_col.separator(factor=0.8)

        # Single layer operations
        self._draw_single_layer_ops(context, main_col, wm)

        # Group operations section
        self._draw_group_ops(context, main_col)

    def _draw_single_layer_ops(self, context, main_col, wm):
        """Draw single layer operations section.

        Args:
            context: Blender context.
            main_col: Main column layout.
            wm: Window manager.
        """
        if self.layer_index >= 0 and self.layer_index < len(wm.mixar_ui.ui_layers):
            layer = wm.mixar_ui.ui_layers[self.layer_index]

            single_box = main_col.box()
            single_col = single_box.column(align=False)

            # Section header
            single_header = single_col.row(align=True)
            single_header.scale_y = 1.2
            single_header.label(text="Current Layer:", icon='LAYER_USED')

            single_col.separator(factor=0.4)

            # Duplicate Layer (with image content)
            dup_row = single_col.row(align=True)
            dup_row.scale_y = 1.2
            op = dup_row.operator("wm.m_duplicate_layer", text="Duplicate Layer", icon='DUPLICATE')
            op.layer_idx = self.layer_index
            op.duplicate_blank = False

            single_col.separator(factor=0.2)

            # Duplicate Blank Layer (no image content)
            dup_blank_row = single_col.row(align=True)
            dup_blank_row.scale_y = 1.2
            op_blank = dup_blank_row.operator("wm.m_duplicate_layer", text="Duplicate Blank Layer", icon='FILE_NEW')
            op_blank.layer_idx = self.layer_index
            op_blank.duplicate_blank = True

            single_col.separator(factor=0.2)

            # Copy Layer (copies layer to clipboard for later paste)
            copy_row = single_col.row(align=True)
            copy_row.scale_y = 1.2
            op_copy = copy_row.operator("wm.m_copy_layer", text="Copy Layer", icon='COPYDOWN')
            op_copy.layer_idx = self.layer_index
            op_copy.all_layers = False

            single_col.separator(factor=0.4)
            single_col.separator(factor=0.2)

            # Remove
            rem_row = single_col.row(align=True)
            rem_row.scale_y = 1.2
            rem_row.operator("layers.remove_active_layer", text="Remove Layer", icon='TRASH')

            single_col.separator(factor=0.4)
            main_col.separator(factor=0.8)

    def _draw_group_ops(self, context, main_col):
        """Draw group operations section.

        Args:
            context: Blender context.
            main_col: Main column layout.
        """
        node = get_active_mpaint_node()
        if not node:
            return

        mp = node.node_tree.mp

        # Check if there are any groups available
        has_groups = any(l.type == 'GROUP' for l in mp.layers)

        # Show group section if groups exist or current layer is in a group
        layer_in_group = (
            self.layer_index >= 0
            and self.layer_index < len(mp.layers)
            and mp.layers[self.layer_index].parent_idx != -1
        )

        if not has_groups and not layer_in_group:
            return

        group_box = main_col.box()
        group_col = group_box.column(align=False)

        # Section header
        group_header = group_col.row(align=True)
        group_header.scale_y = 1.2
        group_header.label(text="Group Operations:", icon='GROUP')

        group_col.separator(factor=0.4)

        # Add to Group (only if groups exist)
        if has_groups:
            add_group_row = group_col.row(align=True)
            add_group_row.scale_y = 1.2
            op_add = add_group_row.operator(
                "layers.add_layers_to_group",
                text="Add to Group...",
                icon='ADD'
            )
            if self.layer_index >= 0:
                op_add.layer_index = self.layer_index

            group_col.separator(factor=0.2)

        # Remove from Group (only if current layer is in a group)
        if layer_in_group:
            current_layer = mp.layers[self.layer_index]
            if current_layer.parent_idx != -1:
                remove_group_row = group_col.row(align=True)
                remove_group_row.scale_y = 1.2
                op_remove = remove_group_row.operator(
                    "layers.remove_from_group",
                    text="Remove from Group",
                    icon='REMOVE'
                )
                op_remove.layer_index = self.layer_index

        group_col.separator(factor=0.4)
        main_col.separator(factor=0.8)

    def execute(self, context):
        """Close the popup.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'}.
        """
        return {"FINISHED"}


# Classes for registration
classes = (
    LAYERS_OT_SelectedLayersMenu,
)
