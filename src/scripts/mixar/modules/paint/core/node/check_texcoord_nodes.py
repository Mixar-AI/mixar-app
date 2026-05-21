# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Texture coordinate node operations for layers and masks.

This module contains functions for checking and updating texture coordinate nodes
for both layers and masks, including decal processing.
"""

from ...utils.constants import nsew_letters
from ..io.input_outputs.input_outputs import create_decal_empty
from ..layer.check_layers import get_layer_enabled, get_mask_enabled
from ..layer.get_channels import get_channel_enabled
from ..layer.layer_utils import get_height_channel, get_root_height_channel
from ..layer.mappings import is_mapping_possible
from ..lib.lib import DECAL_PROCESS
from ..node.create_nodes import check_new_node, new_node
from ..node.get_nodes import get_layer_source, get_mask_source
from ..node.node_utils import get_node_tree_lib, remove_node
from ..subtree.get_subtree import get_tree


def check_mask_texcoord_nodes(layer, mask, tree=None):
    """
    Check and update texture coordinate nodes for a mask.

    Parameters:
        layer: Layer object containing the mask.
        mask: Mask object to check texture coordinate nodes for.
        tree (optional): Node tree to check. If None, will be obtained from layer. Default: None.

    Returns:
        None. Nodes are checked and updated directly in the tree.
    """
    mp = layer.id_data.mp
    if not tree:
        tree = get_tree(layer)

    height_root_ch = get_root_height_channel(mp)
    height_ch = get_height_channel(layer)
    height_ch_enabled = get_channel_enabled(height_ch) if height_ch else False

    # Create texcoord node if decal is used
    texcoord = tree.nodes.get(mask.texcoord)
    if (
        get_mask_enabled(mask)
        and mask.texcoord_type == "Decal"
        and is_mapping_possible(mask.type)
    ):

        # Set image extension type to clip
        image = None
        source = get_mask_source(mask)
        if mask.type == "IMAGE" and source:
            image = source.image

        # Create new empty object if there's no texcoord yet
        if not texcoord:
            empty = create_decal_empty()
            texcoord = new_node(
                tree, mask, "texcoord", "ShaderNodeTexCoord", "TexCoord"
            )
            texcoord.object = empty

        decal_process = tree.nodes.get(mask.decal_process)
        if not decal_process:
            decal_process = new_node(
                tree, mask, "decal_process", "ShaderNodeGroup", "Decal Process"
            )
            decal_process.node_tree = get_node_tree_lib(DECAL_PROCESS)

            # Set image extension only after decal process node is initialized
            if image and source:
                mask.original_image_extension = source.extension
                source.extension = "CLIP"

        # Set decal aspect ratio
        if image and image.size[0] > 0 and image.size[1] > 0:
            if image.size[0] > image.size[1]:
                decal_process.inputs["Scale"].default_value = (
                    image.size[1] / image.size[0],
                    1.0,
                    1.0,
                )
            else:
                decal_process.inputs["Scale"].default_value = (
                    1.0,
                    image.size[0] / image.size[1],
                    1.0,
                )

        decal_alpha = check_new_node(
            tree, mask, "decal_alpha", "ShaderNodeMath", "Decal Alpha"
        )
        if decal_alpha.operation != "MULTIPLY":
            decal_alpha.operation = "MULTIPLY"

        if height_ch and height_ch_enabled and height_root_ch.enable_smooth_bump:
            for letter in nsew_letters:
                decal_alpha = check_new_node(
                    tree,
                    mask,
                    "decal_alpha_" + letter,
                    "ShaderNodeMath",
                    "Decal Alpha " + letter.upper(),
                )
                if decal_alpha.operation != "MULTIPLY":
                    decal_alpha.operation = "MULTIPLY"
        else:
            for letter in nsew_letters:
                remove_node(tree, mask, "decal_alpha_" + letter)

    else:
        if not texcoord or not hasattr(texcoord, "object") or not texcoord.object:
            remove_node(tree, mask, "texcoord")
        remove_node(tree, mask, "decal_process")
        remove_node(tree, mask, "decal_alpha")

        if height_ch:
            for letter in nsew_letters:
                remove_node(tree, mask, "decal_alpha_" + letter)

        # Recover image extension type
        if (
            mask.type == "IMAGE"
            and mask.original_texcoord == "Decal"
            and mask.original_image_extension != ""
        ):
            source = get_mask_source(mask)
            if source:
                source.extension = mask.original_image_extension
                mask.original_image_extension = ""

    # Save original texcoord type
    if mask.original_texcoord != mask.texcoord_type:
        mask.original_texcoord = mask.texcoord_type


def check_layer_texcoord_nodes(layer, tree=None):
    """
    Check and update texture coordinate nodes for a layer.

    Parameters:
        layer: Layer object to check texture coordinate nodes for.
        tree (optional): Node tree to check. If None, will be obtained from layer. Default: None.

    Returns:
        None. Nodes are checked and updated directly in the tree.
    """
    mp = layer.id_data.mp
    if not tree:
        tree = get_tree(layer)

    # Create texcoord node if decal is used
    texcoord = tree.nodes.get(layer.texcoord) if tree else None

    if (
        get_layer_enabled(layer)
        and layer.texcoord_type == "Decal"
        and is_mapping_possible(layer.type, layer)
    ):
        # Set image extension type to clip
        image = None
        source = get_layer_source(layer)
        # Check for image in IMAGE layers or COLOR (Fill) layers with IMAGE source
        if source and hasattr(source, 'image'):
            if layer.type == "IMAGE":
                image = source.image
            elif layer.type == "COLOR" and hasattr(layer, 'source_type') and layer.source_type == "IMAGE":
                image = source.image

        # Create new empty object if there's no texcoord yet
        if not texcoord:
            empty = create_decal_empty()
            texcoord = new_node(
                tree, layer, "texcoord", "ShaderNodeTexCoord", "TexCoord"
            )
            texcoord.object = empty

        decal_process = tree.nodes.get(layer.decal_process)
        if not decal_process:
            decal_process = new_node(
                tree, layer, "decal_process", "ShaderNodeGroup", "Decal Process"
            )
            decal_process.node_tree = get_node_tree_lib(DECAL_PROCESS)

            # Set image extension only after decal process node is initialized
            if image and source:
                layer.original_image_extension = source.extension
                source.extension = "CLIP"

        # Set decal aspect ratio
        if image and image.size[0] > 0 and image.size[1] > 0:
            if image.size[0] > image.size[1]:
                decal_process.inputs["Scale"].default_value = (
                    image.size[1] / image.size[0],
                    1.0,
                    1.0,
                )
            else:
                decal_process.inputs["Scale"].default_value = (
                    1.0,
                    image.size[0] / image.size[1],
                    1.0,
                )

        # Create decal alpha nodes
        for i, ch in enumerate(layer.channels):
            root_ch = mp.channels[i]
            ch_enabled = get_channel_enabled(ch)
            if ch_enabled:
                decal_alpha = check_new_node(
                    tree, ch, "decal_alpha", "ShaderNodeMath", "Decal Alpha"
                )
                if decal_alpha.operation != "MULTIPLY":
                    decal_alpha.operation = "MULTIPLY"
            else:
                remove_node(tree, ch, "decal_alpha")

            if root_ch.type == "NORMAL":
                if ch_enabled and root_ch.enable_smooth_bump:
                    for letter in nsew_letters:
                        decal_alpha = check_new_node(
                            tree,
                            ch,
                            "decal_alpha_" + letter,
                            "ShaderNodeMath",
                            "Decal Alpha " + letter.upper(),
                        )
                        if decal_alpha.operation != "MULTIPLY":
                            decal_alpha.operation = "MULTIPLY"
                else:
                    for letter in nsew_letters:
                        remove_node(tree, ch, "decal_alpha_" + letter)

    else:
        if not texcoord or not hasattr(texcoord, "object") or not texcoord.object:
            remove_node(tree, layer, "texcoord")
        remove_node(tree, layer, "decal_process")

        for i, ch in enumerate(layer.channels):
            root_ch = mp.channels[i]
            remove_node(tree, ch, "decal_alpha")

            if root_ch.type == "NORMAL":
                for letter in nsew_letters:
                    remove_node(tree, ch, "decal_alpha_" + letter)

        # Recover image extension type for IMAGE layers or COLOR layers with IMAGE source
        is_image_layer = layer.type == "IMAGE"
        is_color_image_layer = (layer.type == "COLOR" and hasattr(layer, 'source_type')
                                and layer.source_type == "IMAGE")
        if (
            (is_image_layer or is_color_image_layer)
            and layer.original_texcoord == "Decal"
            and layer.original_image_extension != ""
        ):
            source = get_layer_source(layer)
            if source:
                source.extension = layer.original_image_extension
                layer.original_image_extension = ""

    # Save original texcoord type
    if layer.original_texcoord != layer.texcoord_type:
        layer.original_texcoord = layer.texcoord_type
