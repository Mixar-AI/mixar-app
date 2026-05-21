# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modifier node arrangement functions.

This module handles the arrangement of modifier nodes (invert, RGB curves,
hue/saturation, etc.) for layers and channels.
"""

from mathutils import Vector

from ....utils.constants import MOD_TREE_END, MOD_TREE_START
from ...node.loc import check_set_node_loc

# Y-axis offset constants for modifier node positioning
NO_MODIFIER_Y_OFFSET = 200
FINE_BUMP_Y_OFFSET = 300

default_y_offsets = {
    'RGB': 165,
    'VALUE': 220,
    'NORMAL': 155,
}

mod_y_offsets = {
    'INVERT': 330,
    'RGB_TO_INTENSITY': 280,
    'INTENSITY_TO_RGB': 280,
    'OVERRIDE_COLOR': 280,
    'COLOR_RAMP': 315,
    'RGB_CURVE': 390,
    'HUE_SATURATION': 265,
    'BRIGHT_CONTRAST': 220,
    'MULTIPLIER': 350,
    'MATH': 350
}

value_mod_y_offsets = {
    'INVERT': 270,
    'MULTIPLIER': 270,
    'MATH': 270
}


def get_mod_y_offsets(mod, is_value=False):
    """Get the Y-axis offset for a modifier node based on its type.

    Returns different offsets for value modifiers vs regular modifiers to
    ensure proper vertical spacing in the node tree layout.

    Args:
        mod: The modifier object containing a 'type' attribute.
        is_value (bool, optional): Whether this is a value modifier. Defaults to False.

    Returns:
        int: The Y-axis offset in pixels for the modifier type.
    """
    if is_value and mod.type in value_mod_y_offsets:
        return value_mod_y_offsets[mod.type]
    return mod_y_offsets[mod.type]


def arrange_modifier_nodes(tree, parent, loc, is_value=False, return_y_offset=False, use_modifier_1=False):
    """Arrange modifier nodes for a layer or channel.

    Positions all modifier nodes (invert, RGB curves, hue/saturation, etc.)
    horizontally with appropriate spacing based on modifier type.

    Args:
        tree: The node tree containing the modifier nodes.
        parent: The parent object (layer or channel) containing modifiers.
        loc (Vector): The starting location for arranging nodes (modified in place).
        is_value (bool, optional): Whether arranging value modifiers (uses different
            offsets). Defaults to False.
        return_y_offset (bool, optional): If True, returns both location and Y offset.
            Defaults to False.
        use_modifier_1 (bool, optional): If True, uses modifiers_1 instead of modifiers.
            Defaults to False.

    Returns:
        Vector or tuple: Updated location after arranging. If return_y_offset is True,
            returns (location, y_offset) tuple.
    """
    ori_y = loc.y
    offset_y = 0

    if check_set_node_loc(tree, MOD_TREE_START, loc):
        loc.x += 200

    modifiers = parent.modifiers
    if use_modifier_1:
        modifiers = parent.modifiers_1

    # Modifier loops
    for m in reversed(modifiers):

        loc.y = ori_y
        loc.x += 20

        mod_y_offset = get_mod_y_offsets(m, is_value)
        if offset_y < mod_y_offset:
            offset_y = mod_y_offset

        if m.type == 'INVERT':
            if check_set_node_loc(tree, m.invert, loc):
                loc.x += 165.0

        elif m.type == 'RGB_TO_INTENSITY':
            if check_set_node_loc(tree, m.rgb2i, loc):
                loc.x += 165.0

        elif m.type == 'INTENSITY_TO_RGB':
            if check_set_node_loc(tree, m.i2rgb, loc):
                loc.x += 165.0

        elif m.type == 'OVERRIDE_COLOR':
            if check_set_node_loc(tree, m.oc, loc):
                loc.x += 165.0

        elif m.type == 'COLOR_RAMP':

            if check_set_node_loc(tree, m.color_ramp_alpha_multiply, loc):
                loc.x += 165.0

            if check_set_node_loc(tree, m.color_ramp_linear_start, loc):
                loc.x += 165.0

            if check_set_node_loc(tree, m.color_ramp, loc):
                loc.x += 265.0

            if check_set_node_loc(tree, m.color_ramp_linear, loc):
                loc.x += 165.0

            if check_set_node_loc(tree, m.color_ramp_mix_rgb, loc):
                loc.x += 165.0

            if check_set_node_loc(tree, m.color_ramp_mix_alpha, loc):
                loc.x += 165.0

        elif m.type == 'RGB_CURVE':
            if check_set_node_loc(tree, m.rgb_curve, loc):
                loc.x += 260.0

        elif m.type == 'HUE_SATURATION':
            if check_set_node_loc(tree, m.huesat, loc):
                loc.x += 175.0

        elif m.type == 'BRIGHT_CONTRAST':
            if check_set_node_loc(tree, m.brightcon, loc):
                loc.x += 165.0

        elif m.type == 'MULTIPLIER':
            if check_set_node_loc(tree, m.multiplier, loc):
                loc.x += 165.0

        elif m.type == 'MATH':
            if check_set_node_loc(tree, m.math, loc):
                loc.x += 165.0

        loc.y = ori_y
        loc.x += 100

    if check_set_node_loc(tree, MOD_TREE_END, loc):
        loc.x += 200

    if return_y_offset:
        return loc, offset_y
    return loc
