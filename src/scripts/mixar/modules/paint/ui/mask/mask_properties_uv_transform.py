# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update callbacks for mask UV, transform, blur, and blend type changes."""

import re

from ...core.element.update_uv import refresh_temp_uv
from ...core.io.input_outputs.input_outputs_layer_ios import check_layer_tree_ios
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.layer.mappings import update_mapping
from ...core.lib.lib import BLUR_VECTOR
from ...core.node.check_nodes import (
    check_all_layer_channel_io_and_nodes,
    check_mask_mix_nodes,
    check_uv_nodes,
)
from ...core.node.create_nodes import new_node
from ...core.node.node_utils import get_node_tree_lib, remove_node
from ...core.subtree.get_subtree import get_tree
from ...utils.blender_commons import get_active_object
from ...utils.constants import TEMP_UV


def update_mask_uv_name(self, context):
    """Update callback when mask UV map name changes.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    obj = get_active_object()
    mp = self.id_data.mp
    mpui = context.window_manager.mpui
    if mp.halt_update:
        return

    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    mask_idx = int(match.group(2))
    active_layer = mp.layers[mp.active_layer_index]
    tree = get_tree(layer)
    mask = self

    if (
        mask.type
        in {"HEMI", "OBJECT_INDEX", "COLOR_ID", "BACKFACE", "EDGE_DETECT", "AO"}
        or mask.texcoord_type != "UV"
    ):
        return

    # Cannot use temp uv as standard uv
    if mask.uv_name in {TEMP_UV, ""}:
        if len(mp.uvs) > 0:
            for uv in mp.uvs:
                mask.uv_name = uv.name
                break

    # Update uv layer
    if mask.active_edit and obj.type == "MESH" and layer == active_layer:

        if mask.segment_name != "":
            refresh_temp_uv(obj, mask)
        else:

            if hasattr(obj.data, "uv_textures"):
                uv_layers = obj.data.uv_textures
            else:
                uv_layers = obj.data.uv_layers

            uv_layers.active = uv_layers.get(mask.uv_name)

    # Update global uv
    check_uv_nodes(mp)

    # Update layer tree inputs
    check_all_layer_channel_io_and_nodes(layer, tree)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)


def update_mask_blend_type(self, context):
    """Update callback when mask blend type changes.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """

    mp = self.id_data.mp
    if mp.halt_update:
        return
    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    tree = get_tree(layer)
    mask = self

    # dirs = [d for d in neighbor_directions]
    # dirs.extend(['pure', 'remains', 'normal'])

    # for c in mask.channels:
    #    mix = tree.nodes.get(c.mix)
    #    if mix: mix.blend_type = mask.blend_type
    #    for d in dirs:
    #        mix = tree.nodes.get(getattr(c, 'mix_' + d))
    #        if mix: mix.blend_type = mask.blend_type

    check_mask_mix_nodes(layer, tree, mask)

    # Reconnect nodes
    reconnect_layer_nodes(layer)

    # Rearrange nodes
    rearrange_layer_nodes(layer)


def update_mask_transform(self, context):
    """Update callback when mask transform properties change.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    update_mapping(self)


def update_mask_blur_vector(self, context):
    """Update callback when mask blur vector enable state changes.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    mask = self
    tree = get_tree(layer)

    if mask.enable_blur_vector:
        blur_vector = new_node(
            tree, mask, "blur_vector", "ShaderNodeGroup", "Mask Blur Vector"
        )
        blur_vector.node_tree = get_node_tree_lib(BLUR_VECTOR)
        blur_vector.inputs[0].default_value = mask.blur_vector_factor / 100.0
    else:
        remove_node(tree, mask, "blur_vector")

    check_layer_tree_ios(layer, tree)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)
