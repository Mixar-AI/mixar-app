# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Resolve image-tool coordinates in the canvas that owns the modal."""

from types import SimpleNamespace

from .moodboard_utils import mouse_to_image_coords as _image_coords


def mouse_to_image_coords(context, event, target_image_index):
    """Ignore popup/viewport View2D and use the originating area's canvas.

    Popup modals can retain a temporary or WINDOW region. Window coordinates
    remain authoritative after the popup closes and across Retina scaling.
    Never fall back to a canvas in another area or window.
    """
    area = context.area
    if area is None:
        return None
    if area.type == 'MIXIE':
        region_type = 'WINDOW'
    elif (area.type == 'VIEW_3D'
          and context.workspace.name == 'Zen Mode'
          and context.window_manager.mixar_moodboard_drawer_amount >= .98):
        region_type = 'TOOL_PROPS'
    else:
        return None
    region = next((r for r in area.regions
                   if r.type == region_type and r.width > 1), None)
    if region is None:
        return None
    local_event = SimpleNamespace(mouse_region_x=event.mouse_x - region.x,
                                  mouse_region_y=event.mouse_y - region.y)
    with context.temp_override(region=region):
        return _image_coords(context, local_event, target_image_index)
