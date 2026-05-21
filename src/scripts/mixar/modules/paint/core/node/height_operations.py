# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...utils.constants import BAKED_PARALLAX, PARALLAX
from ..layer.get_channels import get_height_channel
from ..subtree.get_subtree import get_displacement_max_height, get_lower_neighbor, get_tree, get_transition_disp_delta
from ..node.node_graph import get_layer_channel_bump_distance, get_transition_bump_max_distance

def update_layer_bump_distance(height_ch, height_root_ch, layer, tree=None):
    """Update the bump distance values for a layer's height processing nodes.

    This function updates the bump and displacement processing parameters for a layer,
    including maximum height values, transition heights, and delta values for the
    height processing and normal processing nodes.

    Args:
        height_ch: The height channel object containing height processing configuration.
        height_root_ch: The root height channel used for displacement calculations.
        layer: The layer object to update bump distance for.
        tree: The node tree containing the layer nodes. Defaults to None, which will
              retrieve the tree automatically using get_tree(layer).

    Returns:
        None. Updates are made in-place to the node tree.
    """
    mp = layer.id_data.mp
    if not tree: tree = get_tree(layer)
    if not tree: return
    layer_node = layer.id_data.nodes.get(layer.group_node)

    height_proc = tree.nodes.get(height_ch.height_proc)
    if height_proc and layer.type != 'GROUP':

        if height_ch.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:

            inp = height_proc.inputs.get('Value Max Height')
            if inp: inp.default_value = get_layer_channel_bump_distance(layer, height_ch)

            inp = height_proc.inputs.get('Transition Max Height')
            if inp: inp.default_value = get_transition_bump_max_distance(height_ch)

            inp = height_proc.inputs.get('Delta')
            if inp: inp.default_value = get_transition_disp_delta(layer, height_ch)

    normal_proc = tree.nodes.get(height_ch.normal_proc)
    if normal_proc:

        max_height = get_displacement_max_height(height_root_ch, layer)

        if 'Max Height' in normal_proc.inputs:
            normal_proc.inputs['Max Height'].default_value = max_height

def update_layer_bump_process_max_height(height_root_ch, layer, tree=None):
    """Update the maximum height value for a layer's bump process node.

    Sets the 'Max Height' input of the layer's bump process node based on the
    displacement max height of the previous (lower) neighboring layer. If there
    is no previous layer, sets the max height to 0.0.

    Args:
        height_root_ch: The root height channel used for displacement calculations.
        layer: The layer object whose bump process needs updating.
        tree: The node tree containing the layer nodes. Defaults to None, which will
              retrieve the tree automatically using get_tree(layer).

    Returns:
        None. Updates are made in-place to the node tree.
    """
    mp = layer.id_data.mp
    if not tree: tree = get_tree(layer)
    if not tree: return

    bump_process = tree.nodes.get(layer.bump_process)
    if not bump_process: return

    prev_idx, prev_layer = get_lower_neighbor(layer)
    if prev_layer: 
        max_height = get_displacement_max_height(height_root_ch, prev_layer)
    else: max_height = 0.0

    if 'Max Height' in bump_process.inputs and bump_process.inputs['Max Height'].default_value != max_height:
        bump_process.inputs['Max Height'].default_value = max_height

def update_displacement_height_ratio(root_ch, max_height=None):
    """Update displacement height ratio across all parallax and height processing nodes.

    Updates the maximum height values for baked parallax, parallax, end linear nodes,
    and all UV parallax preparation nodes. Also updates the bump process for all layers
    in reverse order.

    Args:
        root_ch: The root channel object containing height and parallax configuration.
        max_height: The maximum displacement height value to set. Defaults to None,
                   which will calculate the max height using get_displacement_max_height(root_ch).

    Returns:
        None. Updates are made in-place to the node tree and all layer bump processes.
    """
    group_tree = root_ch.id_data
    mp = group_tree.mp

    if not max_height: max_height = get_displacement_max_height(root_ch)

    baked_parallax = group_tree.nodes.get(BAKED_PARALLAX)
    if baked_parallax:
        #baked_parallax.inputs['depth_scale'].default_value = max_height
        depth_source_0 = baked_parallax.node_tree.nodes.get('_depth_source_0')
        if depth_source_0:
            pack = depth_source_0.node_tree.nodes.get('_normalize')
            if pack:
                if max_height != 0.0:
                    pack.inputs['Max Height'].default_value = max_height
                else: pack.inputs['Max Height'].default_value = 1.0

    parallax = group_tree.nodes.get(PARALLAX)
    if parallax:
        depth_source_0 = parallax.node_tree.nodes.get('_depth_source_0')
        if depth_source_0:
            pack = depth_source_0.node_tree.nodes.get('_normalize')
            if pack:
                if max_height != 0.0:
                    pack.inputs['Max Height'].default_value = max_height
                else: pack.inputs['Max Height'].default_value = 1.0

    end_linear = group_tree.nodes.get(root_ch.end_linear)
    if end_linear:
        if 'Max Height' in end_linear.inputs:
            if max_height != 0.0:
                end_linear.inputs['Max Height'].default_value = max_height
            else: end_linear.inputs['Max Height'].default_value = 1.0

    for uv in mp.uvs:
        parallax_prep = group_tree.nodes.get(uv.parallax_prep)
        if parallax_prep:
            parallax_prep.inputs['depth_scale'].default_value = max_height * root_ch.parallax_height_tweak

    # Update layer bump process
    for layer in reversed(mp.layers):
        update_layer_bump_process_max_height(root_ch, layer)
        height_ch = get_height_channel(layer)
        if height_ch:
            update_layer_bump_distance(height_ch, root_ch, layer)
