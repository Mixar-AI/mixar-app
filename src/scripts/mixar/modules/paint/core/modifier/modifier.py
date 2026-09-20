# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main modifier module for paint layers.

This module provides the core functionality for creating and managing modifiers
on paint layers and channels. It includes type definitions, UI drawing functions,
and the main entry point for adding new modifiers.

For update callbacks, see modifier_updates.py.
For tree management, see modifier_tree.py.
"""

import re

from ...utils.blender_commons import get_unique_name
from ...utils.common import split_layout
from ..element.update_fcurves import shift_modifier_fcurves_down
from ..subtree.get_subtree import get_mod_tree

# Import from refactored modules for re-export
from .modifier_channel import get_modifier_channel_type
from .modifier_tree import (
    check_modifiers_trees,
    disable_modifiers_tree,
    enable_modifiers_tree,
)
from .modifier_updates import (
    update_affect_alpha,
    update_affect_color,
    update_invert_channel,
    update_math_method,
    update_modifier_enable,
    update_modifier_shortcut,
    update_multiplier_val_input,
    update_oc_col,
    update_use_clamp,
)

modifier_type_items = (
    ("INVERT", "Invert", "Invert input RGB and/or Alpha", "MODIFIER", 0),
    (
        "RGB_TO_INTENSITY",
        "RGB to Alpha",
        "Input RGB will be used as alpha output, Output RGB will be replaced using custom color.",
        "MODIFIER",
        1,
    ),
    (
        "INTENSITY_TO_RGB",
        "Alpha to RGB",
        "Input alpha will be used as RGB output, Output Alpha will use solid value of one.",
        "MODIFIER",
        2,
    ),
    # Deprecated
    (
        "OVERRIDE_COLOR",
        "Override Color",
        "Input RGB will be replaced with custom RGB",
        "MODIFIER",
        3,
    ),
    ("COLOR_RAMP", "Color Ramp", "", "MODIFIER", 4),
    ("RGB_CURVE", "RGB Curve", "", "MODIFIER", 5),
    ("HUE_SATURATION", "Hue Saturation", "", "MODIFIER", 6),
    ("BRIGHT_CONTRAST", "Brightness Contrast", "", "MODIFIER", 7),
    # Deprecated
    ("MULTIPLIER", "Multiplier", "", "MODIFIER", 8),
    ("MATH", "Math", "", "MODIFIER", 9),
)

can_be_expanded = {
    "INVERT",
    "RGB_TO_INTENSITY",
    "OVERRIDE_COLOR",  # Deprecated
    "COLOR_RAMP",
    "RGB_CURVE",
    "HUE_SATURATION",
    "BRIGHT_CONTRAST",
    "MULTIPLIER",  # Deprecated
    "MATH",
}


def add_new_modifier(parent, modifier_type):
    """Create and add a new modifier to a parent (layer or channel).

    Creates a new modifier of the specified type, assigns it a unique name, positions it
    at the top of the modifier stack, and initializes its shader nodes. For COLOR_RAMP
    modifiers, automatically enables both color and alpha affects.

    Args:
        parent: The parent object (layer or channel) to which the modifier will be added.
        modifier_type (str): The type of modifier to create. Must be one of the values
            from modifier_type_items (e.g., 'INVERT', 'RGB_TO_INTENSITY', 'COLOR_RAMP', etc.).

    Returns:
        The newly created modifier instance.
    """
    mp = parent.id_data.mp

    match1 = re.match(
        r"^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$", parent.path_from_id()
    )
    match2 = re.match(r"^mp\.layers\[(\d+)\]$", parent.path_from_id())
    match3 = re.match(r"^mp\.channels\[(\d+)\]$", parent.path_from_id())

    if match1:
        root_ch = mp.channels[int(match1.group(2))]
        channel_type = root_ch.type
    elif match3:
        root_ch = mp.channels[int(match3.group(1))]
        channel_type = root_ch.type
    elif match2:
        channel_type = "RGB"

    tree = get_mod_tree(parent)
    modifiers = parent.modifiers

    # Add new modifier and move it to the top
    m = modifiers.add()

    if channel_type == "VALUE" and modifier_type == "OVERRIDE_COLOR":
        name = "Override Value"
    else:
        name = [mt[1] for mt in modifier_type_items if mt[0] == modifier_type][0]

    m.name = get_unique_name(name, modifiers)
    modifiers.move(len(modifiers) - 1, 0)
    shift_modifier_fcurves_down(parent)
    m = modifiers[0]
    m.type = modifier_type

    # Color ramp modifier has affect_color and affect_alpha enabled by default
    if modifier_type == "COLOR_RAMP":
        ori_halt_update = mp.halt_update
        mp.halt_update = True

        m.affect_color = True
        m.affect_alpha = True

        mp.halt_update = ori_halt_update

    check_modifiers_trees(parent)

    return m


def draw_modifier_properties(
    context, channel_type, nodes, modifier, parent, layout, is_root_ch=False
):
    """Draw the UI properties for a modifier in the Blender interface.

    Renders the appropriate UI elements for the modifier based on its type. Each modifier
    type has different properties and controls that are displayed in the layout.

    Args:
        context: The Blender context containing scene and UI state.
        channel_type (str): The type of channel ('RGB' or 'VALUE') the modifier operates on.
        nodes: The node collection from the shader tree.
        modifier: The modifier instance whose properties will be drawn.
        parent: The parent object (layer or channel) containing the modifier.
        layout: The Blender UI layout object where controls will be drawn.
        is_root_ch (bool, optional): Whether this is a root channel modifier. Defaults to False.

    Returns:
        None
    """
    if modifier.type == "INVERT":
        _draw_invert_properties(layout, modifier, channel_type)

    elif modifier.type == "RGB_TO_INTENSITY":
        _draw_rgb_to_intensity_properties(layout, nodes, modifier)

    elif modifier.type == "OVERRIDE_COLOR":
        _draw_override_color_properties(layout, modifier, channel_type)

    elif modifier.type == "COLOR_RAMP":
        _draw_color_ramp_properties(
            layout, nodes, modifier, parent, channel_type, is_root_ch
        )

    elif modifier.type == "RGB_CURVE":
        _draw_rgb_curve_properties(context, layout, nodes, modifier)

    elif modifier.type == "HUE_SATURATION":
        _draw_hue_saturation_properties(layout, nodes, modifier)

    elif modifier.type == "BRIGHT_CONTRAST":
        _draw_bright_contrast_properties(layout, nodes, modifier)

    elif modifier.type == "MULTIPLIER":
        _draw_multiplier_properties(layout, modifier, channel_type)

    elif modifier.type == "MATH":
        _draw_math_properties(layout, nodes, modifier, channel_type)


def _draw_invert_properties(layout, modifier, channel_type):
    """Draw UI properties for INVERT modifier."""
    row = layout.row(align=True)
    if channel_type == "VALUE":
        row.prop(modifier, "invert_r_enable", text="Value", toggle=True)
        row.prop(modifier, "invert_a_enable", text="Alpha", toggle=True)
    else:
        row.prop(modifier, "invert_r_enable", text="R", toggle=True)
        row.prop(modifier, "invert_g_enable", text="G", toggle=True)
        row.prop(modifier, "invert_b_enable", text="B", toggle=True)
        row.prop(modifier, "invert_a_enable", text="A", toggle=True)


def _draw_rgb_to_intensity_properties(layout, nodes, modifier):
    """Draw UI properties for RGB_TO_INTENSITY modifier."""
    col = layout.column(align=True)
    row = col.row()
    row.label(text="Color:")
    rgb2i = nodes.get(modifier.rgb2i)
    if rgb2i:
        row.prop(rgb2i.inputs[3], "default_value", text="")
    else:
        row.prop(modifier, "rgb2i_col", text="")


def _draw_override_color_properties(layout, modifier, channel_type):
    """Draw UI properties for OVERRIDE_COLOR modifier."""
    col = layout.column(align=True)

    row = col.row()
    if channel_type == "VALUE":
        row.label(text="Value:")
        row.prop(modifier, "oc_val", text="")
    else:
        row.label(text="Color:")
        row.prop(modifier, "oc_col", text="")

        row = col.row()
        row.label(text="Shortcut on layer list:")
        row.prop(modifier, "shortcut", text="")


def _draw_color_ramp_properties(
    layout, nodes, modifier, parent, channel_type, is_root_ch
):
    """Draw UI properties for COLOR_RAMP modifier."""
    col = layout.column()
    color_ramp = nodes.get(modifier.color_ramp)
    if color_ramp:
        ccol = col.column()
        ccol.active = modifier.affect_color or modifier.affect_alpha
        ccol.template_color_ramp(color_ramp, "color_ramp", expand=True)

    if (
        not is_root_ch
        or parent.enable_alpha
        or not modifier.affect_color
        or not modifier.affect_alpha
    ):
        split = split_layout(col, 0.3, align=True)
        split.label(text="Affect:")
        row = split.row(align=True)

        label = "Color" if channel_type != "VALUE" else "Value"
        row.prop(modifier, "affect_color", text=label, toggle=True)
        row.prop(modifier, "affect_alpha", text="Alpha", toggle=True)


def _draw_rgb_curve_properties(context, layout, nodes, modifier):
    """Draw UI properties for RGB_CURVE modifier."""
    rgb_curve = nodes.get(modifier.rgb_curve)
    if rgb_curve:
        rgb_curve.draw_buttons_ext(context, layout)


def _draw_hue_saturation_properties(layout, nodes, modifier):
    """Draw UI properties for HUE_SATURATION modifier."""
    row = layout.row(align=True)
    col = row.column(align=True)
    col.label(text="Hue:")
    col.label(text="Saturation:")
    col.label(text="Value:")

    col = row.column(align=True)
    huesat = nodes.get(modifier.huesat)
    if huesat:
        col.prop(huesat.inputs[0], "default_value", text="")
        col.prop(huesat.inputs[1], "default_value", text="")
        col.prop(huesat.inputs[2], "default_value", text="")
    else:
        col.prop(modifier, "huesat_hue_val", text="")
        col.prop(modifier, "huesat_saturation_val", text="")
        col.prop(modifier, "huesat_value_val", text="")


def _draw_bright_contrast_properties(layout, nodes, modifier):
    """Draw UI properties for BRIGHT_CONTRAST modifier."""
    row = layout.row(align=True)
    col = row.column(align=True)
    col.label(text="Brightness:")
    col.label(text="Contrast:")

    col = row.column(align=True)
    brightcon = nodes.get(modifier.brightcon)
    if brightcon:
        col.prop(brightcon.inputs[1], "default_value", text="")
        col.prop(brightcon.inputs[2], "default_value", text="")
    else:
        col.prop(modifier, "brightness_value", text="")
        col.prop(modifier, "contrast_value", text="")


def _draw_multiplier_properties(layout, modifier, channel_type):
    """Draw UI properties for MULTIPLIER modifier."""
    col = layout.column(align=True)
    row = col.row()
    row.label(text="Clamp:")
    row.prop(modifier, "use_clamp", text="")
    if channel_type == "VALUE":
        col.prop(modifier, "multiplier_r_val", text="Value")
        col.prop(modifier, "multiplier_a_val", text="Alpha")
    else:
        col.prop(modifier, "multiplier_r_val", text="R")
        col.prop(modifier, "multiplier_g_val", text="G")
        col.prop(modifier, "multiplier_b_val", text="B")
        col.separator()
        col.prop(modifier, "multiplier_a_val", text="Alpha")


def _draw_math_properties(layout, nodes, modifier, channel_type):
    """Draw UI properties for MATH modifier."""
    col = layout.column(align=True)
    row = col.row()
    col.prop(modifier, "math_meth")
    row = col.row()
    row.label(text="Clamp:")
    row.prop(modifier, "use_clamp", text="")
    math = nodes.get(modifier.math)
    if channel_type == "VALUE":
        if math:
            col.prop(math.inputs[2], "default_value", text="Value")
        else:
            col.prop(modifier, "math_r_val", text="Value")
    else:
        if math:
            col.prop(math.inputs[2], "default_value", text="R")
            col.prop(math.inputs[3], "default_value", text="G")
            col.prop(math.inputs[4], "default_value", text="B")
        else:
            col.prop(modifier, "math_r_val", text="R")
            col.prop(modifier, "math_g_val", text="G")
            col.prop(modifier, "math_b_val", text="B")
    col.separator()
    row = col.row()
    row.label(text="Affect Alpha:")
    row.prop(modifier, "affect_alpha", text="")
    if modifier.affect_alpha:
        if math:
            if channel_type == "VALUE":
                col.prop(math.inputs[3], "default_value", text="A")
            else:
                col.prop(math.inputs[5], "default_value", text="A")
        else:
            col.prop(modifier, "math_a_val", text="A")


# Re-export all public symbols for backward compatibility
__all__ = [
    # Constants
    "modifier_type_items",
    "can_be_expanded",
    # Core functions
    "add_new_modifier",
    "draw_modifier_properties",
    "get_modifier_channel_type",
    # Tree management (from modifier_tree.py)
    "check_modifiers_trees",
    "enable_modifiers_tree",
    "disable_modifiers_tree",
    # Update callbacks (from modifier_updates.py)
    "update_modifier_enable",
    "update_modifier_shortcut",
    "update_use_clamp",
    "update_affect_color",
    "update_affect_alpha",
    "update_math_method",
    "update_multiplier_val_input",
    "update_oc_col",
    "update_invert_channel",
]
