# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask removal functions for cleaning up masks and their associated nodes.

This module contains functions for removing masks, mask channels, and
cleaning up all associated node data.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.update_elements import remove_decal_object
from ...core.element.update_fcurves import remove_entity_fcurves, shift_mask_fcurves_up
from ...core.modifier.mask_modifier import delete_mask_modifier_nodes
from ...core.node.get_nodes import get_mask_source
from ...core.node.node_utils import remove_node
from ...core.subtree.get_subtree import get_tree
from ...core.subtree.update_subtree import disable_mask_source_tree
from ..list_item.list_item_operators_helper import refresh_list_items
from ..udim.udim_utils import remove_udim_atlas_segment_by_name


def remove_mask_channel_nodes(tree, c):
    """Remove all mix nodes associated with a mask channel.

    Args:
        tree: Shader node tree containing the nodes.
        c: YLayerMaskChannel property group whose nodes should be removed.
    """
    remove_node(tree, c, 'mix')
    remove_node(tree, c, 'mix_n')
    remove_node(tree, c, 'mix_s')
    remove_node(tree, c, 'mix_e')
    remove_node(tree, c, 'mix_w')
    remove_node(tree, c, 'mix_pure')
    remove_node(tree, c, 'mix_remains')
    remove_node(tree, c, 'mix_normal')
    remove_node(tree, c, 'mix_vdisp')
    remove_node(tree, c, 'mix_limit')
    remove_node(tree, c, 'mix_limit_normal')


def remove_mask_channel(tree, layer, ch_index):
    """Remove a specific channel from all masks in a layer.

    Args:
        tree: Shader node tree containing the mask nodes.
        layer: YLayer property group containing the masks.
        ch_index (int): Index of the channel to remove.
    """
    # Remove mask nodes
    for mask in layer.masks:
        # Get channels
        c = mask.channels[ch_index]
        ch = layer.channels[ch_index]

        # Remove mask channel nodes first
        remove_mask_channel_nodes(tree, c)

    # Remove the mask itself
    for mask in layer.masks:
        mask.channels.remove(ch_index)


def remove_mask(layer, mask, obj, refresh_list=True):
    """Remove a mask from a layer and clean up all associated nodes and data.

    Args:
        layer: YLayer property group containing the mask.
        mask: YLayerMask property group to remove.
        obj: Blender object that owns the material.
        refresh_list (bool, optional): Whether to refresh UI list items. Defaults to True.
    """
    tree = get_tree(layer)
    mp = layer.id_data.mp
    mat = obj.active_material

    # Get mask index
    mask_index = next((i for i, m in enumerate(layer.masks) if m == mask), None)
    if mask_index is None:
        logger.warning(
            "remove_mask: mask '%s' not found in layer '%s'", mask.name, layer.name
        )
        return

    # Dealing with decal object
    remove_decal_object(tree, mask)

    # Remove mask fcurves first
    remove_entity_fcurves(mask)
    shift_mask_fcurves_up(layer, mask_index)

    # Dealing with image atlas segments
    if mask.type == 'IMAGE':
        src = get_mask_source(mask)
        if src and src.image:
            image = src.image
            if mask.segment_name != '':
                if image.yia.is_image_atlas:
                    segment = image.yia.segments.get(mask.segment_name)
                    if segment:
                        segment.unused = True
                elif image.yua.is_udim_atlas:
                    logger.debug('ZEGMENT: %s', mask.segment_name)
                    remove_udim_atlas_segment_by_name(image, mask.segment_name, mp=mp)

    disable_mask_source_tree(layer, mask)

    remove_node(tree, mask, 'source')
    remove_node(tree, mask, 'baked_source')
    remove_node(tree, mask, 'blur_vector')
    remove_node(tree, mask, 'separate_color_channels')
    remove_node(tree, mask, 'mapping')
    remove_node(tree, mask, 'texcoord')
    remove_node(tree, mask, 'baked_mapping')
    remove_node(tree, mask, 'linear')
    remove_node(tree, mask, 'uv_map')
    remove_node(tree, mask, 'uv_neighbor')

    # Remove mask modifiers
    for m in mask.modifiers:
        delete_mask_modifier_nodes(tree, m)

    # Remove mask channel nodes
    for c in mask.channels:
        remove_mask_channel_nodes(tree, c)

    # Remove mask
    layer.masks.remove(mask_index)

    # Adjust active_mask_index after removal to prevent invalid index
    if hasattr(layer, 'active_mask_index'):
        if len(layer.masks) == 0:
            layer.active_mask_index = -1
        elif layer.active_mask_index >= len(layer.masks):
            layer.active_mask_index = max(0, len(layer.masks) - 1)

    # Update list items
    if refresh_list:
        refresh_list_items(mp)
