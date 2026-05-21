# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...core.modifier.modifier import check_modifiers_trees
from ...utils.common import split_layout


def draw_modifier_properties(
    context, channel_type, nodes, modifier, parent, layout, is_root_ch=False
):
    """Draw UI properties for a modifier in the Blender interface.

    Args:
        context: Blender context object.
        channel_type (str): The type of channel (e.g., "RGB", "VALUE", "NORMAL").
        nodes: Node tree nodes collection.
        modifier: The modifier object to draw properties for.
        parent: The parent object containing the modifier.
        layout: Blender UILayout object to draw the properties into.
        is_root_ch (bool): Whether this is a root channel. Defaults to False.

    Returns:
        None
    """
    if modifier.type == "INVERT":
        row = layout.row(align=True)
        if channel_type == "VALUE":
            row.prop(modifier, "invert_r_enable", text="Value", toggle=True)
            row.prop(modifier, "invert_a_enable", text="Alpha", toggle=True)
        else:
            row.prop(modifier, "invert_r_enable", text="R", toggle=True)
            row.prop(modifier, "invert_g_enable", text="G", toggle=True)
            row.prop(modifier, "invert_b_enable", text="B", toggle=True)
            row.prop(modifier, "invert_a_enable", text="A", toggle=True)

    elif modifier.type == "RGB_TO_INTENSITY":
        col = layout.column(align=True)
        row = col.row()
        row.label(text="Color:")
        rgb2i = nodes.get(modifier.rgb2i)
        if rgb2i:
            row.prop(rgb2i.inputs[3], "default_value", text="")
        else:
            row.prop(modifier, "rgb2i_col", text="")

    elif modifier.type == "OVERRIDE_COLOR":
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

    elif modifier.type == "COLOR_RAMP":
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

    elif modifier.type == "RGB_CURVE":
        rgb_curve = nodes.get(modifier.rgb_curve)
        if rgb_curve:
            rgb_curve.draw_buttons_ext(context, layout)

    elif modifier.type == "HUE_SATURATION":
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

    elif modifier.type == "BRIGHT_CONTRAST":
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

    elif modifier.type == "MULTIPLIER":
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

    elif modifier.type == "MATH":
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


def check_mp_modifier_linear_nodes(mp):
    """Check and update modifier trees for all channels and layers in a MPaint node.

    Args:
        mp: The MPaint data structure containing channels and layers.

    Returns:
        None
    """
    for ch in mp.channels:
        check_modifiers_trees(ch)

    for layer in mp.layers:
        check_modifiers_trees(layer)
        for ch in layer.channels:
            check_modifiers_trees(ch)
        # for mask in layer.masks:
        #    check_modifiers_trees(mask)
