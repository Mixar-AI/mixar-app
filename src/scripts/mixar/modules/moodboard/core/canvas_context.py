# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The editor and Zen drawer are two hosts of the same moodboard canvas."""

import bpy


MOODBOARD_CONTENT_COLLECTIONS = (
    "mixie_moodboard_images",
    "mixie_moodboard_textboxes",
    # Frames replaced the index-based `mixie_moodboard_groups`, which the
    # load-time migration empties for good. The legacy name stays listed
    # only so a board that has not ticked the migration yet still reads
    # as non-empty.
    "mixie_moodboard_frames",
    "mixie_moodboard_groups",
    "mixie_moodboard_action_nodes",
    "mixie_moodboard_asset_nodes",
    "mixie_moodboard_links",
    "mixie_moodboard_annotations",
)


def has_moodboard_content(context):
    """True when either canvas host should offer Clear Moodboard."""
    scene = getattr(context, "scene", None)
    return any(getattr(scene, name, ()) for name in MOODBOARD_CONTENT_COLLECTIONS)


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


def find_moodboard_canvas_region(context):
    """Return the live moodboard canvas region (Mixie WINDOW or open drawer)."""
    region = getattr(context, "region", None)
    if (
        region is not None
        and getattr(region, "view2d", None) is not None
        and region.type in {"WINDOW", "TOOL_PROPS"}
        and region.width > 1
    ):
        space = getattr(context, "space_data", None)
        if getattr(space, "type", None) == "MIXIE" and region.type == "WINDOW":
            return region
        if (
            getattr(space, "type", None) == "VIEW_3D"
            and region.type == "TOOL_PROPS"
            and float(
                getattr(context.window_manager, "mixar_moodboard_drawer_amount", 0.0)
            )
            >= 0.98
        ):
            return region

    wm = context.window_manager
    drawer_live = float(getattr(wm, "mixar_moodboard_drawer_amount", 0.0)) >= 0.98
    mixie_fallback = None
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if drawer_live and area.type == "VIEW_3D":
                for candidate in area.regions:
                    if (
                        candidate.type == "TOOL_PROPS"
                        and candidate.width > 1
                        and getattr(candidate, "view2d", None) is not None
                    ):
                        return candidate
            if area.type == "MIXIE" and mixie_fallback is None:
                for candidate in area.regions:
                    if (
                        candidate.type == "WINDOW"
                        and getattr(candidate, "view2d", None) is not None
                    ):
                        mixie_fallback = candidate
                        break
    return mixie_fallback


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

