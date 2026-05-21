# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
UV resolution settings functions.
"""

import re

from ......config.logging_config import get_logger
from ...layer.get_channels import get_height_channel
from ...layer.mappings import get_layer_mapping, get_mask_mapping
from ...node.get_nodes import get_channel_source, get_layer_source, get_mask_source
from ...subtree.get_subtree import get_mask_tree, get_tree
from ..get_elements import get_correct_uv_neighbor_resolution

logger = get_logger(__name__)


def set_uv_neighbor_resolution(entity, uv_neighbor=None, source=None, use_baked=False):
    """
    Set the resolution for UV neighbor node based on entity type and height channel.

    This function configures the UV neighbor resolution by analyzing the entity type
    (layer, mask, or channel), retrieving the appropriate source and tree, and setting
    the ResX and ResY input values on the UV neighbor node based on the height channel
    and image dimensions.

    Parameters
    ----------
    entity : object
        The entity object (layer, mask, or channel) whose UV neighbor resolution needs to be set.
    uv_neighbor : object, optional
        The UV neighbor node object. If None, it will be retrieved from the tree. Default is None.
    source : object, optional
        The source node object. If None, it will be retrieved based on entity type. Default is None.
    use_baked : bool, optional
        Whether to use baked source when retrieving the source node. Default is False.

    Returns
    -------
    None
    """
    mp = entity.id_data.mp
    m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())
    m3 = re.match(r'^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$', entity.path_from_id())

    if m1:
        layer = mp.layers[int(m1.group(1))]
        tree = get_tree(entity)
        if not source:
            source = get_layer_source(entity, get_baked=use_baked)
        entity_type = entity.type
        scale = entity.scale
    elif m2:
        layer = mp.layers[int(m2.group(1))]
        tree = get_tree(layer)
        if not source:
            source = get_mask_source(entity, get_baked=use_baked)
        entity_type = entity.type
        scale = entity.scale
    elif m3:
        layer = mp.layers[int(m3.group(1))]
        tree = get_tree(layer)
        if not source:
            source = get_channel_source(entity, layer, tree)
        entity_type = entity.override_type
        scale = layer.scale
    else:
        return

    if not uv_neighbor:
        uv_neighbor = tree.nodes.get(entity.uv_neighbor)
    if not uv_neighbor:
        return

    if 'ResX' not in uv_neighbor.inputs:
        return

    # Get height channel
    height_ch = get_height_channel(layer)
    if not height_ch:
        return

    # Get Image
    image = source.image if entity_type == 'IMAGE' else None

    # Get correct resolution
    res_x, res_y = get_correct_uv_neighbor_resolution(height_ch, image)

    # Set UV Neighbor resolution
    uv_neighbor.inputs['ResX'].default_value = res_x
    uv_neighbor.inputs['ResY'].default_value = res_y
