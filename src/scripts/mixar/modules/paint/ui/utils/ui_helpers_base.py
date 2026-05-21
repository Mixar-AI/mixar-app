# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Base UI helper functions shared across ui_helpers modules."""

from ...utils.common import get_entity_prop_input


def draw_input_prop(layout, entity, prop_name, emboss=None, text=''):
    """Draw a property, using the node group input if available (for real-time updates).

    This function attempts to draw a property from the entity's corresponding node group
    input socket if available, otherwise falls back to drawing the property directly.
    Using node group inputs allows for real-time material updates.

    Args:
        layout: Blender UI layout to draw into.
        entity: Property group or data object containing the property.
        prop_name (str): Name of the property to draw.
        emboss (bool, optional): Whether to draw with embossed style. None uses default. Defaults to None.
        text (str, optional): Label text for the property. Defaults to ''.
    """
    inp = get_entity_prop_input(entity, prop_name)
    if emboss is not None:
        if inp:
            layout.prop(inp, 'default_value', text=text, emboss=emboss)
        else:
            layout.prop(entity, prop_name, text=text, emboss=emboss)
    else:
        if inp:
            layout.prop(inp, 'default_value', text=text)
        else:
            layout.prop(entity, prop_name, text=text)
