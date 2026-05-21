# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Node management functions for texcoord and linear/gamma correction nodes.

This module handles creating and managing texture coordinate nodes (particularly for decal
mapping) and linear/gamma correction nodes for layers, channels, and masks.
"""

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.constants import nsew_letters
from ..arrangements.layer_arrangements import rearrange_layer_nodes
from ..connections.layer_connections import reconnect_layer_nodes
from ...layer.check_layers import get_layer_enabled
from ...layer.get_channels import (
    get_channel_enabled,
    get_layer_channel_gamma_value,
    get_layer_channel_normal_gamma_value,
    get_layer_gamma_value,
    get_layer_mask_gamma_value,
)
from ...layer.layer_utils import get_layer_and_root_ch_from_layer_ch
from ...layer.mappings import is_mapping_possible
from ...lib.lib import DECAL_PROCESS
from ...node.create_nodes import check_new_node, new_node, replace_new_node
from ...node.get_nodes import get_layer_source
from ...node.node_utils import create_decal_empty, get_node_tree_lib, remove_node
from ...subtree.get_subtree import get_channel_source_tree, get_mask_tree, get_source_tree, get_tree


def check_layer_texcoord_nodes(layer, tree=None):
    """Check and update texture coordinate nodes for a layer.

    This function manages texcoord nodes for a layer, particularly for decal mapping.
    It creates or removes texcoord nodes, decal process nodes, and decal alpha nodes
    based on the layer's texcoord type and configuration. It also handles image extension
    settings for decal projections.

    Args:
        layer: The layer object to check and update texcoord nodes for.
        tree (optional): The node tree to modify. If None, retrieves it from the layer.
            Defaults to None.

    Returns:
        None
    """

    mp = layer.id_data.mp
    if not tree:
        tree = get_tree(layer)


    # Create texcoord node if decal is used
    texcoord = tree.nodes.get(layer.texcoord)
    layer_enabled = get_layer_enabled(layer)
    mapping_possible = is_mapping_possible(layer.type, layer)

    condition_met = layer_enabled and layer.texcoord_type == 'Decal' and mapping_possible

    if layer_enabled and layer.texcoord_type == 'Decal' and mapping_possible:

        # Set image extension type to clip
        image = None
        source = get_layer_source(layer)
        # Check for image in IMAGE layers or COLOR (Fill) layers with IMAGE source
        if source and hasattr(source, 'image'):
            if layer.type == 'IMAGE':
                image = source.image
            elif layer.type == 'COLOR' and hasattr(layer, 'source_type') and layer.source_type == 'IMAGE':
                image = source.image

        # Create new empty object if there's no texcoord yet
        if not texcoord:
            try:
                empty = create_decal_empty()
                texcoord = new_node(tree, layer, 'texcoord', 'ShaderNodeTexCoord', 'TexCoord')
                texcoord.object = empty
            except Exception as e:
                logger.error("Failed to create decal texcoord node: %s", e, exc_info=True)

        decal_process = tree.nodes.get(layer.decal_process)
        if not decal_process:
            try:
                decal_process = new_node(tree, layer, 'decal_process', 'ShaderNodeGroup', 'Decal Process')
                decal_process.node_tree = get_node_tree_lib(DECAL_PROCESS)
            except Exception as e:
                logger.error("Failed to create decal process node: %s", e, exc_info=True)

            # Set image extension only after decal process node is initialized
            if image and source:
                layer.original_image_extension = source.extension
                source.extension = 'CLIP'

        # Set decal aspect ratio
        if image and image.size[0] > 0 and image.size[1] > 0:
            if image.size[0] > image.size[1]:
                decal_process.inputs['Scale'].default_value = (image.size[1] / image.size[0], 1.0, 1.0)
            else:
                decal_process.inputs['Scale'].default_value = (1.0, image.size[0] / image.size[1], 1.0)

        # Create decal alpha nodes
        for i, ch in enumerate(layer.channels):
            root_ch = mp.channels[i]
            ch_enabled = get_channel_enabled(ch)
            if ch_enabled:
                decal_alpha = check_new_node(tree, ch, 'decal_alpha', 'ShaderNodeMath', 'Decal Alpha')
                if decal_alpha.operation != 'MULTIPLY':
                    decal_alpha.operation = 'MULTIPLY'
            else:
                remove_node(tree, ch, 'decal_alpha')

            if root_ch.type == 'NORMAL':
                if ch_enabled and root_ch.enable_smooth_bump:
                    for letter in nsew_letters:
                        decal_alpha = check_new_node(tree, ch, 'decal_alpha_' + letter, 'ShaderNodeMath', 'Decal Alpha ' + letter.upper())
                        if decal_alpha.operation != 'MULTIPLY':
                            decal_alpha.operation = 'MULTIPLY'
                else:
                    for letter in nsew_letters:
                        remove_node(tree, ch, 'decal_alpha_' + letter)

    else:
        if not texcoord or not hasattr(texcoord, 'object') or not texcoord.object:
            remove_node(tree, layer, 'texcoord')
        remove_node(tree, layer, 'decal_process')

        for i, ch in enumerate(layer.channels):
            root_ch = mp.channels[i]
            remove_node(tree, ch, 'decal_alpha')

            if root_ch.type == 'NORMAL':
                for letter in nsew_letters:
                    remove_node(tree, ch, 'decal_alpha_' + letter)

        # Recover image extension type for IMAGE layers or COLOR layers with IMAGE source
        is_image_layer = layer.type == 'IMAGE'
        is_color_image_layer = (layer.type == 'COLOR' and hasattr(layer, 'source_type')
                                and layer.source_type == 'IMAGE')
        if (is_image_layer or is_color_image_layer) and layer.original_texcoord == 'Decal' and layer.original_image_extension != '':
            source = get_layer_source(layer)
            if source:
                source.extension = layer.original_image_extension
                layer.original_image_extension = ''

    # Save original texcoord type
    if layer.original_texcoord != layer.texcoord_type:
        layer.original_texcoord = layer.texcoord_type


def check_layer_image_linear_node(layer, source_tree=None):
    """Check and update the linear/gamma correction node for a layer's image.

    This function creates or removes a gamma correction node for a layer based on its
    gamma value. If the gamma value is not 1.0, a gamma node is created with the
    appropriate correction value. Otherwise, the gamma node is removed.

    Args:
        layer: The layer object to check and update the linear node for.
        source_tree (optional): The source tree containing the layer's nodes. If None,
            retrieves it from the layer. Defaults to None.

    Returns:
        None
    """

    mp = layer.id_data.mp

    if not source_tree: source_tree = get_source_tree(layer)

    gamma = get_layer_gamma_value(layer)

    if gamma != 1.0:
        # Create linear node
        linear = check_new_node(source_tree, layer, 'linear', 'ShaderNodeGamma', 'Linear')
        linear.inputs[1].default_value = gamma
    else:
        # Delete linear node
        remove_node(source_tree, layer, 'linear')


def check_layer_channel_linear_node(ch, layer=None, root_ch=None, reconnect=False):
    """Check and update linear/gamma correction nodes for a layer channel.

    This function manages gamma correction nodes for a layer channel. It creates or removes
    gamma nodes based on the channel's gamma values. For normal channels, it can handle
    two separate linear nodes (linear and linear_1) for different correction purposes.
    Optionally reconnects and rearranges nodes after making changes.

    Args:
        ch: The channel object to check and update linear nodes for.
        layer (optional): The parent layer object. If None, derives it from the channel.
            Defaults to None.
        root_ch (optional): The root channel object. If None, derives it from the channel.
            Defaults to None.
        reconnect (bool, optional): If True, reconnects and rearranges layer nodes after
            making changes. Defaults to False.

    Returns:
        None
    """

    mp = ch.id_data.mp
    if not layer or not root_ch: layer, root_ch = get_layer_and_root_ch_from_layer_ch(ch)

    source_tree = get_channel_source_tree(ch, layer)

    gamma = get_layer_channel_gamma_value(ch, layer, root_ch)

    if gamma != 1.0:
        # Create linear node
        if root_ch.type == 'VALUE':
            linear = replace_new_node(source_tree, ch, 'linear', 'ShaderNodeMath', 'Linear')
            linear.operation = 'POWER'
        else: linear = replace_new_node(source_tree, ch, 'linear', 'ShaderNodeGamma', 'Linear')
        linear.inputs[1].default_value = gamma
    else:
        # Delete linear node
        remove_node(source_tree, ch, 'linear')


    if root_ch.type == 'NORMAL':
        gamma_1 = get_layer_channel_normal_gamma_value(ch, layer, root_ch)
        if gamma_1 != 1.0:
            # Create linear node
            layer_tree = get_tree(layer)
            linear_1 = replace_new_node(layer_tree, ch, 'linear_1', 'ShaderNodeGamma', 'Linear 1')
            linear_1.inputs[1].default_value = gamma_1
        else:
            # Delete linear node
            remove_node(source_tree, ch, 'linear_1')

    if reconnect:
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)


def check_mask_image_linear_node(mask, mask_tree=None):
    """Check and update the linear/gamma correction node for a mask's image.

    This function creates or removes a gamma correction node for a mask based on its
    gamma value. If the gamma value is not 1.0, a gamma node is created with the
    appropriate correction value. Otherwise, the gamma node is removed.

    Args:
        mask: The mask object to check and update the linear node for.
        mask_tree (optional): The mask tree containing the mask's nodes. If None,
            retrieves it from the mask. Defaults to None.

    Returns:
        None
    """

    if not mask_tree: mask_tree = get_mask_tree(mask)

    gamma = get_layer_mask_gamma_value(mask, mask_tree)

    if gamma != 1.0:
        # Create linear node
        linear = check_new_node(mask_tree, mask, 'linear', 'ShaderNodeGamma', 'Linear')
        linear.inputs[1].default_value = gamma
    else:
        # Delete linear node
        remove_node(mask_tree, mask, 'linear')
