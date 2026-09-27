# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Live theme colors shared by Python drawing tools."""

from ..constants import SKETCH_COLOR_RGBA


def sketch_ink_color():
    """Resolve old preferences through the same zero-value fallback as native UI."""
    import bpy

    try:
        color = tuple(bpy.context.preferences.themes[0].user_interface.mixar_sketch_ink)
        if len(color) == 4 and any(color):
            return color
    except (AttributeError, IndexError, TypeError):
        pass
    return SKETCH_COLOR_RGBA


def annotation_color_get(state):
    """A saved brush choice wins; an untouched brush follows the theme."""
    return state.get("annotation_color", sketch_ink_color())


def annotation_color_set(state, value):
    state["annotation_color"] = value
