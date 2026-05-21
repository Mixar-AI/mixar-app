# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy


def draw_modifier_properties(tree, m, layout):
    """Draw UI properties for a mask modifier based on its type.

    Displays appropriate UI controls for the modifier: color ramp for RAMP type
    modifiers, or curve controls for CURVE type modifiers.

    Args:
        tree: The node tree containing the modifier's nodes.
        m: The mask modifier whose properties to draw.
        layout: Blender UILayout object to draw the properties into.

    Returns:
        None
    """
    if m.type == "RAMP":
        ramp = tree.nodes.get(m.ramp)
        layout.template_color_ramp(ramp, "color_ramp", expand=True)

    elif m.type == "CURVE":
        curve = tree.nodes.get(m.curve)
        curve.draw_buttons_ext(bpy.context, layout)
