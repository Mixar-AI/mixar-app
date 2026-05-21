# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel inputs/outputs setup for MPaint materials.

This module handles the creation and management of all input/output sockets
for channels, including alpha, displacement, and vector displacement sockets.
"""

from ...utils.constants import (
    LAYER_ALPHA_VIEWER,
    LAYER_VIEWER,
    channel_socket_input_bl_idnames,
    channel_socket_output_bl_idnames,
    io_suffix,
)
from ..io.input_outputs.inputs import create_input, get_tree_inputs, remove_tree_input
from ..io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ..io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ..io.input_outputs.outputs import create_output, get_tree_outputs, remove_tree_output
from ..node.check_nodes import check_all_layer_channel_io_and_nodes, check_uv_nodes
from ..node.create_nodes import check_new_node
from ..node.node_utils import get_active_mpaint_node, remove_node
from .normal_processing import check_start_end_root_ch_nodes


def _create_channel_input_output(group_tree, ch, valid_inputs, valid_outputs,
                                  input_index, output_index, mp_node=None):
    """Create input and output sockets for a channel.

    Args:
        group_tree: The node group tree.
        ch: The channel object.
        valid_inputs: List to track valid inputs.
        valid_outputs: List to track valid outputs.
        input_index: Current input index.
        output_index: Current output index.
        mp_node: Optional MPaint node reference.

    Returns:
        tuple: Updated (input_index, output_index).
    """
    if ch.type == "VALUE":
        create_input(
            group_tree,
            ch.name,
            channel_socket_input_bl_idnames[ch.type],
            valid_inputs,
            input_index,
            min_value=0.0,
            max_value=1.0,
        )
    elif ch.type == "RGB":
        create_input(
            group_tree,
            ch.name,
            channel_socket_input_bl_idnames[ch.type],
            valid_inputs,
            input_index,
            default_value=(1, 1, 1, 1),
        )
    elif ch.type == "NORMAL":
        # Use 999 as normal z value so it will fallback to use geometry normal at checking process
        create_input(
            group_tree,
            ch.name,
            channel_socket_input_bl_idnames[ch.type],
            valid_inputs,
            input_index,
            default_value=(999, 999, 999),
            hide_value=True,
            node=mp_node,
        )

    create_output(
        group_tree,
        ch.name,
        channel_socket_output_bl_idnames[ch.type],
        valid_outputs,
        output_index,
    )

    if ch.io_index != input_index:
        ch.io_index = input_index

    return input_index + 1, output_index + 1


def _setup_alpha_io(group_tree, ch, valid_inputs, valid_outputs,
                    input_index, output_index):
    """Setup alpha input/output sockets for a channel.

    Args:
        group_tree: The node group tree.
        ch: The channel object.
        valid_inputs: List to track valid inputs.
        valid_outputs: List to track valid outputs.
        input_index: Current input index.
        output_index: Current output index.

    Returns:
        tuple: Updated (input_index, output_index).
    """
    if not ch.enable_alpha:
        if ch.backface_mode == "BOTH":
            remove_node(group_tree, ch, "end_backface")
        return input_index, output_index

    name = ch.name + io_suffix["ALPHA"]

    create_input(
        group_tree,
        name,
        "NodeSocketFloatFactor",
        valid_inputs,
        input_index,
        min_value=0.0,
        max_value=1.0,
        default_value=0.0,
    )

    create_output(
        group_tree, name, "NodeSocketFloat", valid_outputs, output_index
    )

    input_index += 1
    output_index += 1

    # Backface mode
    if ch.backface_mode != "BOTH":
        end_backface = check_new_node(
            group_tree, ch, "end_backface", "ShaderNodeMath", "Backface"
        )
        end_backface.use_clamp = True

        if ch.backface_mode == "FRONT_ONLY":
            end_backface.operation = "SUBTRACT"
        elif ch.backface_mode == "BACK_ONLY":
            end_backface.operation = "MULTIPLY"
    else:
        remove_node(group_tree, ch, "end_backface")

    return input_index, output_index


def _setup_displacement_io(group_tree, ch, group_node, valid_inputs, valid_outputs,
                           input_index, output_index, force_height_io=False):
    """Setup displacement input/output sockets for a normal channel.

    Args:
        group_tree: The node group tree.
        ch: The channel object.
        group_node: The group node.
        valid_inputs: List to track valid inputs.
        valid_outputs: List to track valid outputs.
        input_index: Current input index.
        output_index: Current output index.
        force_height_io: Whether to force creation of height IO sockets.

    Returns:
        tuple: Updated (input_index, output_index).
    """
    if ch.type != "NORMAL" or not (ch.enable_subdiv_setup or force_height_io):
        return input_index, output_index

    # Height socket
    name = ch.name + io_suffix["HEIGHT"]
    height_default_value = 0.0
    create_input(
        group_tree,
        name,
        "NodeSocketFloatFactor",
        valid_inputs,
        input_index,
        min_value=0.0,
        max_value=1.0,
        default_value=height_default_value,
        hide_value=True,
    )
    if group_node and group_node.node_tree == group_tree:
        group_node.inputs[name].default_value = height_default_value
    input_index += 1

    create_output(
        group_tree, name, "NodeSocketFloat", valid_outputs, output_index
    )
    output_index += 1

    # Max height socket
    name = ch.name + io_suffix["MAX_HEIGHT"]
    if create_input(
        group_tree,
        name,
        "NodeSocketFloat",
        valid_inputs,
        input_index,
        default_value=0.1,
    ):
        # Set node default value
        if group_node and group_node.node_tree == group_tree:
            group_node.inputs[name].default_value = ch.ori_max_height_value
    input_index += 1

    create_output(
        group_tree, name, "NodeSocketFloat", valid_outputs, output_index
    )
    output_index += 1

    # Vector displacement socket
    name = ch.name + io_suffix["VDISP"]
    create_input(
        group_tree,
        name,
        "NodeSocketVector",
        valid_inputs,
        input_index,
        default_value=(0, 0, 0),
        hide_value=True,
    )
    input_index += 1

    create_output(
        group_tree, name, "NodeSocketVector", valid_outputs, output_index
    )
    output_index += 1

    return input_index, output_index


def _setup_layer_preview_outputs(group_tree, valid_outputs, output_index, mp):
    """Setup layer preview outputs if preview mode is enabled.

    Args:
        group_tree: The node group tree.
        valid_outputs: List to track valid outputs.
        output_index: Current output index.
        mp: The MPaint material data object.

    Returns:
        int: Updated output_index.
    """
    if not mp.layer_preview_mode:
        return output_index

    create_output(
        group_tree, LAYER_VIEWER, "NodeSocketColor", valid_outputs, output_index
    )
    output_index += 1

    create_output(
        group_tree,
        LAYER_ALPHA_VIEWER,
        "NodeSocketColor",
        valid_outputs,
        output_index,
    )
    output_index += 1

    return output_index


def _cleanup_invalid_ios(group_tree, mp, group_node, valid_inputs, valid_outputs):
    """Remove invalid input/output sockets and remember default values.

    Args:
        group_tree: The node group tree.
        mp: The MPaint material data object.
        group_node: The group node.
        valid_inputs: List of valid inputs.
        valid_outputs: List of valid outputs.
    """
    for inp in get_tree_inputs(group_tree):
        if inp not in valid_inputs:
            # Remember default values
            for ch in mp.channels:
                if group_node and inp.name == ch.name + io_suffix["ALPHA"]:
                    node_inp = group_node.inputs.get(inp.name)
                    ch.ori_alpha_value = node_inp.default_value

                if ch.type == "NORMAL":
                    if group_node and inp.name == ch.name + io_suffix["MAX_HEIGHT"]:
                        node_inp = group_node.inputs.get(inp.name)
                        ch.ori_max_height_value = node_inp.default_value

            remove_tree_input(group_tree, inp)

    for outp in get_tree_outputs(group_tree):
        if outp not in valid_outputs:
            remove_tree_output(group_tree, outp)


def _update_layer_ios(mp, specific_layer, remove_props, hard_reset):
    """Update layer input/output nodes.

    Args:
        mp: The MPaint material data object.
        specific_layer: Optional specific layer to process.
        remove_props: Whether to remove unused properties.
        hard_reset: Whether to perform a hard reset of nodes.
    """
    for layer in mp.layers:
        if specific_layer and layer != specific_layer:
            continue
        specific_ch = None
        if mp.layer_preview_mode and mp.active_channel_index < len(layer.channels):
            specific_ch = layer.channels[mp.active_channel_index]
        check_all_layer_channel_io_and_nodes(
            layer,
            specific_ch=specific_ch,
            do_recursive=False,
            remove_props=remove_props,
            hard_reset=hard_reset,
        )


def _reconnect_and_rearrange_nodes(mp, group_tree, specific_layer, reconnect):
    """Reconnect and rearrange layer and MP nodes.

    Args:
        mp: The MPaint material data object.
        group_tree: The node group tree.
        specific_layer: Optional specific layer to process.
        reconnect: Whether to reconnect and rearrange nodes.
    """
    if not reconnect:
        return

    # Rearrange layers
    for layer in mp.layers:
        if specific_layer and layer != specific_layer:
            continue
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

    # Rearrange nodes
    reconnect_mp_nodes(group_tree)
    rearrange_mp_nodes(group_tree)


def check_all_channel_ios(
    mp,
    reconnect=True,
    specific_layer=None,
    remove_props=False,
    force_height_io=False,
    hard_reset=False,
    mp_node=None,
):
    """Check and setup all channel inputs/outputs for the MPaint material.

    This function creates or updates all input/output sockets for channels,
    including alpha, displacement, and vector displacement sockets.

    Args:
        mp: The MPaint material data object.
        reconnect: Whether to reconnect and rearrange nodes after setup. Default: True.
        specific_layer: Optional specific layer to process. Default: None (processes all layers).
        remove_props: Whether to remove unused properties. Default: False.
        force_height_io: Whether to force creation of height IO sockets. Default: False.
        hard_reset: Whether to perform a hard reset of nodes. Default: False.
        mp_node: Optional MPaint node reference. Default: None.

    Returns:
        None
    """
    group_node = get_active_mpaint_node()
    group_tree = mp.id_data

    input_index = 0
    output_index = 0
    valid_inputs = []
    valid_outputs = []

    for ch in mp.channels:
        # Create main channel IO
        input_index, output_index = _create_channel_input_output(
            group_tree, ch, valid_inputs, valid_outputs,
            input_index, output_index, mp_node
        )

        # Setup alpha IO
        input_index, output_index = _setup_alpha_io(
            group_tree, ch, valid_inputs, valid_outputs,
            input_index, output_index
        )

        # Setup displacement IO
        input_index, output_index = _setup_displacement_io(
            group_tree, ch, group_node, valid_inputs, valid_outputs,
            input_index, output_index, force_height_io
        )

    # Check start and end nodes
    check_start_end_root_ch_nodes(group_tree)

    # Setup layer preview outputs
    output_index = _setup_layer_preview_outputs(
        group_tree, valid_outputs, output_index, mp
    )

    # Cleanup invalid IOs
    _cleanup_invalid_ios(group_tree, mp, group_node, valid_inputs, valid_outputs)

    # Check uv maps
    check_uv_nodes(mp)

    # Update layer IO
    _update_layer_ios(mp, specific_layer, remove_props, hard_reset)

    # Reconnect and rearrange nodes
    _reconnect_and_rearrange_nodes(mp, group_tree, specific_layer, reconnect)
