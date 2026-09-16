# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The editor and Zen drawer are two hosts of the same moodboard canvas."""

import bpy


def is_moodboard_context(context):
    space = getattr(context, "space_data", None)
    if getattr(space, "type", None) == "MIXIE":
        return getattr(space, "mixie_mode", "MOODBOARD") == "MOODBOARD"
    return (
        getattr(space, "type", None) == "VIEW_3D"
        and getattr(getattr(context, "workspace", None), "name", None) == "Zen Mode"
        and getattr(getattr(context, "region", None), "type", None) in {"TOOL_PROPS", "TEMP"}
        and getattr(context.window_manager, "mixar_moodboard_drawer_amount", 0.0) >= 0.98
    )


def redraw_moodboard_canvases():
    """Refresh board changes and job pulses without redrawing the 3D scene."""
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        if window.screen is None:
            continue
        for area in window.screen.areas:
            if area.type == "MIXIE":
                area.tag_redraw()
            elif (
                area.type == "VIEW_3D"
                and window.workspace.name == "Zen Mode"
                and getattr(wm, "mixar_moodboard_drawer_amount", 0.0) > 0.0
            ):
                for region in area.regions:
                    if region.type == "TOOL_PROPS":
                        region.tag_redraw()
