# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import time

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)
from ...core.element.frame_utils import rearrange_mp_frame_nodes
from ...core.io.input_outputs.inputs import get_tree_input_by_index
from ...core.io.utils.io_utils import get_tree_output_index
from ...core.io.arrangements.layer_arrangements import (
    rearrange_layer_frame_nodes,
    rearrange_layer_nodes,
    rearrange_mp_nodes,
)
from ...core.io.arrangements.layer_arrangements import rearrange_parallax_layer_nodes_
from ...core.io.connections.layer_connections import (
    reconnect_layer_nodes,
    reconnect_parallax_layer_nodes__,
    reconnect_mp_nodes,
)
from ...core.io.input_outputs.outputs import get_tree_output_by_index
from ...core.lib.lib_operations import clean_unused_libraries
from ...core.node.check_nodes import check_all_layer_channel_io_and_nodes
from ...core.node.update_nodes import create_delete_iterate_nodes__
from ...core.subtree.get_subtree import get_tree
from ...ui.operators.operators_helper import check_all_channel_ios
from ...utils.constants import BAKED_PARALLAX, PARALLAX, io_suffix, rgba_letters

def update_channel_name(self, context):
    """Update callback when channel name changes.

    Updates all references to the channel name including bake targets, inputs,
    outputs, and layer node trees. Triggers node reconnection and rearrangement.

    Args:
        self: The channel property instance.
        context: The Blender context.

    Returns:
        None
    """
    T = time.time()

    wm = context.window_manager
    group_tree = self.id_data
    mp = group_tree.mp

    if mp.halt_reconnect or mp.halt_update:
        return

    # Update bake target channel name
    for bt in mp.bake_targets:
        for letter in rgba_letters:
            btc = getattr(bt, letter)
            if btc.channel_name != '' and btc.channel_name == self.original_name:
                btc.channel_name  = self.name

    # Update channel's original name
    self.original_name = self.name

    input_index = self.io_index
    output_index = get_tree_output_index(self)

    get_tree_input_by_index(group_tree, input_index).name = self.name
    get_tree_output_by_index(group_tree, output_index).name = self.name

    shift = 1
    if self.enable_alpha:
        get_tree_input_by_index(group_tree, input_index+shift).name = self.name + io_suffix['ALPHA']
        get_tree_output_by_index(group_tree, output_index+shift).name = self.name + io_suffix['ALPHA']
        shift += 1

    if self.type == 'NORMAL' and self.enable_subdiv_setup:
        get_tree_input_by_index(group_tree, input_index+shift).name = self.name + io_suffix['HEIGHT']
        get_tree_output_by_index(group_tree, output_index+shift).name = self.name + io_suffix['HEIGHT']

        shift += 1

        get_tree_input_by_index(group_tree, input_index+shift).name = self.name + io_suffix['MAX_HEIGHT']
        get_tree_output_by_index(group_tree, output_index+shift).name = self.name + io_suffix['MAX_HEIGHT']

        shift += 1

        get_tree_input_by_index(group_tree, input_index+shift).name = self.name + io_suffix['VDISP']
        get_tree_output_by_index(group_tree, output_index+shift).name = self.name + io_suffix['VDISP']

    for layer in mp.layers:
        tree = get_tree(layer)
        check_all_layer_channel_io_and_nodes(layer, tree)
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        rearrange_layer_frame_nodes(layer, tree)
    
    rearrange_mp_frame_nodes(mp)
    reconnect_mp_nodes(group_tree)
    rearrange_mp_nodes(group_tree)

    logger.info('Channel renamed in %s ms!', '{:0.2f}'.format((time.time() - T) * 1000))
    wm.mptimer.time = str(time.time())

def update_enable_smooth_bump(self, context):
    """Update callback when smooth bump enable state changes.

    Args:
        self: The channel property instance.
        context: The Blender context.

    Returns:
        None
    """
    mp = self.id_data.mp

    # Update channel io
    check_all_channel_ios(mp)

    # Clean unused libraries
    clean_unused_libraries()

def update_channel_parallax(self, context):
    """Update callback when channel parallax settings change.

    Args:
        self: The channel property instance.
        context: The Blender context.

    Returns:
        None
    """
    mp = self.id_data.mp

    # Update channel io
    check_all_channel_ios(mp)

def update_parallax_num_of_layers(self, context):
    """Update callback when parallax number of layers changes.

    Creates or deletes iterate nodes in the parallax loop to match the requested
    number of layers. Handles both baked and unbaked parallax modes.

    Args:
        self: The channel property instance.
        context: The Blender context.

    Returns:
        None
    """
    group_tree = self.id_data
    mp = group_tree.mp

    # Baked parallax
    #baked_parallax = group_tree.nodes.get(BAKED_PARALLAX)
    #if baked_parallax:
    #    set_baked_parallax_node(mp, baked_parallax)

    #    rearrange_parallax_layer_nodes(mp, baked_parallax)
    #    reconnect_baked_parallax_layer_nodes(mp, baked_parallax)

    if mp.use_baked:

        num_of_layers = int(self.baked_parallax_num_of_layers)

        baked_parallax = group_tree.nodes.get(BAKED_PARALLAX)
        if baked_parallax:
            loop = baked_parallax.node_tree.nodes.get('_parallax_loop')
            #create_delete_iterate_nodes(loop.node_tree, num_of_layers)
            #create_delete_iterate_nodes_(loop.node_tree, num_of_layers)
            create_delete_iterate_nodes__(loop.node_tree, num_of_layers)

            #rearrange_parallax_layer_nodes(mp, baked_parallax)
            #reconnect_parallax_layer_nodes(group_tree, baked_parallax, mp.baked_uv_name)
            rearrange_parallax_layer_nodes_(mp, baked_parallax)
            reconnect_parallax_layer_nodes__(group_tree, baked_parallax, mp.baked_uv_name)

            baked_parallax.inputs['layer_depth'].default_value = 1.0 / num_of_layers

    else:

        num_of_layers = int(self.parallax_num_of_layers)

        # Parallax
        parallax = group_tree.nodes.get(PARALLAX)
        if parallax:
            loop = parallax.node_tree.nodes.get('_parallax_loop')
            #create_delete_iterate_nodes(loop.node_tree, num_of_layers)
            #create_delete_iterate_nodes_(loop.node_tree, num_of_layers)
            create_delete_iterate_nodes__(loop.node_tree, num_of_layers)

            #rearrange_parallax_layer_nodes(mp, parallax)
            #reconnect_parallax_layer_nodes(group_tree, parallax)
            rearrange_parallax_layer_nodes_(mp, parallax)
            reconnect_parallax_layer_nodes__(group_tree, parallax)

            parallax.inputs['layer_depth'].default_value = 1.0 / num_of_layers

    for uv in mp.uvs:
        parallax_prep = group_tree.nodes.get(uv.parallax_prep)
        if parallax_prep:
            parallax_prep.inputs['layer_depth'].default_value = 1.0 / num_of_layers
