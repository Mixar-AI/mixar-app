# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer popup operators for Mixar layers system"""

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from ...core.node.node_utils import get_active_mpaint_node


class LAYERS_OT_EditLayerMenu(Operator):
    """Open layer settings menu"""

    bl_idname = "layers.edit_layer_menu"
    bl_label = "Edit Layer"
    bl_description = "Edit layer settings"
    bl_options = {"INTERNAL"}

    layer_index: IntProperty(default=-1)

    def invoke(self, context, event):
        """Show layer settings popup menu.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Result from popup invocation.
        """
        # Show popup menu
        wm = context.window_manager
        return wm.invoke_popup(self, width=300)

    def draw(self, context):
        """Draw layer settings UI.

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

        if self.layer_index < 0 or self.layer_index >= len(wm.mixar_ui.ui_layers):
            layout.label(text="Invalid layer index", icon='ERROR')
            return

        layer = wm.mixar_ui.ui_layers[self.layer_index]

        main_col = layout.column(align=False)

        # ========== LAYER SETTINGS SECTION ==========
        settings_box = main_col.box()
        settings_col = settings_box.column(align=False)

        # Header
        header_row = settings_col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Layer Settings", icon='GREASEPENCIL')

        settings_col.separator(factor=1.2)

        # Layer name
        name_row = settings_col.row(align=True)
        name_row.scale_y = 1.4
        name_split = name_row.split(factor=0.25, align=True)
        label_col = name_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Name:")
        name_split.prop(layer, "name", text="")

        settings_col.separator(factor=0.4)

        # Layer color tag
        color_row = settings_col.row(align=True)
        color_row.scale_y = 1.4
        color_split = color_row.split(factor=0.25, align=True)
        label_col = color_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Color Tag:")
        color_split.prop(layer, "layer_color", text="")

        settings_col.separator(factor=0.4)

        settings_col.separator(factor=0.8)

    def execute(self, context):
        """Close the popup.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'}.
        """
        # Just close the popup
        return {"FINISHED"}


class LAYERS_OT_RenameLayerPopup(Operator):
    """Rename layer popup (double-click on layer name)"""

    bl_idname = "layers.rename_layer_popup"
    bl_label = "Rename Layer"
    bl_description = "Rename this layer"
    bl_options = {'REGISTER', 'UNDO'}

    layer_index: IntProperty(default=-1)

    new_name: StringProperty(
        name="Name",
        description="New name for the layer",
        default=""
    )

    def draw(self, context):
        """Draw rename popup UI.

        Args:
            context: Blender context.
        """
        layout = self.layout
        row = layout.row(align=True)

        row.use_property_split = False
        row.activate_init = True

        row.prop(self, "new_name", text="")

    def invoke(self, context, event):
        """Show rename popup.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Result from popup invocation.
        """
        node = get_active_mpaint_node()
        if not node:
            self.report({'WARNING'}, "No active Mixar node")
            return {'CANCELLED'}

        mp = node.node_tree.mp

        if self.layer_index < 0 or self.layer_index >= len(mp.layers):
            self.report({'WARNING'}, "Invalid layer index")
            return {'CANCELLED'}

        # Initialize with current name
        self.new_name = mp.layers[self.layer_index].name

        return context.window_manager.invoke_props_dialog(self, width=250)

    def execute(self, context):
        """Apply the new name to the backend layer.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} or {'CANCELLED'}.
        """
        node = get_active_mpaint_node()
        if not node:
            self.report({'ERROR'}, "No active Mixar node")
            return {'CANCELLED'}

        mp = node.node_tree.mp

        if self.layer_index < 0 or self.layer_index >= len(mp.layers):
            self.report({'ERROR'}, "Invalid layer index")
            return {'CANCELLED'}

        if not self.new_name.strip():
            self.report({'WARNING'}, "Name cannot be empty")
            return {'CANCELLED'}

        old_name = mp.layers[self.layer_index].name
        mp.layers[self.layer_index].name = self.new_name

        # Also update UI layer cache
        wm = context.window_manager
        if hasattr(wm, 'mixar_ui'):
            if self.layer_index < len(wm.mixar_ui.ui_layers):
                wm.mixar_ui.ui_layers[self.layer_index].name = self.new_name

        self.report({'INFO'}, f"Renamed '{old_name}' to '{self.new_name}'")
        return {'FINISHED'}


class LAYERS_OT_ColorPickerPopup(Operator):
    """Color picker popup for layer color tag"""

    bl_idname = "layers.color_picker_popup"
    bl_label = "Layer Color Tag"
    bl_description = "Pick color tag for this layer"
    bl_options = {'REGISTER', 'UNDO'}

    layer_index: IntProperty(default=-1)

    def draw(self, context):
        """Draw color picker popup UI.

        Args:
            context: Blender context.
        """
        layout = self.layout
        col = layout.column(align=True)

        wm = context.window_manager
        if not hasattr(wm, 'mixar_ui'):
            return

        if self.layer_index < 0 or self.layer_index >= len(wm.mixar_ui.ui_layers):
            return

        layer = wm.mixar_ui.ui_layers[self.layer_index]

        # Color picker with larger size
        col.scale_y = 1.2
        col.prop(layer, "layer_color", text="")

    def invoke(self, context, event):
        """Show color picker popup.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Result from popup invocation.
        """
        wm = context.window_manager

        if not hasattr(wm, 'mixar_ui'):
            self.report({'WARNING'}, "UI not initialized")
            return {'CANCELLED'}

        if self.layer_index < 0 or self.layer_index >= len(wm.mixar_ui.ui_layers):
            self.report({'WARNING'}, "Invalid layer index")
            return {'CANCELLED'}

        wm.invoke_popup(self, width=300)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        """Finish color selection.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'}.
        """
        return {'FINISHED'}


# Classes for registration
classes = (
    LAYERS_OT_EditLayerMenu,
    LAYERS_OT_RenameLayerPopup,
    LAYERS_OT_ColorPickerPopup,
)
