# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer selection operators for Mixar layers system"""

import time
import bpy
from bpy.props import BoolProperty, IntProperty
from bpy.types import Operator

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.node.get_nodes import get_layer_source, get_mask_source
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
        layout.operator(
            "layers.toggle_layer_preview",
            text="Isolate Layer",
            icon='RESTRICT_VIEW_OFF',
        )
        layout.operator(
            "wm.m_merge_layer",
            text="Merge Down",
            icon='AUTOMERGE_ON',
        ).direction = 'DOWN'
        layout.operator(
            "layers.invert_active_layer_image",
            text="Invert Image",
            icon='IMAGE_ALPHA',
        )
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


class LAYERS_OT_ToggleLayerPreview(Operator):
    """Solo a layer in the viewport (Ucupaint layer_preview_mode)."""

    bl_idname = "layers.toggle_layer_preview"
    bl_label = "Isolate Layer"
    bl_description = "Preview only this layer in the viewport"
    bl_options = {"REGISTER", "UNDO"}

    layer_index: IntProperty(
        name="Layer Index",
        description="Layer to isolate; -1 uses the active layer",
        default=-1,
    )

    @classmethod
    def poll(cls, context):
        node = get_active_mpaint_node()
        return bool(node and node.node_tree and node.node_tree.mp.layers)

    def execute(self, context):
        mp = get_active_mpaint_node().node_tree.mp
        idx = self.layer_index if self.layer_index >= 0 else mp.active_layer_index
        if idx < 0 or idx >= len(mp.layers):
            self.report({"WARNING"}, "No active layer")
            return {"CANCELLED"}

        wm = context.window_manager
        if hasattr(wm, "mixar_ui"):
            wm.mixar_ui.active_layer_index = idx
            wm.mixar_ui.editing_mask_index = -1

        # Clicking solo on the already-isolated layer turns preview off.
        already = mp.layer_preview_mode and mp.active_layer_index == idx
        if already:
            mp.layer_preview_mode = False
            request_ui_refresh()
            return {"FINISHED"}

        mp.active_layer_index = idx
        mp.layer_preview_mode_type = "LAYER"
        # RNA skips the update if the bool is already True (switching solos).
        if mp.layer_preview_mode:
            mp.layer_preview_mode = False
        mp.layer_preview_mode = True
        request_ui_refresh()
        return {"FINISHED"}


class LAYERS_OT_IsolateChannel(Operator):
    """Solo one PBR channel in the viewport (ArmorPaint viewport modes)."""

    bl_idname = "layers.isolate_channel"
    bl_label = "Isolate Channel"
    bl_description = "Preview only this material channel in the viewport"
    bl_options = {"REGISTER", "UNDO"}

    channel_index: IntProperty(default=0, min=0)

    @classmethod
    def poll(cls, context):
        node = get_active_mpaint_node()
        return bool(node and node.node_tree and node.node_tree.mp.channels)

    def execute(self, context):
        mp = get_active_mpaint_node().node_tree.mp
        if self.channel_index < 0 or self.channel_index >= len(mp.channels):
            return {"CANCELLED"}
        already = mp.preview_mode and mp.active_channel_index == self.channel_index
        if mp.preview_mode:
            mp.preview_mode = False
        if already:
            request_ui_refresh()
            return {"FINISHED"}
        mp.active_channel_index = self.channel_index
        mp.preview_mode = True
        request_ui_refresh()
        return {"FINISHED"}


