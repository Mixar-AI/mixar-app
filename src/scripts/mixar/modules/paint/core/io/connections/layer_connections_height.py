# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection height processing.

This module provides functions for handling height processor input connections
and height blend node connections in normal channel processing.
"""

from ......config.logging_config import get_logger
from ....utils.common import get_mix_color_indices
from ....utils.constants import ONE_VALUE, TREE_START, TREE_END, io_suffix
from ..utils.io_utils import create_link, break_input_link
from ...node.node_utils import get_essential_node

logger = get_logger(__name__)


def _get_layer_normal_channel(layer, root_ch):
    """Get the layer's channel matching the root_ch.

    Args:
        layer: The layer object.
        root_ch: The root channel to match.

    Returns:
        The layer channel if found, None otherwise.
    """
    mp = layer.id_data.mp
    for i, ch in enumerate(layer.channels):
        if mp.channels[i] == root_ch:
            return ch
    return None


def _connect_to_alpha_socket(tree, source, target_node, socket_names):
    """Connect to alpha socket with name fallback logic.

    Tries each socket name in order and connects to the first one found.

    Args:
        tree: The node tree.
        source: Source socket to connect from.
        target_node: Target node containing the input sockets.
        socket_names: List of socket names to try in order.

    Returns:
        bool: True if connection was made, False otherwise.
    """
    for name in socket_names:
        if name in target_node.inputs:
            create_link(tree, source, target_node.inputs[name])
            return True
    return False


def _connect_through_rgb_to_bw(tree, ch, rgb, height_proc_input):
    """Connect RGB through RGB to BW node if available, otherwise connect directly.

    Args:
        tree: The node tree.
        ch: The layer channel (may have height_rgb_to_bw node).
        rgb: RGB source socket.
        height_proc_input: Height processor input socket.

    Returns:
        bool: True if connected through RGB to BW, False if direct connection.
    """
    # Check if we have an RGB to BW node for luminance extraction
    rgb_to_bw = tree.nodes.get(getattr(ch, 'height_rgb_to_bw', ''))
    if rgb_to_bw and 'Color' in rgb_to_bw.inputs and len(rgb_to_bw.outputs) > 0:
        # Connect RGB -> RGB to BW -> height_proc Value
        create_link(tree, rgb, rgb_to_bw.inputs['Color'])
        create_link(tree, rgb_to_bw.outputs[0], height_proc_input)
        logger.debug(f"  Connected rgb -> RGB to BW -> height_proc.inputs['Value']")
        return True
    else:
        # Fallback to direct connection
        create_link(tree, rgb, height_proc_input)
        logger.debug(f"  Connected rgb -> height_proc.inputs['Value'] (direct)")
        return False


def connect_height_proc_value_inputs(
    tree, layer, height_proc, root_ch, rgb,
    rgb_n, rgb_s, rgb_e, rgb_w
):
    """Connect value inputs to height processor.

    Args:
        tree: The node tree.
        layer: The layer object.
        height_proc: Height processor node.
        root_ch: The root channel.
        rgb: Current RGB value.
        rgb_n/s/e/w: Neighbor RGB values.
    """
    if 'Value' in height_proc.inputs:
        if layer.type == 'BACKGROUND':
            create_link(tree, get_essential_node(tree, ONE_VALUE)[0], height_proc.inputs['Value'])
        elif layer.type == 'IMAGE':
            # For IMAGE layers, use RGB to BW conversion for proper luminance-based height values
            ch = _get_layer_normal_channel(layer, root_ch)
            _connect_through_rgb_to_bw(tree, ch, rgb, height_proc.inputs['Value'])
        else:
            create_link(tree, rgb, height_proc.inputs['Value'])
            logger.debug(f"  Connected rgb -> height_proc.inputs['Value']")

    # Connect neighbor values for smooth bump
    if root_ch.enable_smooth_bump and 'Value n' in height_proc.inputs:
        if layer.type == 'BACKGROUND':
            one_value = get_essential_node(tree, ONE_VALUE)[0]
            create_link(tree, one_value, height_proc.inputs['Value n'])
            create_link(tree, one_value, height_proc.inputs['Value s'])
            create_link(tree, one_value, height_proc.inputs['Value e'])
            create_link(tree, one_value, height_proc.inputs['Value w'])
        elif layer.type == 'IMAGE':
            # For IMAGE layers, use RGB to BW for proper luminance extraction
            ch = _get_layer_normal_channel(layer, root_ch)
            if rgb_n:
                _connect_through_rgb_to_bw(tree, ch, rgb_n, height_proc.inputs['Value n'])
            if rgb_s:
                _connect_through_rgb_to_bw(tree, ch, rgb_s, height_proc.inputs['Value s'])
            if rgb_e:
                _connect_through_rgb_to_bw(tree, ch, rgb_e, height_proc.inputs['Value e'])
            if rgb_w:
                _connect_through_rgb_to_bw(tree, ch, rgb_w, height_proc.inputs['Value w'])
        else:
            if rgb_n:
                create_link(tree, rgb_n, height_proc.inputs['Value n'])
            if rgb_s:
                create_link(tree, rgb_s, height_proc.inputs['Value s'])
            if rgb_e:
                create_link(tree, rgb_e, height_proc.inputs['Value e'])
            if rgb_w:
                create_link(tree, rgb_w, height_proc.inputs['Value w'])


def connect_height_proc_parameters(tree, height_proc, ch_bump_distance, ch_intensity, ch_bump_midlevel=None):
    """Connect parameter inputs to height processor.

    Args:
        tree: The node tree.
        height_proc: Height processor node.
        ch_bump_distance: Channel bump distance socket.
        ch_intensity: Channel intensity socket.
        ch_bump_midlevel: Channel bump midlevel socket.
    """
    # Connect bump distance (height range)
    if ch_bump_distance and 'Value Max Height' in height_proc.inputs:
        create_link(tree, ch_bump_distance, height_proc.inputs['Value Max Height'])
        logger.debug(f"  Connected ch_bump_distance -> height_proc.inputs['Value Max Height']")

    # Connect intensity if available
    if ch_intensity and 'Intensity' in height_proc.inputs:
        create_link(tree, ch_intensity, height_proc.inputs['Intensity'])

    # Connect bump midlevel
    if ch_bump_midlevel and 'Midlevel' in height_proc.inputs:
        create_link(tree, ch_bump_midlevel, height_proc.inputs['Midlevel'])
        logger.debug(f"  Connected ch_bump_midlevel -> height_proc.inputs['Midlevel']")


def get_height_alpha_output(height_proc, write_height, root_ch, alpha):
    """Get the appropriate height alpha output from height processor for Height Blend.

    This returns the alpha for Height Blend Factor connections.
    When write_height is True, uses 'Normal Alpha' output from height_proc.

    Args:
        height_proc: Height processor node.
        write_height: Whether height writing is enabled.
        root_ch: The root channel.
        alpha: Default alpha value.

    Returns:
        The height alpha output socket for Height Blend.
    """
    height_alpha = alpha

    if height_proc:
        if write_height:
            # When write_height is True, prioritize 'Normal Alpha' output
            if 'Normal Alpha' in height_proc.outputs:
                height_alpha = height_proc.outputs['Normal Alpha']
            elif 'Combined Alpha' in height_proc.outputs:
                height_alpha = height_proc.outputs['Combined Alpha']
            elif 'Alpha' in height_proc.outputs:
                height_alpha = height_proc.outputs['Alpha']
        else:
            # When write_height is False
            if 'Filtered Alpha' in height_proc.outputs and not root_ch.enable_smooth_bump:
                height_alpha = height_proc.outputs['Filtered Alpha']
            elif 'Combined Alpha' in height_proc.outputs:
                height_alpha = height_proc.outputs['Combined Alpha']
            elif 'Normal Alpha' in height_proc.outputs:
                height_alpha = height_proc.outputs['Normal Alpha']
            elif 'Alpha' in height_proc.outputs:
                height_alpha = height_proc.outputs['Alpha']

    return height_alpha


def get_blend_alpha_output(height_proc, write_height, root_ch, ch, alpha):
    """Get the appropriate alpha output from height processor for Blend Fac.

    For BUMP_MAP and BUMP_NORMAL_MAP modes (when write_height=OFF), returns
    'Alpha' output for correct Blend Fac / Channel Opacity connections.

    Args:
        height_proc: Height processor node.
        write_height: Whether height writing is enabled.
        root_ch: The root channel.
        ch: The layer channel.
        alpha: Default alpha value.

    Returns:
        The alpha output socket for Blend Fac.
    """
    blend_alpha = alpha

    if height_proc and not write_height:
        normal_map_type = getattr(ch, 'normal_map_type', None)

        if normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
            # For bump-based modes, use 'Alpha' output for Blend Fac
            if 'Alpha' in height_proc.outputs:
                blend_alpha = height_proc.outputs['Alpha']
        else:
            # For other modes, use the same logic as height_alpha
            if 'Filtered Alpha' in height_proc.outputs and not root_ch.enable_smooth_bump:
                blend_alpha = height_proc.outputs['Filtered Alpha']
            elif 'Combined Alpha' in height_proc.outputs:
                blend_alpha = height_proc.outputs['Combined Alpha']
            elif 'Normal Alpha' in height_proc.outputs:
                blend_alpha = height_proc.outputs['Normal Alpha']
            elif 'Alpha' in height_proc.outputs:
                blend_alpha = height_proc.outputs['Alpha']

    return blend_alpha


def connect_height_blend_standard(
    tree, ch, height_proc, height_blend, height_alpha,
    has_parent, prev_height, prev_height_alpha, write_height=True
):
    """Connect height blend for standard (non-smooth bump) mode.

    Args:
        tree: The node tree.
        ch: The layer channel.
        height_proc: Height processor node.
        height_blend: Height blend node.
        height_alpha: Height alpha output.
        has_parent: Whether layer has a parent.
        prev_height: Previous layer height output.
        prev_height_alpha: Previous layer height alpha.
        write_height: Whether height writing is enabled.
    """
    hbcol0, hbcol1, hbout = get_mix_color_indices(height_blend)

    # Connect height_proc output to height_blend
    if 'Height' in height_proc.outputs:
        if height_blend.type == 'GROUP' and 'Height' in height_blend.inputs:
            create_link(tree, height_proc.outputs['Height'], height_blend.inputs['Height'])
        else:
            create_link(tree, height_proc.outputs['Height'], height_blend.inputs[hbcol1])

    if ch.normal_blend_type in {'MIX', 'OVERLAY'}:
        if has_parent:
            # OVERLAY without write_height disconnects prev_height (ucupaint pattern)
            if not write_height and ch.normal_blend_type == 'OVERLAY':
                if height_blend.type == 'GROUP' and 'Prev Height' in height_blend.inputs:
                    break_input_link(tree, height_blend.inputs['Prev Height'])
                elif len(height_blend.inputs) > 0:
                    break_input_link(tree, height_blend.inputs[0])
            elif prev_height and height_blend.type == 'GROUP':
                if 'Prev Height' in height_blend.inputs:
                    create_link(tree, prev_height, height_blend.inputs['Prev Height'])
                elif len(height_blend.inputs) > 0:
                    create_link(tree, prev_height, height_blend.inputs[0])
            elif prev_height:
                create_link(tree, prev_height, height_blend.inputs[hbcol0])

            # Connect prev_height_alpha (from Group Input's "Normal Height Alpha") to "Alpha1"
            if prev_height_alpha:
                if height_blend.type == 'GROUP':
                    _connect_to_alpha_socket(
                        tree, prev_height_alpha, height_blend,
                        ['Alpha1', 'Alpha 1', 'Prev Alpha']
                    )
                elif len(height_blend.inputs) > 1:
                    create_link(tree, prev_height_alpha, height_blend.inputs[1])

            # Connect current height alpha (from Height Process's "Normal Alpha") to "Alpha2"
            if height_alpha:
                if height_blend.type == 'GROUP':
                    _connect_to_alpha_socket(
                        tree, height_alpha, height_blend,
                        ['Alpha2', 'Alpha 2', 'Alpha']
                    )
                elif len(height_blend.inputs) > 3:
                    create_link(tree, height_alpha, height_blend.inputs[3])
        else:
            # No parent - simpler blend
            # OVERLAY without write_height disconnects prev_height (ucupaint pattern)
            if not write_height and ch.normal_blend_type == 'OVERLAY':
                break_input_link(tree, height_blend.inputs[hbcol0])
            elif prev_height:
                if height_blend.type == 'GROUP' and 'Prev Height' in height_blend.inputs:
                    create_link(tree, prev_height, height_blend.inputs['Prev Height'])
                else:
                    create_link(tree, prev_height, height_blend.inputs[hbcol0])

            # Connect blend factor (height alpha)
            if height_alpha:
                create_link(tree, height_alpha, height_blend.inputs[0])
    else:
        # COMPARE blend type
        if prev_height:
            if height_blend.type == 'GROUP' and 'Prev Height' in height_blend.inputs:
                create_link(tree, prev_height, height_blend.inputs['Prev Height'])
            else:
                create_link(tree, prev_height, height_blend.inputs[hbcol0])

        # Connect current height alpha to "Alpha2"
        if height_alpha and height_blend.type == 'GROUP':
            _connect_to_alpha_socket(
                tree, height_alpha, height_blend,
                ['Alpha2', 'Alpha 2', 'Alpha']
            )

        # Connect prev_height_alpha to "Alpha1"
        if prev_height_alpha and height_blend.type == 'GROUP':
            _connect_to_alpha_socket(
                tree, prev_height_alpha, height_blend,
                ['Alpha1', 'Alpha 1', 'Prev Alpha']
            )


def connect_height_blend_smooth_bump(
    tree, ch, height_proc, height_blend, height_alpha,
    prev_height, prev_height_alpha,
    prev_height_n, prev_height_s, prev_height_e, prev_height_w,
    write_height=True
):
    """Connect height blend for smooth bump mode.

    Args:
        tree: The node tree.
        ch: The layer channel.
        height_proc: Height processor node.
        height_blend: Height blend node.
        height_alpha: Height alpha output.
        prev_height: Previous layer height output.
        prev_height_alpha: Previous layer height alpha.
        prev_height_n/s/e/w: Previous height neighbor outputs.
        write_height: Whether height writing is enabled.
    """
    hbcol0, hbcol1, hbout = get_mix_color_indices(height_blend)

    # Connect height_proc output to height_blend
    if 'Height' in height_proc.outputs:
        if height_blend.type == 'GROUP' and 'Height' in height_blend.inputs:
            create_link(tree, height_proc.outputs['Height'], height_blend.inputs['Height'])
        else:
            create_link(tree, height_proc.outputs['Height'], height_blend.inputs[hbcol1])

    # OVERLAY without write_height disconnects all prev_heights (ucupaint pattern)
    if not write_height and ch.normal_blend_type == 'OVERLAY':
        if 'Prev Height' in height_blend.inputs:
            break_input_link(tree, height_blend.inputs['Prev Height'])
        if 'Prev Height N' in height_blend.inputs:
            break_input_link(tree, height_blend.inputs['Prev Height N'])
        if 'Prev Height S' in height_blend.inputs:
            break_input_link(tree, height_blend.inputs['Prev Height S'])
        if 'Prev Height E' in height_blend.inputs:
            break_input_link(tree, height_blend.inputs['Prev Height E'])
        if 'Prev Height W' in height_blend.inputs:
            break_input_link(tree, height_blend.inputs['Prev Height W'])
    else:
        # Connect prev heights normally
        if prev_height and 'Prev Height' in height_blend.inputs:
            create_link(tree, prev_height, height_blend.inputs['Prev Height'])
        if prev_height_n and 'Prev Height N' in height_blend.inputs:
            create_link(tree, prev_height_n, height_blend.inputs['Prev Height N'])
        if prev_height_s and 'Prev Height S' in height_blend.inputs:
            create_link(tree, prev_height_s, height_blend.inputs['Prev Height S'])
        if prev_height_e and 'Prev Height E' in height_blend.inputs:
            create_link(tree, prev_height_e, height_blend.inputs['Prev Height E'])
        if prev_height_w and 'Prev Height W' in height_blend.inputs:
            create_link(tree, prev_height_w, height_blend.inputs['Prev Height W'])

    # Connect alphas using helper function with socket name fallbacks
    # Alpha2: current height alpha from Height Process's "Normal Alpha"
    if height_alpha:
        _connect_to_alpha_socket(
            tree, height_alpha, height_blend,
            ['Alpha2', 'Alpha 2', 'Alpha']
        )
    # Alpha1: prev_height_alpha from Group Input's "Normal Height Alpha"
    if prev_height_alpha:
        _connect_to_alpha_socket(
            tree, prev_height_alpha, height_blend,
            ['Alpha1', 'Alpha 1', 'Prev Alpha']
        )


def connect_smooth_bump_height_outputs(tree, root_ch, height_proc, height_blend):
    """Connect smooth bump height outputs from height_proc to height_blend.

    Args:
        tree: The node tree.
        root_ch: The root channel.
        height_proc: Height processor node.
        height_blend: Height blend node.
    """
    if not root_ch.enable_smooth_bump:
        return

    if 'Height n' in height_proc.outputs and 'Height N' in height_blend.inputs:
        create_link(tree, height_proc.outputs['Height n'], height_blend.inputs['Height N'])
        create_link(tree, height_proc.outputs['Height s'], height_blend.inputs['Height S'])
        create_link(tree, height_proc.outputs['Height e'], height_blend.inputs['Height E'])
        create_link(tree, height_proc.outputs['Height w'], height_blend.inputs['Height W'])
    elif 'Height n' in height_proc.outputs and 'Height n' in height_blend.inputs:
        create_link(tree, height_proc.outputs['Height n'], height_blend.inputs['Height n'])
        create_link(tree, height_proc.outputs['Height s'], height_blend.inputs['Height s'])
        create_link(tree, height_proc.outputs['Height e'], height_blend.inputs['Height e'])
        create_link(tree, height_proc.outputs['Height w'], height_blend.inputs['Height w'])


def connect_height_blend_to_normal_proc(tree, root_ch, height_blend, normal_proc):
    """Connect height_blend output to normal_proc input.

    Args:
        tree: The node tree.
        root_ch: The root channel.
        height_blend: Height blend node.
        normal_proc: Normal processor node.
    """
    hbcol0, hbcol1, hbout = get_mix_color_indices(height_blend)

    # Use indexed socket for ShaderNodeMix output, named for GROUP
    if height_blend.type == 'GROUP' and 'Height' in height_blend.outputs:
        create_link(tree, height_blend.outputs['Height'], normal_proc.inputs['Height'])
    else:
        create_link(tree, height_blend.outputs[hbout], normal_proc.inputs['Height'])
    logger.debug(f"  Connected height_blend -> normal_proc.inputs['Height']")

    # Smooth bump height connections to normal_proc
    if root_ch.enable_smooth_bump:
        if 'Height n' in height_blend.outputs and 'Height n' in normal_proc.inputs:
            create_link(tree, height_blend.outputs['Height n'], normal_proc.inputs['Height n'])
            create_link(tree, height_blend.outputs['Height s'], normal_proc.inputs['Height s'])
            create_link(tree, height_blend.outputs['Height e'], normal_proc.inputs['Height e'])
            create_link(tree, height_blend.outputs['Height w'], normal_proc.inputs['Height w'])


def connect_height_proc_to_normal_proc(tree, root_ch, height_proc, normal_proc):
    """Connect height_proc output directly to normal_proc (when no height_blend).

    Args:
        tree: The node tree.
        root_ch: The root channel.
        height_proc: Height processor node.
        normal_proc: Normal processor node.
    """
    if 'Height' in height_proc.outputs:
        create_link(tree, height_proc.outputs['Height'], normal_proc.inputs['Height'])
        logger.debug(f"  Connected height_proc.outputs['Height'] -> normal_proc.inputs['Height'] (no height_blend)")

    if root_ch.enable_smooth_bump:
        if 'Height n' in height_proc.outputs and 'Height n' in normal_proc.inputs:
            create_link(tree, height_proc.outputs['Height n'], normal_proc.inputs['Height n'])
            create_link(tree, height_proc.outputs['Height s'], normal_proc.inputs['Height s'])
            create_link(tree, height_proc.outputs['Height e'], normal_proc.inputs['Height e'])
            create_link(tree, height_proc.outputs['Height w'], normal_proc.inputs['Height w'])


def connect_max_height_calc(
    tree, root_ch, layer, max_height_calc, normal_proc,
    ch_bump_distance, ch_intensity, ch_bump_midlevel
):
    """Connect max_height_calc node inputs and outputs.

    This function connects:
    - Prev Bump Distance from previous layer
    - Bump Distance from channel
    - Intensity from channel
    - Midlevel from channel
    - Output to next layer max height and normal_proc

    Args:
        tree: The node tree.
        root_ch: The root channel.
        layer: The layer object.
        max_height_calc: Max height calculator node.
        normal_proc: Normal processor node.
        ch_bump_distance: Channel bump distance socket.
        ch_intensity: Channel intensity socket.
        ch_bump_midlevel: Channel bump midlevel socket.
    """
    # Get prev/next max height from tree start/end
    prev_max_height = get_essential_node(tree, TREE_START).get(
        root_ch.name + io_suffix['MAX_HEIGHT']
    )
    next_max_height = get_essential_node(tree, TREE_END).get(
        root_ch.name + io_suffix['MAX_HEIGHT']
    )

    if max_height_calc:
        # Connect prev max height
        if prev_max_height and 'Prev Bump Distance' in max_height_calc.inputs:
            create_link(tree, prev_max_height, max_height_calc.inputs['Prev Bump Distance'])

        # Connect output to next max height
        if next_max_height and len(max_height_calc.outputs) > 0:
            create_link(tree, max_height_calc.outputs[0], next_max_height)

        # Connect bump distance
        if ch_bump_distance and 'Bump Distance' in max_height_calc.inputs:
            create_link(tree, ch_bump_distance, max_height_calc.inputs['Bump Distance'])
        elif 'Bump Distance' in max_height_calc.inputs:
            break_input_link(tree, max_height_calc.inputs['Bump Distance'])

        # Connect intensity
        if ch_intensity and 'Intensity' in max_height_calc.inputs:
            create_link(tree, ch_intensity, max_height_calc.inputs['Intensity'])

        # Connect midlevel
        if ch_bump_midlevel and 'Midlevel' in max_height_calc.inputs:
            create_link(tree, ch_bump_midlevel, max_height_calc.inputs['Midlevel'])
            logger.debug(f"  Connected ch_bump_midlevel -> max_height_calc.inputs['Midlevel']")

        # Connect output to normal_proc Max Height input
        if normal_proc and 'Max Height' in normal_proc.inputs and len(max_height_calc.outputs) > 0:
            create_link(tree, max_height_calc.outputs[0], normal_proc.inputs['Max Height'])
    else:
        # No max_height_calc - pass through prev to next (ucupaint pattern)
        if prev_max_height and next_max_height:
            create_link(tree, prev_max_height, next_max_height)
            logger.debug(f"  Pass-through: prev_max_height -> next_max_height")
