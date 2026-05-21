# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer selection operators for Mixar layers system"""

import time
import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.node.get_nodes import get_layer_source
from ...core.node.node_utils import get_active_mpaint_node
from ..utils.ui_refresh import request_ui_refresh

# Global variables for double-click detection
_last_click_time = 0.0
_last_click_index = -1


class LAYERS_OT_LayerContextMenu(Operator):
    """Show layer context menu"""

    bl_idname = "layers.context_menu"
    bl_label = "Layer Menu"
    bl_description = "Show layer operations menu"
    bl_options = {"INTERNAL"}

    layer_index: IntProperty(default=-1)

    def invoke(self, context, _event):
        """Store layer index and display context menu.

        Args:
            context: Blender context.
            _event: Event that triggered the operator (unused).

        Returns:
            set: {'FINISHED'}.
        """
        # Store layer index in window manager for menu to access
        wm = context.window_manager
        if hasattr(wm, 'mixar_ui'):
            wm.mixar_ui.active_layer_index = self.layer_index

        # Invoke the menu
        context.window_manager.popup_menu(
            self.draw_menu,
            title="Layer Operations",
            icon='LAYER_USED'
        )
        return {'FINISHED'}

    def draw_menu(self, context):
        """Draw the context menu content

        Note: When called by popup_menu(), 'self' is the popup menu itself,
        not the operator instance.
        """
        layout = self.layout

        # Layer operations
        layout.operator("wm.m_duplicate_layer", text="Duplicate Layer", icon='DUPLICATE')
        layout.separator()
        layout.operator("layers.remove_active_layer", text="Remove Layer", icon='TRASH')


class LAYERS_OT_SelectLayer(Operator):
    """Select and activate this layer for painting"""

    bl_idname = "layers.select_layer"
    bl_label = "Select Layer"
    bl_description = "Select this layer and make it active for texture painting"
    bl_options = {"INTERNAL"}

    index: IntProperty()

    def execute(self, context):
        """Select and activate layer for painting.

        Implements double-click detection: single click selects layer,
        double-click opens rename popup (MatPlus pattern).

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        global _last_click_time, _last_click_index

        current_time = time.time()
        double_click_threshold = 0.3  # 300 ms

        same_item = (self.index == _last_click_index)
        delta = current_time - _last_click_time

        # Check for double-click
        if same_item and (delta < double_click_threshold):
            # Double-click detected - open rename popup
            bpy.ops.layers.rename_layer_popup('INVOKE_DEFAULT', layer_index=self.index)

            # Reset click tracking
            _last_click_time = 0.0
            _last_click_index = -1

            return {'FINISHED'}

        # Save all modified images before switching layers
        if any(img.is_dirty for img in bpy.data.images):
            try:
                bpy.ops.image.save_all_modified()
            except RuntimeError as e:
                self.report({"WARNING"}, f"Could not save modified images before switching layers: {e}")

        # Single click - select the layer
        # Get backend mp
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            return {'CANCELLED'}

        tree = node.node_tree
        mp = tree.mp

        if self.index < 0 or self.index >= len(mp.layers):
            return {'CANCELLED'}

        # Set active layer in backend
        mp.active_layer_index = self.index

        # Update UI cache active index
        wm = context.window_manager
        if hasattr(wm, 'mixar_ui'):
            wm.mixar_ui.active_layer_index = self.index
            # Clear mask editing mode when selecting a layer
            wm.mixar_ui.editing_mask_index = -1

        # Get the selected layer
        layer = mp.layers[self.index]

        obj = context.active_object
        if obj and obj.type == 'MESH':
            # Switch to texture paint mode for IMAGE (Paint) layers
            if layer.type == 'IMAGE':
                # Switch mode FIRST (unconditionally for IMAGE layers)
                if context.mode != 'PAINT_TEXTURE':
                    try:
                        bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
                    except RuntimeError as e:
                        logger.warning(f"Could not switch to texture paint mode: {e}")

                # Then try to set the canvas image (optional step)
                src = get_layer_source(layer, tree)
                if src and hasattr(src, 'image') and src.image:
                    if hasattr(context, 'tool_settings') and hasattr(context.tool_settings, 'image_paint'):
                        context.tool_settings.image_paint.canvas = src.image
                else:
                    logger.debug(f"Could not set canvas for layer {layer.name}: source or image not found")

            # Switch to object mode for COLOR (Fill) layers
            elif layer.type == 'COLOR':
                if context.mode != 'OBJECT':
                    try:
                        bpy.ops.object.mode_set(mode='OBJECT')
                    except RuntimeError as e:
                        logger.warning(f"Could not switch to object mode: {e}")

        # Request UI refresh
        request_ui_refresh()

        # Update click tracking
        _last_click_time = current_time
        _last_click_index = self.index

        return {"FINISHED"}


class LAYERS_OT_ToggleAllSelection(Operator):
    """Toggle selection state for all layers"""

    bl_idname = "layers.toggle_all_selection"
    bl_label = "Toggle All Selection"
    bl_description = "Select or deselect all layers"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        """Toggle selection state for all layers.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} if no UI.
        """
        wm = context.window_manager
        if not hasattr(wm, 'mixar_ui'):
            return {'CANCELLED'}

        ui_layers = wm.mixar_ui.ui_layers

        # Check if any are selected
        any_selected = any(layer.selected for layer in ui_layers)

        # If any selected, deselect all. If none selected, select all.
        for layer in ui_layers:
            layer.selected = not any_selected

        return {"FINISHED"}


class LAYERS_OT_ClearSelection(Operator):
    """Clear all layer selections"""

    bl_idname = "layers.clear_selection"
    bl_label = "Clear Selection"
    bl_description = "Deselect all layers"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        """Clear all layer selections.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} if no UI.
        """
        wm = context.window_manager
        if not hasattr(wm, 'mixar_ui'):
            return {'CANCELLED'}

        # Clear all selections
        for layer in wm.mixar_ui.ui_layers:
            layer.selected = False

        return {"FINISHED"}


class LAYERS_OT_FakeHighlightOp(Operator):
    """Fake operator for visual highlight effect on selected layer rows.

    Used with depress=True to create a colored strap indicator.
    Does nothing when clicked - purely visual.
    """

    bl_idname = "layers.fake_highlight_op"
    bl_label = ""
    bl_description = ""
    bl_options = {"INTERNAL"}

    def execute(self, context):
        return {"FINISHED"}


# Classes for registration
classes = (
    LAYERS_OT_LayerContextMenu,
    LAYERS_OT_SelectLayer,
    LAYERS_OT_ToggleAllSelection,
    LAYERS_OT_ClearSelection,
    LAYERS_OT_FakeHighlightOp,
)