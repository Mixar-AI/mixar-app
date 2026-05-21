# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modifier node management utilities.

This module provides the main public functions for creating, updating,
and deleting shader nodes associated with modifiers.
"""

from ..node.node_utils import remove_node
from .modifier_channel import get_modifier_channel_type
from .modifier_node_handlers import (
    check_invert_modifier,
    check_rgb2i_modifier,
    check_i2rgb_modifier,
    check_override_color_modifier,
    check_color_ramp_modifier,
    check_rgb_curve_modifier,
    check_huesat_modifier,
    check_brightcon_modifier,
    check_multiplier_modifier,
    check_math_modifier,
)


def check_modifier_nodes(m, tree, ref_tree=None):
    """Check and create/update shader nodes for a modifier based on its type and state.

    This is the main function for managing modifier shader nodes. It creates new nodes,
    updates existing ones, or removes them based on the modifier's enable state and type.
    Handles all modifier types including INVERT, RGB_TO_INTENSITY, INTENSITY_TO_RGB,
    OVERRIDE_COLOR, COLOR_RAMP, RGB_CURVE, HUE_SATURATION, BRIGHT_CONTRAST, MULTIPLIER,
    and MATH.

    Args:
        m: The modifier instance to check and update.
        tree: The target ShaderNodeTree where nodes will be created or updated.
        ref_tree (optional): A reference ShaderNodeTree containing existing nodes to
            copy properties from before removal. Defaults to None.

    Returns:
        None
    """
    mp = m.id_data.mp

    # Get channel type and non color status
    channel_type, non_color = get_modifier_channel_type(m, True)

    # Check the nodes based on modifier type
    if m.type == 'INVERT':
        check_invert_modifier(m, tree, ref_tree, channel_type)

    elif m.type == 'RGB_TO_INTENSITY':
        check_rgb2i_modifier(m, tree, ref_tree, non_color)

    elif m.type == 'INTENSITY_TO_RGB':
        check_i2rgb_modifier(m, tree, ref_tree)

    elif m.type == 'OVERRIDE_COLOR':
        check_override_color_modifier(m, tree, ref_tree, channel_type, non_color)

    elif m.type == 'COLOR_RAMP':
        check_color_ramp_modifier(m, tree, ref_tree, non_color, mp)

    elif m.type == 'RGB_CURVE':
        check_rgb_curve_modifier(m, tree, ref_tree)

    elif m.type == 'HUE_SATURATION':
        check_huesat_modifier(m, tree, ref_tree)

    elif m.type == 'BRIGHT_CONTRAST':
        check_brightcon_modifier(m, tree, ref_tree)

    elif m.type == 'MULTIPLIER':
        check_multiplier_modifier(m, tree, ref_tree, channel_type)

    elif m.type == 'MATH':
        check_math_modifier(m, tree, ref_tree, channel_type)


def delete_modifier_nodes(tree, mod):
    """Delete all shader nodes associated with a modifier from the node tree.

    Removes all shader nodes created by the modifier based on its type. This includes
    cleaning up frame nodes and all type-specific nodes (rgb2i, i2rgb, oc, invert,
    color ramp nodes, rgb_curve, huesat, brightcon, multiplier, and math nodes).
    Also removes deprecated nodes if they exist.

    Args:
        tree: The ShaderNodeTree containing the nodes to be removed.
        mod: The modifier instance whose associated nodes should be deleted.

    Returns:
        None
    """
    # Delete the nodes
    remove_node(tree, mod, 'frame')

    if mod.type == 'RGB_TO_INTENSITY':
        remove_node(tree, mod, 'rgb2i')

    elif mod.type == 'INTENSITY_TO_RGB':
        remove_node(tree, mod, 'i2rgb')

    elif mod.type == 'OVERRIDE_COLOR':
        remove_node(tree, mod, 'oc')

    elif mod.type == 'INVERT':
        remove_node(tree, mod, 'invert')

    elif mod.type == 'COLOR_RAMP':
        remove_node(tree, mod, 'color_ramp_linear_start')
        remove_node(tree, mod, 'color_ramp')
        remove_node(tree, mod, 'color_ramp_linear')
        remove_node(tree, mod, 'color_ramp_alpha_multiply')
        remove_node(tree, mod, 'color_ramp_mix_rgb')  # Deprecated
        remove_node(tree, mod, 'color_ramp_mix_alpha')  # Deprecated

    elif mod.type == 'RGB_CURVE':
        remove_node(tree, mod, 'rgb_curve')

    elif mod.type == 'HUE_SATURATION':
        remove_node(tree, mod, 'huesat')

    elif mod.type == 'BRIGHT_CONTRAST':
        remove_node(tree, mod, 'brightcon')

    elif mod.type == 'MULTIPLIER':
        remove_node(tree, mod, 'multiplier')

    elif mod.type == 'MATH':
        remove_node(tree, mod, 'math')
