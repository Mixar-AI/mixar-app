# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection normal transition bump - handles transition bump connections.

This module provides functions for handling transition bump connections
in normal channel processing.
"""

from ......config.logging_config import get_logger
from ....utils.common import get_entity_input_name
from ....utils.constants import TREE_START
from ..utils.io_utils import create_link
from ...node.node_utils import get_essential_node

logger = get_logger(__name__)


def connect_transition_bump_distance(tree, nodes, ch, root_ch, height_proc, max_height_calc, ch_bump_distance):
    """Connect transition bump distance to height processor.

    Args:
        tree: The node tree.
        nodes: Node tree nodes.
        ch: The layer channel.
        root_ch: The root channel.
        height_proc: Height processor node.
        max_height_calc: Max height calculator node.
        ch_bump_distance: Channel bump distance socket.
    """
    tb_distance = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(ch, "transition_bump_distance")
    )
    if not tb_distance:
        return

    tb_distance_flipper = nodes.get(ch.tb_distance_flipper)
    if tb_distance_flipper:
        tb_distance = create_link(tree, tb_distance, tb_distance_flipper.inputs[0])[0]

    if ch.normal_map_type in {"BUMP_MAP", "BUMP_NORMAL_MAP"}:
        if 'Transition Max Height' in height_proc.inputs:
            create_link(tree, tb_distance, height_proc.inputs['Transition Max Height'])
    elif ch.normal_map_type == "NORMAL_MAP":
        if 'Bump Height' in height_proc.inputs:
            create_link(tree, tb_distance, height_proc.inputs['Bump Height'])

    if 'Delta' in height_proc.inputs and ch_bump_distance:
        tb_delta_calc = nodes.get(ch.tb_delta_calc)
        if tb_delta_calc:
            create_link(tree, tb_distance, tb_delta_calc.inputs[0])
            create_link(tree, ch_bump_distance, tb_delta_calc.inputs[1])
            create_link(tree, tb_delta_calc.outputs[0], height_proc.inputs['Delta'])

    if max_height_calc and 'Transition Bump Distance' in max_height_calc.inputs:
        create_link(tree, tb_distance, max_height_calc.inputs['Transition Bump Distance'])


def connect_transition_bump_crease(
    tree, ch, root_ch, height_proc, max_height_calc, intensity_multiplier,
    remains, end_chain, end_chain_n, end_chain_s, end_chain_e, end_chain_w,
    end_chain_crease, end_chain_crease_n, end_chain_crease_s, end_chain_crease_e, end_chain_crease_w
):
    """Connect transition bump crease inputs to height processor.

    Args:
        tree: The node tree.
        ch: The layer channel.
        root_ch: The root channel.
        height_proc: Height processor node.
        max_height_calc: Max height calculator node.
        intensity_multiplier: Intensity multiplier node.
        remains: Remaining alpha socket.
        end_chain/end_chain_n/s/e/w: End chain alpha sockets.
        end_chain_crease/end_chain_crease_n/s/e/w: End chain crease alpha sockets.
    """
    tb_crease_factor = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(ch, "transition_bump_crease_factor")
    )
    if tb_crease_factor:
        if 'Crease Factor' in height_proc.inputs:
            create_link(tree, tb_crease_factor, height_proc.inputs['Crease Factor'])
        if max_height_calc and 'Crease Factor' in max_height_calc.inputs:
            create_link(tree, tb_crease_factor, max_height_calc.inputs['Crease Factor'])

    tb_crease_power = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(ch, "transition_bump_crease_power")
    )
    if tb_crease_power and 'Crease Power' in height_proc.inputs:
        create_link(tree, tb_crease_power, height_proc.inputs['Crease Power'])

    if 'Remaining Alpha' in height_proc.inputs:
        create_link(tree, remains, height_proc.inputs['Remaining Alpha'])
    if 'Transition' in height_proc.inputs:
        create_link(tree, end_chain, height_proc.inputs['Transition'])

    if root_ch.enable_smooth_bump and 'Transition n' in height_proc.inputs:
        create_link(tree, end_chain_n, height_proc.inputs['Transition n'])
        create_link(tree, end_chain_s, height_proc.inputs['Transition s'])
        create_link(tree, end_chain_e, height_proc.inputs['Transition e'])
        create_link(tree, end_chain_w, height_proc.inputs['Transition w'])

    if 'Transition Crease' in height_proc.inputs:
        create_link(tree, end_chain_crease, height_proc.inputs['Transition Crease'])

    if root_ch.enable_smooth_bump and 'Transition Crease n' in height_proc.inputs:
        create_link(tree, end_chain_crease_n, height_proc.inputs['Transition Crease n'])
        create_link(tree, end_chain_crease_s, height_proc.inputs['Transition Crease s'])
        create_link(tree, end_chain_crease_e, height_proc.inputs['Transition Crease e'])
        create_link(tree, end_chain_crease_w, height_proc.inputs['Transition Crease w'])

    if intensity_multiplier and 'Edge 1 Alpha' in height_proc.inputs:
        create_link(tree, intensity_multiplier.outputs[0], height_proc.inputs['Edge 1 Alpha'])


def connect_transition_bump_no_crease(
    tree, root_ch, height_proc, write_height, intensity_multiplier,
    end_chain, pure, alpha_n, alpha_s, alpha_e, alpha_w, alpha_before_intensity
):
    """Connect transition bump inputs without crease to height processor.

    Args:
        tree: The node tree.
        root_ch: The root channel.
        height_proc: Height processor node.
        write_height: Whether height writing is enabled.
        intensity_multiplier: Intensity multiplier node.
        end_chain: End chain alpha socket.
        pure: Pure alpha socket.
        alpha_n/s/e/w: Neighbor alpha sockets.
        alpha_before_intensity: Alpha before intensity socket.
    """
    if not write_height and not root_ch.enable_smooth_bump:
        if 'Transition' in height_proc.inputs:
            create_link(tree, end_chain, height_proc.inputs['Transition'])
        if intensity_multiplier and 'Edge 1 Alpha' in height_proc.inputs:
            create_link(tree, intensity_multiplier.outputs[0], height_proc.inputs['Edge 1 Alpha'])
    else:
        if 'Transition' in height_proc.inputs:
            create_link(tree, pure, height_proc.inputs['Transition'])
        if root_ch.enable_smooth_bump and 'Transition n' in height_proc.inputs:
            create_link(tree, alpha_n, height_proc.inputs['Transition n'])
            create_link(tree, alpha_s, height_proc.inputs['Transition s'])
            create_link(tree, alpha_e, height_proc.inputs['Transition e'])
            create_link(tree, alpha_w, height_proc.inputs['Transition w'])
        if 'Edge 1 Alpha' in height_proc.inputs:
            create_link(tree, alpha_before_intensity, height_proc.inputs['Edge 1 Alpha'])


def connect_transition_bump_inverse(tree, nodes, ch, ctx, height_proc):
    """Connect transition bump inverse and intensity multiplier.

    Args:
        tree: The node tree.
        nodes: Node tree nodes.
        ch: The layer channel.
        ctx: The LayerConnectionContext.
        height_proc: Height processor node.
    """
    tb_inverse = nodes.get(ch.tb_inverse) if hasattr(ch, 'tb_inverse') else None
    tb_intensity_multiplier = nodes.get(ch.tb_intensity_multiplier) if hasattr(ch, 'tb_intensity_multiplier') else None

    if tb_intensity_multiplier:
        if 'Edge 2 Alpha' in height_proc.inputs:
            create_link(tree, tb_intensity_multiplier.outputs[0], height_proc.inputs['Edge 2 Alpha'])

        if tb_inverse:
            transition_input = ctx.transition_input if hasattr(ctx, 'transition_input') else None
            if transition_input:
                create_link(tree, transition_input, tb_inverse.inputs[1])
            create_link(tree, tb_inverse.outputs[0], tb_intensity_multiplier.inputs[0])


def connect_standard_alpha(
    tree, root_ch, ch, height_proc, write_height, end_chain,
    alpha_before_intensity, alpha_n, alpha_s, alpha_e, alpha_w
):
    """Connect standard alpha inputs (no transition bump).

    Args:
        tree: The node tree.
        root_ch: The root channel.
        ch: The layer channel.
        height_proc: Height processor node.
        write_height: Whether height writing is enabled.
        end_chain: End chain alpha socket.
        alpha_before_intensity: Alpha before intensity socket.
        alpha_n/s/e/w: Neighbor alpha sockets.
    """
    if 'Alpha' in height_proc.inputs:
        if not write_height and not root_ch.enable_smooth_bump:
            create_link(tree, end_chain, height_proc.inputs['Alpha'])
        else:
            create_link(tree, alpha_before_intensity, height_proc.inputs['Alpha'])

    if root_ch.enable_smooth_bump and 'Alpha n' in height_proc.inputs:
        if alpha_n:
            create_link(tree, alpha_n, height_proc.inputs['Alpha n'])
        if alpha_s:
            create_link(tree, alpha_s, height_proc.inputs['Alpha s'])
        if alpha_e:
            create_link(tree, alpha_e, height_proc.inputs['Alpha e'])
        if alpha_w:
            create_link(tree, alpha_w, height_proc.inputs['Alpha w'])

    if ch.normal_map_type == 'NORMAL_MAP' and 'Transition' in height_proc.inputs:
        if not write_height and not root_ch.enable_smooth_bump:
            create_link(tree, end_chain, height_proc.inputs['Transition'])
        else:
            create_link(tree, alpha_before_intensity, height_proc.inputs['Transition'])

    if root_ch.enable_smooth_bump and 'Transition n' in height_proc.inputs:
        create_link(tree, alpha_n, height_proc.inputs['Transition n'])
        create_link(tree, alpha_s, height_proc.inputs['Transition s'])
        create_link(tree, alpha_e, height_proc.inputs['Transition e'])
        create_link(tree, alpha_w, height_proc.inputs['Transition w'])


def process_transition_bump_connections(
    ctx, ch, root_ch, height_proc, max_height_calc, ch_bump_distance,
    write_height, intensity_multiplier, alpha,
    alpha_n, alpha_s, alpha_e, alpha_w
):
    """Process all transition bump related connections.

    This is the main entry point for transition bump processing.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        height_proc: Height processor node.
        max_height_calc: Max height calculator node.
        ch_bump_distance: Channel bump distance socket.
        write_height: Whether height writing is enabled.
        intensity_multiplier: Intensity multiplier node.
        alpha: Current alpha value.
        alpha_n/s/e/w: Neighbor alpha sockets.
    """
    from ....utils.constants import ONE_VALUE

    tree = ctx.tree
    nodes = tree.nodes

    # Get transition bump context variables
    alpha_after_mod = ctx.end_chain if hasattr(ctx, 'end_chain') else alpha
    trans_bump_ch = ctx.trans_bump_ch if hasattr(ctx, 'trans_bump_ch') else None
    trans_bump_crease = (
        trans_bump_ch and trans_bump_ch.transition_bump_crease
        and not trans_bump_ch.transition_bump_flip
    ) if trans_bump_ch else False

    # Get end chain variables
    end_chain = ctx.end_chain if hasattr(ctx, 'end_chain') else alpha
    end_chain_n = ctx.end_chain_n if hasattr(ctx, 'end_chain_n') else alpha_n
    end_chain_s = ctx.end_chain_s if hasattr(ctx, 'end_chain_s') else alpha_s
    end_chain_e = ctx.end_chain_e if hasattr(ctx, 'end_chain_e') else alpha_e
    end_chain_w = ctx.end_chain_w if hasattr(ctx, 'end_chain_w') else alpha_w
    end_chain_crease = ctx.end_chain_crease if hasattr(ctx, 'end_chain_crease') else alpha
    end_chain_crease_n = ctx.end_chain_crease_n if hasattr(ctx, 'end_chain_crease_n') else alpha_n
    end_chain_crease_s = ctx.end_chain_crease_s if hasattr(ctx, 'end_chain_crease_s') else alpha_s
    end_chain_crease_e = ctx.end_chain_crease_e if hasattr(ctx, 'end_chain_crease_e') else alpha_e
    end_chain_crease_w = ctx.end_chain_crease_w if hasattr(ctx, 'end_chain_crease_w') else alpha_w
    pure = alpha_after_mod
    remains = get_essential_node(tree, ONE_VALUE)[0]
    alpha_before_intensity = ctx.transition_input if hasattr(ctx, 'transition_input') and ctx.transition_input else alpha

    if ch.enable_transition_bump and ch.enable:
        # Connect transition bump distance
        connect_transition_bump_distance(
            tree, nodes, ch, root_ch, height_proc, max_height_calc, ch_bump_distance
        )

        if trans_bump_crease:
            connect_transition_bump_crease(
                tree, ch, root_ch, height_proc, max_height_calc, intensity_multiplier,
                remains, end_chain, end_chain_n, end_chain_s, end_chain_e, end_chain_w,
                end_chain_crease, end_chain_crease_n, end_chain_crease_s,
                end_chain_crease_e, end_chain_crease_w
            )
        else:
            connect_transition_bump_no_crease(
                tree, root_ch, height_proc, write_height, intensity_multiplier,
                end_chain, pure, alpha_n, alpha_s, alpha_e, alpha_w, alpha_before_intensity
            )

        # Connect inverse and intensity multiplier
        connect_transition_bump_inverse(tree, nodes, ch, ctx, height_proc)
    else:
        # No transition bump - standard alpha connections
        connect_standard_alpha(
            tree, root_ch, ch, height_proc, write_height, end_chain,
            alpha_before_intensity, alpha_n, alpha_s, alpha_e, alpha_w
        )
