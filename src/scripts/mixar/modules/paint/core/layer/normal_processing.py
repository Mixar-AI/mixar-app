# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Normal and bump processing node setup for channels.

This module handles the creation and configuration of start/end processing nodes
for root channels, including gamma correction, linear blending, clamping, and
normal/bump/displacement processing.
"""

import re

from ...utils.blender_commons import get_user_preferences
from ...utils.common import get_action_and_driver_fcurves, set_mix_clamp
from ...utils.constants import GAMMA
from ..lib.lib import (
    BUMP_PROCESS,
    BUMP_PROCESS_SUBDIV_ON,
    CHECK_INPUT_NORMAL,
    CHECK_INPUT_NORMAL_GEOMETRY,
    ENGINE_FILTER,
    FINE_BUMP_PROCESS,
    FINE_BUMP_PROCESS_START_BUMP,
    FINE_BUMP_PROCESS_START_BUMP_SUBDIV_ON,
    MAX_HEIGHT_TWEAK,
    MAX_HEIGHT_TWEAK_SMOOTH,
    START_BUMP_PROCESS,
)
from ..node.check_nodes import check_new_node
from ..node.create_nodes import new_mix_node, replace_new_node
from ..node.node_utils import is_normal_height_input_connected, remove_node
from .check_layers import (
    any_layers_using_bump_map,
    any_layers_using_channel,
    any_layers_using_disp,
    any_layers_using_vdisp,
)


def _setup_rgb_value_channel_nodes(group_tree, mp, channel):
    """Setup start/end linear and clamp nodes for RGB/VALUE channels.

    Args:
        group_tree: The node group tree to process.
        mp: The MPaint material data object.
        channel: The channel to process.
    """
    # Create start linear
    if (
        not mp.use_linear_blending
        and channel.colorspace != "LINEAR"
        and any_layers_using_channel(channel)
    ):
        if channel.type == "RGB":
            start_linear = check_new_node(
                group_tree,
                channel,
                "start_linear",
                "ShaderNodeGamma",
                "Start Linear",
            )
        else:
            start_linear = check_new_node(
                group_tree,
                channel,
                "start_linear",
                "ShaderNodeMath",
                "Start Linear",
            )
            start_linear.operation = (
                "POWER" if channel.colorspace != "LINEAR" else "MULTIPLY"
            )  # Multiply is probably faster if channel is linear
        start_linear.inputs[1].default_value = (
            1.0 / GAMMA if channel.colorspace != "LINEAR" else 1.0
        )
    else:
        remove_node(group_tree, channel, "start_linear")

    # Create end linear
    if channel.type == "RGB":
        if (
            not mp.use_linear_blending
            and channel.colorspace != "LINEAR"
            and any_layers_using_channel(channel)
        ):
            end_linear = check_new_node(
                group_tree,
                channel,
                "end_linear",
                "ShaderNodeGamma",
                "End Linear",
            )
            end_linear.inputs[1].default_value = GAMMA
        else:
            remove_node(group_tree, channel, "end_linear")

        if channel.use_clamp and any_layers_using_channel(channel):
            clamp = group_tree.nodes.get(channel.clamp)
            if not clamp:
                clamp = new_mix_node(group_tree, channel, "clamp", "Clamp")
                clamp.inputs[0].default_value = 0.0
                clamp.blend_type = "MULTIPLY"  # Multiply is probably faster than Mix
                set_mix_clamp(clamp, True)
        else:
            remove_node(group_tree, channel, "clamp")

    elif channel.type == "VALUE":
        if (
            not mp.use_linear_blending
            and (channel.colorspace != "LINEAR" or channel.use_clamp)
            and any_layers_using_channel(channel)
        ):
            end_linear = check_new_node(
                group_tree,
                channel,
                "end_linear",
                "ShaderNodeMath",
                "End Linear & Clamp",
            )
            end_linear.operation = (
                "POWER" if channel.colorspace != "LINEAR" else "MULTIPLY"
            )  # Multiply is probably faster if channel is linear
            end_linear.use_clamp = channel.use_clamp
            end_linear.inputs[1].default_value = (
                GAMMA if channel.colorspace != "LINEAR" else 1.0
            )
        else:
            remove_node(group_tree, channel, "end_linear")


def _remember_height_tweak_from_node(group_tree, channel):
    """Remember height tweak property from node and rename fcurve datapath.

    Args:
        group_tree: The node group tree to process.
        channel: The channel to process.
    """
    end_max_height_tweak = group_tree.nodes.get(channel.end_max_height_tweak)
    if end_max_height_tweak:
        if "Height Tweak" in end_max_height_tweak.inputs:
            channel.height_tweak = end_max_height_tweak.inputs[
                "Height Tweak"
            ].default_value

        # Rename fcurve datapath
        for fcs in get_action_and_driver_fcurves(group_tree):
            for fc in fcs:
                match = re.match(
                    r'^nodes\["'
                    + channel.end_max_height_tweak
                    + '"\]\.inputs\[(\d+)\]\.default_value$',
                    fc.data_path,
                )
                if match:
                    index = int(match.group(1))
                    if end_max_height_tweak.inputs[index].name == "Height Tweak":
                        fc.data_path = channel.path_from_id() + ".height_tweak"


def _setup_normal_filter_node(group_tree, channel):
    """Setup start normal filter node.

    Args:
        group_tree: The node group tree to process.
        channel: The channel to process.
    """
    if not channel.enable_smooth_bump and channel.enable_subdiv_setup:
        lib_name = CHECK_INPUT_NORMAL_GEOMETRY
    else:
        lib_name = CHECK_INPUT_NORMAL

    replace_new_node(
        group_tree,
        channel,
        "start_normal_filter",
        "ShaderNodeGroup",
        "Start Normal Filter",
        lib_name,
    )


def _setup_start_bump_process(group_tree, channel):
    """Setup start bump process node.

    Args:
        group_tree: The node group tree to process.
        channel: The channel to process.
    """
    if is_normal_height_input_connected(channel):
        replace_new_node(
            group_tree,
            channel,
            "start_bump_process",
            "ShaderNodeGroup",
            "Start Bump Process",
            START_BUMP_PROCESS,
            hard_replace=True,
        )
    else:
        remove_node(group_tree, channel, "start_bump_process")


def _get_bump_process_lib_name(channel):
    """Determine the appropriate bump process library name.

    Args:
        channel: The channel to check.

    Returns:
        str: The library name for bump processing, or empty string if not needed.
    """
    if not (
        (any_layers_using_channel(channel) and any_layers_using_bump_map(channel))
        or is_normal_height_input_connected(channel)
    ):
        return ""

    if channel.enable_smooth_bump:
        if is_normal_height_input_connected(channel):
            if channel.enable_subdiv_setup:
                return FINE_BUMP_PROCESS_START_BUMP_SUBDIV_ON
            else:
                return FINE_BUMP_PROCESS_START_BUMP
        else:
            return FINE_BUMP_PROCESS
    else:
        if channel.enable_subdiv_setup:
            return BUMP_PROCESS_SUBDIV_ON
        else:
            return BUMP_PROCESS


def _setup_height_tweak_node(group_tree, channel, process_lib_name):
    """Setup height tweak node if enabled.

    Args:
        group_tree: The node group tree to process.
        channel: The channel to process.
        process_lib_name: The process library name being used.
    """
    if not process_lib_name:
        remove_node(group_tree, channel, "end_linear")
        remove_node(group_tree, channel, "end_max_height_tweak")
        return

    if channel.enable_height_tweak:
        if channel.enable_smooth_bump:
            lib_name = MAX_HEIGHT_TWEAK_SMOOTH
        else:
            lib_name = MAX_HEIGHT_TWEAK

        end_max_height_tweak = replace_new_node(
            group_tree,
            channel,
            "end_max_height_tweak",
            "ShaderNodeGroup",
            "Max Height Tweak",
            lib_name,
            hard_replace=True,
        )

        # Set height tweak prop to node
        end_max_height_tweak.inputs["Height Tweak"].default_value = channel.height_tweak

        # Rename fcurve datapath
        for fcs in get_action_and_driver_fcurves(group_tree):
            for fc in fcs:
                if fc.data_path == channel.path_from_id() + ".height_tweak":
                    index = [
                        i
                        for i, inp in enumerate(end_max_height_tweak.inputs)
                        if inp.name == "Height Tweak"
                    ][0]
                    fc.data_path = (
                        'nodes["'
                        + end_max_height_tweak.name
                        + '"].inputs['
                        + str(index)
                        + "].default_value"
                    )
    else:
        remove_node(group_tree, channel, "end_max_height_tweak")


def _setup_engine_filter_node(group_tree, mp, channel):
    """Setup engine filter node for subdiv with baked channels.

    Args:
        group_tree: The node group tree to process.
        mp: The MPaint material data object.
        channel: The channel to process.
    """
    if (
        mp.use_baked
        and channel.enable_subdiv_setup
        and (any_layers_using_disp(channel) or any_layers_using_vdisp(channel))
    ):
        lib_name = ENGINE_FILTER
        end_normal_engine_filter = replace_new_node(
            group_tree,
            channel,
            "end_normal_engine_filter",
            "ShaderNodeGroup",
            "End Engine Filter",
            lib_name,
        )
        for inp in end_normal_engine_filter.inputs:
            inp.default_value = (0.5, 0.5, 1.0, 1.0)
    else:
        remove_node(group_tree, channel, "end_normal_engine_filter")


def _remember_smooth_normal_tweak(group_tree, channel, process_lib_name):
    """Remember smooth normal tweak from node when certain conditions are met.

    Args:
        group_tree: The node group tree to process.
        channel: The channel to process.
        process_lib_name: The process library name being used.
    """
    end_linear = group_tree.nodes.get(channel.end_linear)
    if (
        end_linear
        and "Normal Tweak" in end_linear.inputs
        and (
            (not channel.enable_smooth_bump and channel.enable_smooth_normal_tweak)
            or (channel.enable_smooth_bump and not channel.enable_smooth_normal_tweak)
            or (
                channel.enable_smooth_bump
                and channel.enable_smooth_normal_tweak
                and process_lib_name != ""
                and end_linear.node_tree.name != process_lib_name
            )
        )
    ):
        channel.smooth_normal_tweak = end_linear.inputs["Normal Tweak"].default_value

        # Rename fcurve datapath
        for fcs in get_action_and_driver_fcurves(group_tree):
            for fc in fcs:
                match = re.match(
                    r'^nodes\["'
                    + channel.end_linear
                    + '"\]\.inputs\[(\d+)\]\.default_value$',
                    fc.data_path,
                )
                if match:
                    index = int(match.group(1))
                    if end_linear.inputs[index].name == "Normal Tweak":
                        fc.data_path = channel.path_from_id() + ".smooth_normal_tweak"


def _setup_bump_process_node(group_tree, channel, process_lib_name):
    """Setup bump process node with normal tweak handling.

    Args:
        group_tree: The node group tree to process.
        channel: The channel to process.
        process_lib_name: The process library name to use.
    """
    if not process_lib_name:
        return

    end_linear = replace_new_node(
        group_tree,
        channel,
        "end_linear",
        "ShaderNodeGroup",
        "Bump Process",
        process_lib_name,
        hard_replace=True,
    )

    # Smooth normal tweak
    if channel.enable_smooth_bump and channel.enable_smooth_normal_tweak:
        end_linear.inputs["Normal Tweak"].default_value = channel.smooth_normal_tweak

        # Rename fcurve datapath
        for fcs in get_action_and_driver_fcurves(group_tree):
            for fc in fcs:
                if fc.data_path == channel.path_from_id() + ".smooth_normal_tweak":
                    index = [
                        i
                        for i, inp in enumerate(end_linear.inputs)
                        if inp.name == "Normal Tweak"
                    ][0]
                    fc.data_path = (
                        'nodes["'
                        + end_linear.name
                        + '"].inputs['
                        + str(index)
                        + "].default_value"
                    )

    elif "Normal Tweak" in end_linear.inputs:
        # Rename fcurve datapath
        for fcs in get_action_and_driver_fcurves(group_tree):
            for fc in fcs:
                match = re.match(
                    r'^nodes\["'
                    + channel.end_linear
                    + '"\]\.inputs\[(\d+)\]\.default_value$',
                    fc.data_path,
                )
                if match:
                    index = int(match.group(1))
                    if end_linear.inputs[index].name == "Normal Tweak":
                        fc.data_path = channel.path_from_id() + ".smooth_normal_tweak"

        # Set normal tweak value to 1.0 if it's disabled
        end_linear.inputs["Normal Tweak"].default_value = 1.0


def _setup_normal_channel_nodes(group_tree, mp, channel):
    """Setup nodes for NORMAL type channels.

    Args:
        group_tree: The node group tree to process.
        mp: The MPaint material data object.
        channel: The channel to process.
    """
    # Remember height tweak prop from node
    _remember_height_tweak_from_node(group_tree, channel)

    # Setup start normal filter
    _setup_normal_filter_node(group_tree, channel)

    # Setup start bump process
    _setup_start_bump_process(group_tree, channel)

    # Get bump process library name
    process_lib_name = _get_bump_process_lib_name(channel)

    # Setup height tweak node
    _setup_height_tweak_node(group_tree, channel, process_lib_name)

    # Setup engine filter node
    _setup_engine_filter_node(group_tree, mp, channel)

    # Remember smooth normal tweak
    _remember_smooth_normal_tweak(group_tree, channel, process_lib_name)

    # Setup bump process node
    _setup_bump_process_node(group_tree, channel, process_lib_name)


def check_start_end_root_ch_nodes(group_tree, specific_channel=None):
    """Check and setup start/end processing nodes for root channels.

    This function sets up gamma correction, linear blending, clamping, and
    normal/bump/displacement processing nodes for each channel.

    Args:
        group_tree: The node group tree to process.
        specific_channel: Optional specific channel to process. Default: None (processes all channels).

    Returns:
        None
    """
    mp = group_tree.mp
    get_user_preferences()  # Called for side effects

    for channel in mp.channels:
        if specific_channel and channel != specific_channel:
            continue

        if channel.type in {"RGB", "VALUE"}:
            _setup_rgb_value_channel_nodes(group_tree, mp, channel)
        elif channel.type == "NORMAL":
            _setup_normal_channel_nodes(group_tree, mp, channel)
