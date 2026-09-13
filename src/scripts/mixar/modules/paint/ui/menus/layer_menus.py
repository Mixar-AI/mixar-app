# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer context menus for Mixar"""

import bpy
from bpy.types import Menu


class LAYERS_MT_NewLayerMenu(Menu):
    """Menu for creating new layers with different types"""

    bl_label = "New Layer"
    bl_idname = "LAYERS_MT_new_layer_menu"

    def draw(self, context):
        """Draw the new layer menu with different layer type options.

        Args:
            context: Blender context containing current state and scene data.
        """
        layout = self.layout

        # IMAGE layer (Paint Layer)
        layout.operator(
            "layers.add_paint_layer",
            text="Paint Layer",
            icon='BRUSHES_ALL'
        )

        # COLOR layer (Fill Layer)
        layout.operator(
            "layers.add_fill_layer",
            text="Fill Layer",
            icon='COLOR'
        )

        # VCOL layer (Vertex Color Layer)
        op = layout.operator(
            "layers.add_advanced_layer",
            text="Vertex Color Layer",
            icon='VPAINT_HLT',
        )
        op.layer_type = 'VCOL'

        # GROUP layer (Layer Group)
        layout.operator(
            "layers.add_layer_group",
            text="Layer Group",
            icon='FILE_FOLDER',
        )

        layout.separator()

        layout.menu("LAYERS_MT_procedural_layer_menu", text="Procedural Pattern", icon='TEXTURE')

        layout.separator()

        # Open images as layer
        layout.operator(
            "layers.open_images_to_layer",
            text="Open Images as Layer",
            icon='FILE_IMAGE'
        )


class LAYERS_MT_LayerContextMenu(Menu):
    """Context menu for layer operations"""

    bl_label = "Layer"
    bl_idname = "LAYERS_MT_layer_context_menu"

    def draw(self, context):
        """Draw the layer context menu with image and layer operations.

        Args:
            context: Blender context containing current state and layer_index
                attribute if set by the caller.
        """
        layout = self.layout

        # Get the layer index from context (set by caller)
        if hasattr(context, 'layer_index'):
            layer_idx = context.layer_index

            # Image operations
            layout.label(text="Image Operations:", icon='IMAGE_DATA')
            layout.operator("layers.save_image", text="Save Image").layer_index = layer_idx
            layout.operator("layers.save_image_as", text="Save Image As...").layer_index = layer_idx
            layout.separator()
            layout.operator("layers.pack_image", text="Pack Image").layer_index = layer_idx
            layout.operator("layers.unpack_image", text="Unpack Image").layer_index = layer_idx

            layout.separator()

            # Layer operations
            layout.label(text="Layer Operations:", icon='NODE')
            layout.operator("layers.remove_active_layer", text="Remove Layer")

            layout.separator()
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


class LAYERS_MT_BakeMenu(Menu):
    """Menu for baking operations"""

    bl_label = "Bake"
    bl_idname = "LAYERS_MT_bake_menu"

    def draw(self, _context):
        """Draw the bake menu with various baking operation options.

        Args:
            _context: Blender context (unused but required by Blender API).
        """
        layout = self.layout

        # Common bake operations
        layout.operator("wm.m_bake_channels", text="Bake All Channels", icon='RENDER_STILL')

        layout.separator()

        # Bake to vertex color
        layout.operator("wm.m_bake_channel_to_vcol", text="Bake Channel to Vertex Color", icon='VPAINT_HLT')

        layout.separator()

        # Bake temp image
        layout.operator("wm.m_bake_temp_image", text="Bake Temporary Image", icon='IMAGE_DATA')

        layout.separator()

        # Delete baked images
        layout.operator("wm.m_delete_baked_channel_images", text="Delete Baked Images", icon='TRASH')


# Classes for registration
classes = (
    LAYERS_MT_NewLayerMenu,
    LAYERS_MT_LayerContextMenu,
    LAYERS_MT_BakeMenu,
)


def register():
    """Register all menu classes with Blender.

    Iterates through the classes tuple and registers each menu class
    using Blender's registration system.

    This function is idempotent - safe to call multiple times.
    """
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise


def unregister():
    """Unregister all menu classes from Blender.

    Iterates through the classes tuple in reverse order and unregisters
    each menu class using Blender's unregistration system.
    """
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
