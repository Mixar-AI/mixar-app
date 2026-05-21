# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preview toggle operators for baked layers and channels - extracted from bake_to_layer_operators.py."""

import bpy
from bpy.props import StringProperty

from ....core.node.node_utils import get_active_mpaint_node
from ....core.node.get_nodes import get_active_mat_output_node
from ....utils.blender_commons import get_active_material, simple_remove_node
from ...operators.operators_helper_preview import get_preview, remove_preview, set_srgb_view_transform

# Constant for temporary image texture node name
TEMP_IMAGE_PREVIEW_NODE = "_temp_image_preview"


class MToggleBakedLayerPreview(bpy.types.Operator):
    """Toggle preview mode for a baked layer in the viewport.

    Switches between viewing the full composited material and viewing
    a single baked texture (AO, Cavity, etc.) in isolation.
    """

    bl_idname = "wm.m_toggle_baked_layer_preview"
    bl_label = "Toggle Baked Layer Preview"
    bl_description = "Toggle viewport preview for a baked texture layer"
    bl_options = {"REGISTER", "UNDO"}

    layer_name: StringProperty(
        name="Layer Name",
        description="Name of the layer to preview (empty to disable preview)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            return {"CANCELLED"}

        mp = node.node_tree.mp

        # Empty layer name = disable preview mode (return to material view)
        if not self.layer_name:
            if mp.layer_preview_mode:
                mp.layer_preview_mode = False
            return {"FINISHED"}

        # Find the layer by name
        layer_index = -1
        for i, layer in enumerate(mp.layers):
            if layer.name == self.layer_name:
                layer_index = i
                break

        if layer_index < 0:
            self.report({"WARNING"}, f"Layer '{self.layer_name}' not found")
            return {"CANCELLED"}

        # Check if we're already previewing this layer
        is_currently_previewing = (
            mp.layer_preview_mode
            and mp.active_layer_index == layer_index
        )

        if is_currently_previewing:
            # Toggle off - return to material view
            mp.layer_preview_mode = False
        else:
            # Switch to this layer's preview
            mp.active_layer_index = layer_index
            mp.layer_preview_mode_type = "LAYER"
            mp.layer_preview_mode = True

        return {"FINISHED"}


class MPreviewAllBakedChannels(bpy.types.Operator):
    """Preview all baked channels applied together as a complete PBR material.

    Shows the final result with all baked textures (Color, Normal, Roughness, etc.)
    combined into the material shader.
    """

    bl_idname = "wm.m_preview_all_baked_channels"
    bl_label = "Preview All Baked Channels"
    bl_description = "Preview all baked channels applied together as a complete material"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            return False
        # Check if there are any baked channels
        mp = node.node_tree.mp
        tree = node.node_tree
        for ch in mp.channels:
            baked_node = tree.nodes.get(ch.baked)
            if baked_node and baked_node.image:
                return True
        return False

    def execute(self, context):
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            return {"CANCELLED"}

        mp = node.node_tree.mp

        # Check if already in "all baked" preview mode
        if mp.use_baked and not mp.preview_mode:
            # Toggle off - return to live material view
            mp.use_baked = False
            self.report({"INFO"}, "Returned to live material view")
        else:
            # Disable layer preview mode first (mutual exclusion)
            if mp.layer_preview_mode:
                mp.layer_preview_mode = False
            # Enable baked mode and disable single channel preview
            mp.preview_mode = False  # Disable single channel preview
            mp.use_baked = True  # Show all baked channels together
            self.report({"INFO"}, "Previewing all baked channels")

        return {"FINISHED"}


class MToggleBakedChannelPreview(bpy.types.Operator):
    """Toggle preview mode for a baked channel image in the viewport.

    Switches between viewing the full composited material and viewing
    a single baked channel image (Color, Normal, etc.) in isolation.
    """

    bl_idname = "wm.m_toggle_baked_channel_preview"
    bl_label = "Toggle Baked Channel Preview"
    bl_description = "Toggle viewport preview for a baked channel image"
    bl_options = {"REGISTER", "UNDO"}

    channel_name: StringProperty(
        name="Channel Name",
        description="Name of the channel to preview (empty to disable baked mode)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            return {"CANCELLED"}

        mp = node.node_tree.mp

        # Empty channel name = disable baked mode (return to live material view)
        if not self.channel_name:
            # Turn off baked mode to show live layers
            if mp.use_baked:
                mp.use_baked = False
            # Also turn off preview mode if active
            if mp.preview_mode:
                mp.preview_mode = False
            return {"FINISHED"}

        # Find the channel by name
        channel_index = -1
        for i, channel in enumerate(mp.channels):
            if channel.name == self.channel_name:
                channel_index = i
                break

        if channel_index < 0:
            self.report({"WARNING"}, f"Channel '{self.channel_name}' not found")
            return {"CANCELLED"}

        # Check if we're already previewing this channel
        is_currently_previewing = (
            mp.preview_mode
            and mp.active_channel_index == channel_index
        )

        if is_currently_previewing:
            # Toggle off - return to baked material view (not live layers)
            mp.preview_mode = False
        else:
            # Disable layer preview mode first (mutual exclusion)
            if mp.layer_preview_mode:
                mp.layer_preview_mode = False
            # Make sure baked mode is on and switch to this channel's preview
            if not mp.use_baked:
                mp.use_baked = True
            mp.active_channel_index = channel_index
            mp.preview_mode = True

        return {"FINISHED"}


class MToggleBakedImagePreview(bpy.types.Operator):
    """Toggle preview mode for a baked mesh map image in the viewport.

    Displays a standalone baked image (AO, Cavity, etc.) that exists in
    bpy.data.images but is not attached to any layer.
    """

    bl_idname = "wm.m_toggle_baked_image_preview"
    bl_label = "Toggle Baked Image Preview"
    bl_description = "Toggle viewport preview for a baked mesh map image"
    bl_options = {"REGISTER", "UNDO"}

    image_name: StringProperty(
        name="Image Name",
        description="Name of the image to preview (empty to disable preview)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            return {"CANCELLED"}

        mp = node.node_tree.mp
        mat = get_active_material()
        if not mat or not mat.node_tree:
            return {"CANCELLED"}

        tree = mat.node_tree

        # Empty image name = disable preview mode (return to material view)
        if not self.image_name:
            self._disable_preview(mp, mat, tree)
            return {"FINISHED"}

        # Get the image from bpy.data.images
        image = bpy.data.images.get(self.image_name)
        if not image:
            self.report({"WARNING"}, f"Image '{self.image_name}' not found")
            return {"CANCELLED"}

        # Check if we're already previewing this image
        is_currently_previewing = mp.image_preview_name == self.image_name

        if is_currently_previewing:
            # Toggle off - return to material view
            self._disable_preview(mp, mat, tree)
        else:
            # Switch to this image's preview
            self._enable_preview(mp, mat, tree, image)

        return {"FINISHED"}

    def _disable_preview(self, mp, mat, tree):
        """Disable image preview and restore material connections."""
        # Remove temporary image texture node
        temp_node = tree.nodes.get(TEMP_IMAGE_PREVIEW_NODE)
        if temp_node:
            simple_remove_node(tree, temp_node)

        # Remove emission viewer and restore original connections
        remove_preview(mat)

        # Clear preview state
        mp.image_preview_name = ""

    def _enable_preview(self, mp, mat, tree, image):
        """Enable image preview with emission viewer."""
        # Disable other preview modes first (mutual exclusion)
        if mp.layer_preview_mode:
            mp.layer_preview_mode = False
        if mp.preview_mode:
            mp.preview_mode = False

        # Set view transform to sRGB for accurate preview
        set_srgb_view_transform()

        # Get material output
        output = get_active_mat_output_node(tree)
        if not output:
            return

        # Create or get temporary image texture node
        temp_node = tree.nodes.get(TEMP_IMAGE_PREVIEW_NODE)
        if not temp_node:
            temp_node = tree.nodes.new("ShaderNodeTexImage")
            temp_node.name = TEMP_IMAGE_PREVIEW_NODE
            temp_node.label = "Temp Preview"
            temp_node.hide = True
            temp_node.location = (output.location.x - 400, output.location.y + 60)

        # Set the image
        temp_node.image = image

        # Get or create emission viewer
        preview = get_preview(mat, output, False)
        if not preview:
            return

        # Connect: Image Texture → Emission Viewer → Material Output
        tree.links.new(temp_node.outputs["Color"], preview.inputs[0])
        tree.links.new(preview.outputs[0], output.inputs[0])

        # Update preview state
        mp.image_preview_name = image.name


classes = (
    MToggleBakedLayerPreview,
    MPreviewAllBakedChannels,
    MToggleBakedChannelPreview,
    MToggleBakedImagePreview,
)