class LAYERS_OT_InvertActiveLayerImage(Operator):
    """Invert the active paint layer or mask image (ArmorPaint invert mask)."""

    bl_idname = "layers.invert_active_layer_image"
    bl_label = "Invert Image"
    bl_description = "Invert RGB of the active layer or mask image"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        if mp.active_layer_index < 0 or mp.active_layer_index >= len(mp.layers):
            self.report({"WARNING"}, "No active layer")
            return {"CANCELLED"}
        layer = mp.layers[mp.active_layer_index]
        image = None
        wm = context.window_manager
        editing_idx = getattr(getattr(wm, "mixar_ui", None), "editing_mask_index", -1)
        if editing_idx is not None and editing_idx >= 0 and editing_idx < len(layer.masks):
            src = get_mask_source(layer.masks[editing_idx])
            image = getattr(src, "image", None) if src else None
        if image is None:
            src = get_layer_source(layer)
            image = getattr(src, "image", None) if src else None
        if image is None:
            self.report({"WARNING"}, "Active layer has no image to invert")
            return {"CANCELLED"}
        if hasattr(image, "yia") and image.yia.is_image_atlas:
            self.report({"ERROR"}, "Cannot invert image atlas")
            return {"CANCELLED"}
        override = bpy.context.copy()
        override["edit_image"] = image
        with bpy.context.temp_override(**override):
            bpy.ops.image.invert(invert_r=True, invert_g=True, invert_b=True)
        request_ui_refresh()
        return {"FINISHED"}


class LAYERS_OT_ColorIdToMask(Operator):
    """Create a Color ID mask from the brush / secondary color (ArmorPaint ColorID→Mask)."""

    bl_idname = "layers.color_id_to_mask"
    bl_label = "Color ID to Mask"
    bl_description = "Add a Color ID mask using the current brush color"
    bl_options = {"REGISTER", "UNDO"}

    use_secondary: BoolProperty(
        name="Use Secondary Color",
        description="Sample the secondary brush color instead of the primary",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            return False
        mp = node.node_tree.mp
        return mp.active_layer_index >= 0 and mp.active_layer_index < len(mp.layers)

    def execute(self, context):
        from ...core.element.check_elements import is_colorid_already_being_used
        from ...utils.constants import COLORID_TOLERANCE
        from ..mask.mask_creation import add_new_mask
        from ..mask.mask_operators_helper import get_new_mask_name
        from ..mask.mask_operators_new_execute import (
            finalize_mask_creation,
            setup_color_id_mask,
        )

        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        layer = mp.layers[mp.active_layer_index]
        obj = context.active_object
        mat = obj.active_material if obj else None
        wm = context.window_manager
        mpui = getattr(wm, "mpui", None)
        if not obj or not mat:
            self.report({"ERROR"}, "Need an active mesh with a material")
            return {"CANCELLED"}
        if mpui is None or not hasattr(mpui, "layer_ui"):
            self.report({"ERROR"}, "Paint UI not initialized")
            return {"CANCELLED"}

        color = (1.0, 0.0, 1.0)
        settings = getattr(getattr(context, "tool_settings", None), "image_paint", None)
        brush = getattr(settings, "brush", None) if settings else None
        if brush is not None:
            ups = settings.unified_paint_settings
            if ups.use_unified_color:
                src = ups.secondary_color if self.use_secondary else ups.color
            else:
                src = brush.secondary_color if self.use_secondary else brush.color
            color = (float(src[0]), float(src[1]), float(src[2]))

        # Avoid pure black / already-used IDs the same way new-mask invoke does.
        if max(color) < COLORID_TOLERANCE:
            color = (COLORID_TOLERANCE, COLORID_TOLERANCE, COLORID_TOLERANCE)
        if is_colorid_already_being_used(mp, color):
            self.report(
                {"WARNING"},
                "That Color ID is already used; creating the mask anyway",
            )

        name = get_new_mask_name(obj, layer, "COLOR_ID")
        setup_color_id_mask(color, True, obj, mat)
        mask = add_new_mask(
            layer,
            name,
            "COLOR_ID",
            "UV",
            "",
            None,
            "",
            None,
            0,
            "MULTIPLY",
            "OBJECT",
            True,
            color,
            source_input="RGB",
        )
        finalize_mask_creation(mask, "COLOR_ID", layer, mpui)
        request_ui_refresh()
        self.report({"INFO"}, f"Added Color ID mask '{mask.name}'")
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
    LAYERS_OT_ToggleLayerPreview,
    LAYERS_OT_IsolateChannel,
    LAYERS_OT_InvertActiveLayerImage,
    LAYERS_OT_ColorIdToMask,
    LAYERS_OT_FakeHighlightOp,
)