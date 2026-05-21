# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask management operators and menus for Mixar"""

import bpy
from bpy.props import IntProperty
from bpy.types import Operator, Menu

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import get_active_object
from ..mask.mask_operators_helper import remove_mask
from ..utils.ui_refresh import request_ui_refresh


class MASKS_OT_RemoveMask(Operator):
    """Remove a mask from the active layer"""

    bl_idname = "masks.remove_mask"
    bl_label = "Remove Mask"
    bl_description = "Remove the selected mask from the active layer"
    bl_options = {"REGISTER", "UNDO"}

    mask_index: IntProperty(default=-1, options={'HIDDEN'})

    def invoke(self, context, event):
        """Show confirmation dialog before removing mask.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Result from confirmation dialog.
        """
        # Show confirmation dialog
        return context.window_manager.invoke_confirm(self, event)

    def draw(self, context):
        """Draw the confirmation dialog UI.

        Displays the mask name to be removed.

        Args:
            context: Blender context.
        """
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        node = get_active_mpaint_node()
        if node and node.node_tree:
            mp = node.node_tree.mp
            if mp.active_layer_index >= 0 and mp.active_layer_index < len(mp.layers):
                layer = mp.layers[mp.active_layer_index]

                if self.mask_index >= 0 and self.mask_index < len(layer.masks):
                    mask = layer.masks[self.mask_index]

                    main_col = layout.column(align=False)

                    # Question
                    question_row = main_col.row(align=True)
                    question_row.scale_y = 1.3
                    question_row.label(text=f"Remove mask '{mask.name}'?", icon='QUESTION')

    def execute(self, context):
        """Remove the specified mask from the active layer.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        node = get_active_mpaint_node()
        obj = get_active_object()

        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp

        if mp.active_layer_index < 0 or mp.active_layer_index >= len(mp.layers):
            self.report({'ERROR'}, "No active layer")
            return {'CANCELLED'}

        layer = mp.layers[mp.active_layer_index]

        if self.mask_index < 0 or self.mask_index >= len(layer.masks):
            self.report({'ERROR'}, "Invalid mask index")
            return {'CANCELLED'}

        mask = layer.masks[self.mask_index]
        mask_name = mask.name

        try:
            # Remove mask
            remove_mask(layer, mask, obj, refresh_list=True)

            self.report({'INFO'}, f"Removed mask '{mask_name}' from layer '{layer.name}'")

            # Request UI refresh
            request_ui_refresh()

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to remove mask: {str(e)}")
            logger.error("Failed to remove mask: %s", e, exc_info=True)
            return {'CANCELLED'}


# Submenu: Image Masks
class MASKS_MT_ImageMasksMenu(Menu):
    """Image-based masks submenu"""

    bl_idname = "MASKS_MT_image_masks_menu"
    bl_label = "Image Masks"

    def draw(self, context):
        """Draw image-based mask options.

        Args:
            context: Blender context.
        """
        layout = self.layout

        # New Image Mask
        op = layout.operator("wm.m_new_layer_mask", text="New Image Mask", icon='IMAGE_DATA')
        op.type = 'IMAGE'

        # Open Image as Mask
        op = layout.operator("wm.m_open_image_as_mask", text="Open Image as Mask...", icon='FILE_FOLDER')
        op.texcoord_type = 'UV'

        # Open Available Image as Mask
        op = layout.operator("wm.m_open_available_data_as_mask", text="Open Available Image", icon='IMAGE_DATA')
        op.type = 'IMAGE'


# Submenu: Vertex Color Masks
class MASKS_MT_VertexColorMasksMenu(Menu):
    """Vertex color-based masks submenu"""

    bl_idname = "MASKS_MT_vertex_color_masks_menu"
    bl_label = "Vertex Color Masks"

    def draw(self, context):
        """Draw vertex color-based mask options.

        Args:
            context: Blender context.
        """
        layout = self.layout

        # New Vertex Color Mask
        op = layout.operator("wm.m_new_layer_mask", text="New Vertex Color Mask", icon='OUTLINER_DATA_MESH')
        op.type = 'VCOL'

        # Open Available Vertex Color as Mask
        op = layout.operator("wm.m_open_available_data_as_mask", text="Open Available Vertex Color", icon='OUTLINER_DATA_MESH')
        op.type = 'VCOL'

        layout.separator()

        # Color ID
        op = layout.operator("wm.m_new_layer_mask", text="Color ID", icon='COLOR')
        op.type = 'COLOR_ID'


# Submenu: Procedural Masks
class MASKS_MT_ProceduralMasksMenu(Menu):
    """Procedural/Generated masks submenu"""

    bl_idname = "MASKS_MT_procedural_masks_menu"
    bl_label = "Procedural Masks"

    def draw(self, context):
        """Draw procedural/generated mask options.

        Args:
            context: Blender context.
        """
        layout = self.layout

        # Texture-based procedural masks
        layout.label(text="Texture Patterns:")

        op = layout.operator("wm.m_new_layer_mask", text="Brick", icon='TEXTURE')
        op.type = 'BRICK'

        op = layout.operator("wm.m_new_layer_mask", text="Checker", icon='TEXTURE')
        op.type = 'CHECKER'

        op = layout.operator("wm.m_new_layer_mask", text="Gradient", icon='TEXTURE')
        op.type = 'GRADIENT'

        op = layout.operator("wm.m_new_layer_mask", text="Magic", icon='TEXTURE')
        op.type = 'MAGIC'

        op = layout.operator("wm.m_new_layer_mask", text="Noise", icon='TEXTURE')
        op.type = 'NOISE'

        op = layout.operator("wm.m_new_layer_mask", text="Gabor", icon='TEXTURE')
        op.type = 'GABOR'

        op = layout.operator("wm.m_new_layer_mask", text="Voronoi", icon='TEXTURE')
        op.type = 'VORONOI'

        op = layout.operator("wm.m_new_layer_mask", text="Wave", icon='TEXTURE')
        op.type = 'WAVE'

        layout.separator()

        # Geometry-based masks
        layout.label(text="Geometry Based:")

        op = layout.operator("wm.m_new_layer_mask", text="Fake Lighting", icon='LIGHT_SUN')
        op.type = 'HEMI'

        op = layout.operator("wm.m_new_layer_mask", text="Object Index", icon='OBJECT_DATA')
        op.type = 'OBJECT_INDEX'

        op = layout.operator("wm.m_new_layer_mask", text="Backface", icon='FACESEL')
        op.type = 'BACKFACE'

        op = layout.operator("wm.m_new_layer_mask", text="Ambient Occlusion", icon='SHADING_RENDERED')
        op.type = 'AO'

        op = layout.operator("wm.m_new_layer_mask", text="Edge Detect", icon='EDGESEL')
        op.type = 'EDGE_DETECT'


# Submenu: Bake as Mask
class MASKS_MT_BakeMasksMenu(Menu):
    """Bake operations as masks submenu"""

    bl_idname = "MASKS_MT_bake_masks_menu"
    bl_label = "Bake as Mask"

    def draw(self, context):
        """Draw bake operation mask options.

        Args:
            context: Blender context.
        """
        layout = self.layout

        # Ambient Occlusion
        op = layout.operator("wm.m_bake_to_layer", text="Ambient Occlusion", icon='SHADING_RENDERED')
        op.type = 'AO'
        op.target_type = 'MASK'
        op.overwrite_current = False

        # Pointiness
        op = layout.operator("wm.m_bake_to_layer", text="Pointiness", icon='SHARPCURVE')
        op.type = 'POINTINESS'
        op.target_type = 'MASK'
        op.overwrite_current = False

        # Cavity
        op = layout.operator("wm.m_bake_to_layer", text="Cavity", icon='SMOOTHCURVE')
        op.type = 'CAVITY'
        op.target_type = 'MASK'
        op.overwrite_current = False

        # Dust
        op = layout.operator("wm.m_bake_to_layer", text="Dust", icon='PARTICLES')
        op.type = 'DUST'
        op.target_type = 'MASK'
        op.overwrite_current = False

        # Paint Base
        op = layout.operator("wm.m_bake_to_layer", text="Paint Base", icon='BRUSHES_ALL')
        op.type = 'PAINT_BASE'
        op.target_type = 'MASK'
        op.overwrite_current = False

        # Bevel Grayscale
        op = layout.operator("wm.m_bake_to_layer", text="Bevel Grayscale", icon='MOD_BEVEL')
        op.type = 'BEVEL_MASK'
        op.target_type = 'MASK'
        op.overwrite_current = False

        # Selected Vertices
        op = layout.operator("wm.m_bake_to_layer", text="Selected Vertices", icon='VERTEXSEL')
        op.type = 'SELECTED_VERTICES'
        op.target_type = 'MASK'
        op.overwrite_current = False


# Submenu: Modifier Masks
class MASKS_MT_ModifierMasksMenu(Menu):
    """Modifier masks submenu"""

    bl_idname = "MASKS_MT_modifier_masks_menu"
    bl_label = "Modifier Masks"

    def draw(self, context):
        """Draw modifier mask options.

        Args:
            context: Blender context.
        """
        layout = self.layout

        # Invert
        op = layout.operator("wm.m_new_layer_mask", text="Invert", icon='ARROW_LEFTRIGHT')
        op.type = 'MODIFIER'
        op.modifier_type = 'INVERT'

        # Ramp
        op = layout.operator("wm.m_new_layer_mask", text="Ramp", icon='SMOOTHCURVE')
        op.type = 'MODIFIER'
        op.modifier_type = 'RAMP'

        # Curve
        op = layout.operator("wm.m_new_layer_mask", text="Curve", icon='CURVE_BEZCURVE')
        op.type = 'MODIFIER'
        op.modifier_type = 'CURVE'


# Mask Selection Operators (Substance Painter style sub-layer selection)
class LAYERS_OT_SelectMask(Operator):
    """Select mask for editing in Properties panel"""

    bl_idname = "layers.select_mask"
    bl_label = "Select Mask"
    bl_description = "Select this mask to edit its properties"
    bl_options = {"INTERNAL"}

    layer_index: IntProperty(default=-1, options={'HIDDEN'})
    mask_index: IntProperty(default=-1, options={'HIDDEN'})

    def execute(self, context):
        """Select the specified mask for editing.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success.
        """
        # Save all modified images before switching to mask
        if any(img.is_dirty for img in bpy.data.images):
            try:
                bpy.ops.image.save_all_modified()
            except RuntimeError as e:
                self.report({"WARNING"}, f"Could not save modified images before switching to mask: {e}")

        wm = context.window_manager

        if not hasattr(wm, 'mixar_ui'):
            return {'CANCELLED'}

        mixar_ui = wm.mixar_ui

        # Set the editing mask index
        mixar_ui.editing_mask_index = self.mask_index

        # Switch to the mask's parent layer and set active mask
        node = get_active_mpaint_node()
        if node and node.node_tree:
            mp = node.node_tree.mp
            if self.layer_index >= 0 and self.layer_index < len(mp.layers):
                # Switch active layer to the mask's parent layer
                mp.active_layer_index = self.layer_index
                mixar_ui.active_layer_index = self.layer_index

                layer = mp.layers[self.layer_index]
                if self.mask_index >= 0 and self.mask_index < len(layer.masks):
                    layer.active_mask_index = self.mask_index

                    # Clear active_edit on all masks and channels first
                    # Use halt_update to prevent callback recursion
                    mp.halt_update = True
                    for m in layer.masks:
                        if m.active_edit:
                            m.active_edit = False
                    for ch in layer.channels:
                        if ch.active_edit:
                            ch.active_edit = False
                        if ch.active_edit_1:
                            ch.active_edit_1 = False

                    # Set active_edit on the selected mask
                    mask = layer.masks[self.mask_index]
                    mask.active_edit = True
                    mp.halt_update = False

                    # Update texture slot based on mask type
                    # For IMAGE masks, use the source image
                    # For baked masks, use the baked source image
                    # For procedural masks (not baked), clear the texture set
                    from ...core.node.get_nodes import get_mask_source
                    from ...utils.blender_commons import set_image_paint_canvas
                    if mask.type == 'IMAGE':
                        source = get_mask_source(mask)
                        if source and hasattr(source, 'image') and source.image:
                            set_image_paint_canvas(source.image)
                        else:
                            set_image_paint_canvas(None)
                    elif mask.use_baked:
                        # Use baked image for procedural masks that have been baked
                        baked_source = get_mask_source(mask, get_baked=True)
                        if baked_source and hasattr(baked_source, 'image') and baked_source.image:
                            set_image_paint_canvas(baked_source.image)
                        else:
                            set_image_paint_canvas(None)
                    else:
                        # Procedural mask without baked image - clear texture set
                        set_image_paint_canvas(None)

        # Switch to texture paint mode for masks
        obj = context.active_object
        if obj and obj.type == 'MESH':
            if context.mode != 'PAINT_TEXTURE':
                try:
                    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
                except RuntimeError:
                    pass  # Silently ignore if can't switch

        # Request UI refresh
        request_ui_refresh()

        return {'FINISHED'}


class LAYERS_OT_DeselectMask(Operator):
    """Go back to layer properties"""

    bl_idname = "layers.deselect_mask"
    bl_label = "Back to Layer"
    bl_description = "Return to layer properties view"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        """Deselect the current mask and return to layer view.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success.
        """
        wm = context.window_manager

        if not hasattr(wm, 'mixar_ui'):
            return {'CANCELLED'}

        mixar_ui = wm.mixar_ui
        mixar_ui.editing_mask_index = -1

        # Clear active_edit on masks and update texture slot for Paint layers
        node = get_active_mpaint_node()
        if node and node.node_tree:
            mp = node.node_tree.mp
            if mp.active_layer_index >= 0 and mp.active_layer_index < len(mp.layers):
                layer = mp.layers[mp.active_layer_index]

                # Clear active_edit on all masks
                # Use halt_update to prevent callback recursion
                mp.halt_update = True
                for mask in layer.masks:
                    if mask.active_edit:
                        mask.active_edit = False
                mp.halt_update = False

                # For Paint layers, update texture slot to layer image
                if layer.type == 'IMAGE':
                    from ...core.node.get_nodes import get_layer_source, get_tree
                    from ...utils.blender_commons import set_image_paint_canvas
                    tree = get_tree(layer)
                    source = get_layer_source(layer, tree)
                    if source and hasattr(source, 'image') and source.image:
                        set_image_paint_canvas(source.image)

        # Request UI refresh
        request_ui_refresh()

        return {'FINISHED'}


# Main Menu: Add Mask
class MASKS_MT_AddMaskMenu(Menu):
    """Main menu for adding different types of masks"""

    bl_idname = "MASKS_MT_add_mask_menu"
    bl_label = "Add Mask"
    bl_description = "Add different types of masks to the active layer"

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed.

        Args:
            context: Blender context.

        Returns:
            bool: True if active mpaint node exists, False otherwise.
        """
        return get_active_mpaint_node() is not None

    def draw(self, context):
        """Draw the main mask menu with all submenu options.

        Args:
            context: Blender context.
        """
        layout = self.layout

        # Image Masks submenu
        layout.menu("MASKS_MT_image_masks_menu", icon='IMAGE_DATA')

        # Vertex Color Masks submenu (disabled for now)
        # layout.menu("MASKS_MT_vertex_color_masks_menu", icon='OUTLINER_DATA_MESH')

        # Procedural Masks submenu
        layout.menu("MASKS_MT_procedural_masks_menu", icon='TEXTURE')

        # Bake as Mask submenu
        layout.menu("MASKS_MT_bake_masks_menu", icon='RENDER_RESULT')

        # Modifier Masks submenu (disabled for now)
        # layout.menu("MASKS_MT_modifier_masks_menu", icon='MODIFIER')


# Classes for registration
classes = (
    MASKS_OT_RemoveMask,
    LAYERS_OT_SelectMask,
    LAYERS_OT_DeselectMask,
    MASKS_MT_ImageMasksMenu,
    MASKS_MT_VertexColorMasksMenu,
    MASKS_MT_ProceduralMasksMenu,
    MASKS_MT_BakeMasksMenu,
    MASKS_MT_ModifierMasksMenu,
    MASKS_MT_AddMaskMenu,
)
