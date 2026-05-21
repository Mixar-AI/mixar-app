# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Channel iteration and end node connection helpers for mp_connections.
"""

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.common import get_mix_color_indices
from ....utils.constants import (
    TREE_START,
    ZERO_VALUE,
    ONE_VALUE,
    GEOMETRY,
    io_suffix,
)
from ...node.node_utils import get_essential_node, is_normal_height_input_connected
from ..utils.io_utils import create_link

# Re-export baked functions for backward compatibility
from .mp_connections_baked import (
    process_baked_channel,
    process_baked_vcol,
    connect_channel_to_tree_end,
)


def initialize_channel_values(tree, ch, nodes):
    """
    Initialize channel values and nodes for processing.

    Parameters:
        tree: The node tree.
        ch: The current channel.
        nodes: The nodes in the tree.

    Returns:
        tuple: (channel_nodes, io_names_dict, channel_values)
    """
    start_linear = nodes.get(ch.start_linear)
    end_linear = nodes.get(ch.end_linear)
    end_normal_engine_filter = nodes.get(ch.end_normal_engine_filter)
    end_backface = nodes.get(ch.end_backface)
    clamp = nodes.get(ch.clamp)
    end_max_height = nodes.get(ch.end_max_height)
    end_max_height_tweak = nodes.get(ch.end_max_height_tweak)
    start_normal_filter = nodes.get(ch.start_normal_filter)
    start_bump_process = nodes.get(ch.start_bump_process)

    channel_nodes = {
        "start_linear": start_linear,
        "end_linear": end_linear,
        "end_normal_engine_filter": end_normal_engine_filter,
        "end_backface": end_backface,
        "clamp": clamp,
        "end_max_height": end_max_height,
        "end_max_height_tweak": end_max_height_tweak,
        "start_normal_filter": start_normal_filter,
        "start_bump_process": start_bump_process,
    }

    io_name = ch.name
    io_alpha_name = ch.name + io_suffix["ALPHA"]
    io_height_name = ch.name + io_suffix["HEIGHT"]
    io_height_n_name = ch.name + io_suffix["HEIGHT_N"]
    io_height_s_name = ch.name + io_suffix["HEIGHT_S"]
    io_height_e_name = ch.name + io_suffix["HEIGHT_E"]
    io_height_w_name = ch.name + io_suffix["HEIGHT_W"]
    io_height_alpha_name = ch.name + io_suffix["HEIGHT"] + io_suffix["ALPHA"]
    io_height_n_alpha_name = ch.name + io_suffix["HEIGHT_N"] + io_suffix["ALPHA"]
    io_height_s_alpha_name = ch.name + io_suffix["HEIGHT_S"] + io_suffix["ALPHA"]
    io_height_e_alpha_name = ch.name + io_suffix["HEIGHT_E"] + io_suffix["ALPHA"]
    io_height_w_alpha_name = ch.name + io_suffix["HEIGHT_W"] + io_suffix["ALPHA"]
    io_max_height_name = ch.name + io_suffix["MAX_HEIGHT"]
    io_vdisp_name = ch.name + io_suffix["VDISP"]

    io_names_dict = {
        "io_name": io_name,
        "io_alpha_name": io_alpha_name,
        "io_height_name": io_height_name,
        "io_height_n_name": io_height_n_name,
        "io_height_s_name": io_height_s_name,
        "io_height_e_name": io_height_e_name,
        "io_height_w_name": io_height_w_name,
        "io_height_alpha_name": io_height_alpha_name,
        "io_height_n_alpha_name": io_height_n_alpha_name,
        "io_height_s_alpha_name": io_height_s_alpha_name,
        "io_height_e_alpha_name": io_height_e_alpha_name,
        "io_height_w_alpha_name": io_height_w_alpha_name,
        "io_max_height_name": io_max_height_name,
        "io_vdisp_name": io_vdisp_name,
    }

    # Initialize channel values
    rgb = get_essential_node(tree, TREE_START)[io_name]
    if ch.enable_alpha:
        alpha = get_essential_node(tree, TREE_START)[io_alpha_name]
    else:
        alpha = get_essential_node(tree, ONE_VALUE)[0]

    channel_values = {
        "rgb": rgb,
        "alpha": alpha,
        "height": None,
        "height_n": None,
        "height_s": None,
        "height_e": None,
        "height_w": None,
        "height_alpha": None,
        "height_n_alpha": None,
        "height_s_alpha": None,
        "height_e_alpha": None,
        "height_w_alpha": None,
        "max_height": None,
        "vdisp": None,
    }

    return channel_nodes, io_names_dict, channel_values


def initialize_normal_channel_values(tree, ch):
    """
    Initialize values specific to normal channels.

    Parameters:
        tree: The node tree.
        ch: The current channel.

    Returns:
        dict: Updated height-related values for normal channels.
    """
    io_height_name = ch.name + io_suffix["HEIGHT"]
    io_max_height_name = ch.name + io_suffix["MAX_HEIGHT"]
    io_vdisp_name = ch.name + io_suffix["VDISP"]

    height_input = get_essential_node(tree, TREE_START).get(io_height_name)
    height = (
        height_input
        if height_input
        else get_essential_node(tree, ZERO_VALUE)[0]
    )

    if is_normal_height_input_connected(ch):
        max_height = get_essential_node(tree, TREE_START)[io_max_height_name]
    else:
        max_height = get_essential_node(tree, ZERO_VALUE)[0]

    vdisp_input = get_essential_node(tree, TREE_START).get(io_vdisp_name)
    vdisp = (
        vdisp_input if vdisp_input else get_essential_node(tree, ZERO_VALUE)[0]
    )

    result = {
        "height": height,
        "max_height": max_height,
        "vdisp": vdisp,
        "height_n": None,
        "height_s": None,
        "height_e": None,
        "height_w": None,
        "height_alpha": None,
        "height_n_alpha": None,
        "height_s_alpha": None,
        "height_e_alpha": None,
        "height_w_alpha": None,
    }

    if ch.enable_smooth_bump:
        result["height_n"] = (
            height_input
            if height_input
            else get_essential_node(tree, ZERO_VALUE)[0]
        )
        result["height_s"] = (
            height_input
            if height_input
            else get_essential_node(tree, ZERO_VALUE)[0]
        )
        result["height_e"] = (
            height_input
            if height_input
            else get_essential_node(tree, ZERO_VALUE)[0]
        )
        result["height_w"] = (
            height_input
            if height_input
            else get_essential_node(tree, ZERO_VALUE)[0]
        )

        if is_normal_height_input_connected(ch):
            result["height_alpha"] = get_essential_node(tree, ZERO_VALUE)[0]
            result["height_n_alpha"] = get_essential_node(tree, ZERO_VALUE)[0]
            result["height_s_alpha"] = get_essential_node(tree, ZERO_VALUE)[0]
            result["height_e_alpha"] = get_essential_node(tree, ZERO_VALUE)[0]
            result["height_w_alpha"] = get_essential_node(tree, ZERO_VALUE)[0]

    return result


def process_start_bump(tree, ch, channel_values, channel_nodes):
    """
    Process start bump node connections.

    Parameters:
        tree: The node tree.
        ch: The current channel.
        channel_values: Current channel values.
        channel_nodes: Channel-related nodes.

    Returns:
        dict: Updated channel values.
    """
    start_bump_process = channel_nodes.get("start_bump_process")
    height = channel_values.get("height")
    max_height = channel_values.get("max_height")

    if start_bump_process and height and max_height:
        height = create_link(tree, height, start_bump_process.inputs["Height"])[0]
        create_link(tree, max_height, start_bump_process.inputs["Max Height"])
        channel_values["height"] = height

    return channel_values


def process_start_linear(tree, ch, channel_values, channel_nodes):
    """
    Process start linear node connections.

    Parameters:
        tree: The node tree.
        ch: The current channel.
        channel_values: Current channel values.
        channel_nodes: Channel-related nodes.

    Returns:
        Updated rgb value.
    """
    start_linear = channel_nodes.get("start_linear")
    start_normal_filter = channel_nodes.get("start_normal_filter")
    rgb = channel_values["rgb"]

    if start_linear:
        rgb = create_link(tree, rgb, start_linear.inputs[0])[0]
    elif start_normal_filter:
        rgb = create_link(tree, rgb, start_normal_filter.inputs[0])[0]

    return rgb


def process_end_linear_normal(tree, ch, channel_values, channel_nodes, uv_maps, tangent, bitangent):
    """
    Process end linear node for normal channels.

    Parameters:
        tree: The node tree.
        ch: The current channel.
        channel_values: Current channel values.
        channel_nodes: Channel-related nodes.
        uv_maps: Dictionary of UV map outputs.
        tangent: Main tangent output.
        bitangent: Main bitangent output.

    Returns:
        tuple: (rgb, normal_no_bump)
    """
    end_linear = channel_nodes.get("end_linear")
    end_max_height_tweak = channel_nodes.get("end_max_height_tweak")
    start_bump_process = channel_nodes.get("start_bump_process")

    rgb = channel_values["rgb"]
    height = channel_values.get("height")
    height_n = channel_values.get("height_n")
    height_s = channel_values.get("height_s")
    height_e = channel_values.get("height_e")
    height_w = channel_values.get("height_w")
    height_alpha = channel_values.get("height_alpha")
    height_n_alpha = channel_values.get("height_n_alpha")
    height_s_alpha = channel_values.get("height_s_alpha")
    height_e_alpha = channel_values.get("height_e_alpha")
    height_w_alpha = channel_values.get("height_w_alpha")
    max_height = channel_values.get("max_height")

    normal_no_bump = rgb

    if "Normal Overlay" in end_linear.inputs:
        rgb = create_link(tree, rgb, end_linear.inputs["Normal Overlay"])[0]
    else:
        rgb = end_linear.outputs[0]

    if "Main UV" in end_linear.inputs and ch.main_uv in uv_maps:
        create_link(tree, uv_maps[ch.main_uv], end_linear.inputs["Main UV"])

    if max_height:
        if end_max_height_tweak and "Max Height" in end_max_height_tweak.inputs:
            max_height = create_link(
                tree, max_height, end_max_height_tweak.inputs["Max Height"]
            )["Max Height"]

        create_link(tree, max_height, end_linear.inputs["Max Height"])

    if end_max_height_tweak:
        if height and "Height" in end_max_height_tweak.inputs:
            height = create_link(
                tree, height, end_max_height_tweak.inputs["Height"]
            )["Height"]

        if height_n and "Height N" in end_max_height_tweak.inputs:
            height_n = create_link(
                tree, height_n, end_max_height_tweak.inputs["Height N"]
            )["Height N"]

        if height_s and "Height S" in end_max_height_tweak.inputs:
            height_s = create_link(
                tree, height_s, end_max_height_tweak.inputs["Height S"]
            )["Height S"]

        if height_e and "Height E" in end_max_height_tweak.inputs:
            height_e = create_link(
                tree, height_e, end_max_height_tweak.inputs["Height E"]
            )["Height E"]

        if height_w and "Height W" in end_max_height_tweak.inputs:
            height_w = create_link(
                tree, height_w, end_max_height_tweak.inputs["Height W"]
            )["Height W"]

    if height and "Height" in end_linear.inputs:
        height = create_link(tree, height, end_linear.inputs["Height"])[1]
    if height_n and "Height N" in end_linear.inputs:
        create_link(tree, height_n, end_linear.inputs["Height N"])
    if height_s and "Height S" in end_linear.inputs:
        create_link(tree, height_s, end_linear.inputs["Height S"])
    if height_e and "Height E" in end_linear.inputs:
        create_link(tree, height_e, end_linear.inputs["Height E"])
    if height_w and "Height W" in end_linear.inputs:
        create_link(tree, height_w, end_linear.inputs["Height W"])

    if height_alpha and "Height Alpha" in end_linear.inputs:
        create_link(tree, height_alpha, end_linear.inputs["Height Alpha"])
    if height_n_alpha and "Height Alpha N" in end_linear.inputs:
        create_link(tree, height_n_alpha, end_linear.inputs["Height Alpha N"])
    if height_s_alpha and "Height Alpha S" in end_linear.inputs:
        create_link(tree, height_s_alpha, end_linear.inputs["Height Alpha S"])
    if height_e_alpha and "Height Alpha E" in end_linear.inputs:
        create_link(tree, height_e_alpha, end_linear.inputs["Height Alpha E"])
    if height_w_alpha and "Height Alpha W" in end_linear.inputs:
        create_link(tree, height_w_alpha, end_linear.inputs["Height Alpha W"])

    if "Start Height" in end_linear.inputs and start_bump_process:
        create_link(
            tree,
            start_bump_process.outputs[0],
            end_linear.inputs["Start Height"],
        )

    if tangent and "Tangent" in end_linear.inputs:
        create_link(tree, tangent, end_linear.inputs["Tangent"])

    if bitangent and "Bitangent" in end_linear.inputs:
        create_link(tree, bitangent, end_linear.inputs["Bitangent"])

    # Update channel_values with possibly modified height
    channel_values["height"] = height

    return rgb, normal_no_bump


def process_clamp_and_backface(tree, ch, rgb, alpha, channel_nodes):
    """
    Process clamp and backface nodes.

    Parameters:
        tree: The node tree.
        ch: The current channel.
        rgb: Current RGB value.
        alpha: Current alpha value.
        channel_nodes: Channel-related nodes.

    Returns:
        tuple: (rgb, alpha)
    """
    clamp = channel_nodes.get("clamp")
    end_backface = channel_nodes.get("end_backface")

    if clamp:
        mixcol0, mixcol1, mixout = get_mix_color_indices(clamp)
        rgb = create_link(tree, rgb, clamp.inputs[mixcol0])[mixout]

    if end_backface:
        alpha = create_link(tree, alpha, end_backface.inputs[0])[0]
        create_link(
            tree,
            get_essential_node(tree, GEOMETRY)["Backfacing"],
            end_backface.inputs[1],
        )

    return rgb, alpha
