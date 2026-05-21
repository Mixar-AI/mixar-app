# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer removal helpers: functions for removing layers and cleaning up resources."""

import bpy

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.element.update_elements import remove_decal_object
from ....core.node.get_nodes import (
    get_channel_source,
    get_channel_source_1,
    get_layer_source,
    get_mask_source,
)
from ....core.node.node_utils import remove_node
from ....core.subtree.get_subtree import (
    get_channel_source_tree,
    get_mask_tree,
    get_source_tree,
    get_tree,
)
from ....utils.blender_commons import get_active_object, remove_datablock
from ....utils.constants import PARALLAX
from ...image_atlas.image_atlas_operators_helper import get_entities_with_specific_segment
from ...udim.udim_utils import remove_udim_atlas_segment_by_name


def remove_layer(mp, index, remove_on_disk=False):
    """Remove a layer and clean up associated resources.

    Args:
        mp: MPaint data structure.
        index (int): Index of layer to remove.
        remove_on_disk (bool, optional): Whether to delete image files from disk. Defaults to False.
    """
    group_tree = mp.id_data
    obj = get_active_object()
    layer = mp.layers[index]
    layer_tree = get_tree(layer)
    mat = obj.active_material
    wm = bpy.context.window_manager

    # Dealing with decal object
    remove_decal_object(layer_tree, layer)

    # Dealing with image atlas segments
    if layer.type == "IMAGE":
        src = get_layer_source(layer)
        if src:
            if src.image.yia.is_image_atlas and layer.segment_name != "":
                segment = src.image.yia.segments.get(layer.segment_name)
                entities = get_entities_with_specific_segment(mp, segment)
                if len(entities) == 1:
                    segment.unused = True
            elif src.image.yua.is_udim_atlas and layer.segment_name != "":
                remove_udim_atlas_segment_by_name(src.image, layer.segment_name, mp=mp)

    # Remove the source first to remove image
    source_tree = get_source_tree(layer)
    remove_node(source_tree, layer, "source", remove_on_disk=remove_on_disk)

    # Remove channel source
    for ch in layer.channels:
        src = get_channel_source(ch)
        if src and src.type == "TEX_IMAGE" and src.image:
            ch_tree = get_channel_source_tree(ch, layer)
            remove_node(ch_tree, ch, "source", remove_on_disk=remove_on_disk)

        src = get_channel_source_1(ch)
        if src and src.type == "TEX_IMAGE" and src.image:
            remove_node(layer_tree, ch, "source_1", remove_on_disk=remove_on_disk)

    # Remove Mask source
    for mask in layer.masks:

        # Dealing with decal object
        remove_decal_object(layer_tree, mask)

        # Dealing with image atlas segments
        if mask.type == "IMAGE":
            src = get_mask_source(mask)
            if not src:
                continue
            if src.image.yia.is_image_atlas and mask.segment_name != "":
                segment = src.image.yia.segments.get(mask.segment_name)
                entities = get_entities_with_specific_segment(mp, segment)
                if len(entities) == 1:
                    segment.unused = True
            elif src.image.yua.is_udim_atlas and mask.segment_name != "":
                remove_udim_atlas_segment_by_name(src.image, mask.segment_name, mp=mp)

        mask_tree = get_mask_tree(mask)
        remove_node(mask_tree, mask, "source", remove_on_disk=remove_on_disk)

    # Remove node group and layer tree
    if layer_tree:
        layer_node = group_tree.nodes.get(layer.group_node)
        remove_datablock(
            bpy.data.node_groups, layer_tree, user=layer_node, user_prop="node_tree"
        )
    if layer.trash_group_node != "":
        trash = group_tree.nodes.get(mp.trash)
        if trash:
            trash.node_tree.nodes.remove(
                trash.node_tree.nodes.get(layer.trash_group_node)
            )
    else:
        layer_node = group_tree.nodes.get(layer.group_node)
        if layer_node:
            group_tree.nodes.remove(layer_node)

    # Remove node group from parallax tree
    parallax = group_tree.nodes.get(PARALLAX)
    if parallax:
        depth_source_0 = parallax.node_tree.nodes.get("_depth_source_0")
        depth_source_0.node_tree.nodes.remove(
            depth_source_0.node_tree.nodes.get(layer.depth_group_node)
        )

    # Reset UI (layer_ui may be absent on older/rebuilt UI state)
    if hasattr(wm.mpui, 'layer_ui'):
        try:
            wm.mpui.layer_ui.expand_content = False
            wm.mpui.layer_ui.expand_source = False
            wm.mpui.layer_ui.expand_channels = False
            wm.mpui.layer_ui.expand_masks = False
            wm.mpui.layer_ui.expand_vector = False

            if hasattr(wm.mpui.layer_ui, 'channels') and len(wm.mpui.layer_ui.channels) > 0:
                for i, ch in enumerate(layer.channels):
                    if i < len(wm.mpui.layer_ui.channels):
                        wm.mpui.layer_ui.channels[i].expand_content = False
        except IndexError:
            wm.mpui.need_update = True

    wm.mpui.need_update = True

    # Delete the layer
    mp.layers.remove(index)
