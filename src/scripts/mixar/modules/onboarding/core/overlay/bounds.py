# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Highlight bounds functions.

Each function takes a live Blender region and returns ``(x, y, w, h)``
in region-local coordinates. Values use ``scaled()`` so the highlight
scales correctly across DPI / ui_scale settings.
"""

import bpy

from mixar.modules.onboarding.constants import (
    HIGHLIGHT_REGION_INSET,
    HIGHLIGHT_TOPBAR_INSET,
    SIDEBAR_PANEL_H_IMAGE_TO_3D,
    SIDEBAR_PANEL_H_IMAGEGEN,
    SIDEBAR_PANEL_H_RETOPOLOGY,
    SIDEBAR_PANEL_PAD,
    SIDEBAR_TAB_STRIP_WIDTH,
    TOPBAR_MODE_BUTTON_W,
    TOPBAR_MODE_BUTTON_X,
)


def _ui_scale() -> float:
    try:
        return float(bpy.context.preferences.system.ui_scale)
    except Exception:
        return 1.0


def scaled(value: float) -> int:
    return max(1, int(round(value * _ui_scale())))


def full_window_bounds(region) -> tuple:
    """Whole region with a small inset."""
    inset = scaled(HIGHLIGHT_REGION_INSET)
    return (
        inset,
        inset,
        max(0, region.width - 2 * inset),
        max(0, region.height - 2 * inset),
    )


def sidebar_panel_bounds(region, panel_h_unscaled: float) -> tuple:
    """Bounds for the active sidebar tool panel."""
    panel_h = scaled(panel_h_unscaled)
    tab_strip_w = scaled(SIDEBAR_TAB_STRIP_WIDTH)
    pad = scaled(SIDEBAR_PANEL_PAD)
    content_w = max(0, region.width - tab_strip_w)
    x = pad
    y = max(0, region.height - panel_h - pad)
    w = max(0, content_w - 2 * pad)
    h = min(panel_h, region.height - y - pad)
    return (x, y, w, h)


def imagegen_bounds(region) -> tuple:
    return sidebar_panel_bounds(region, SIDEBAR_PANEL_H_IMAGEGEN)


def image_to_3d_bounds(region) -> tuple:
    return sidebar_panel_bounds(region, SIDEBAR_PANEL_H_IMAGE_TO_3D)


def retopology_bounds(region) -> tuple:
    return sidebar_panel_bounds(region, SIDEBAR_PANEL_H_RETOPOLOGY)


def topbar_strip_bounds(x_unscaled: int, w_unscaled: int, region) -> tuple:
    """Narrow horizontal strip of the topbar HEADER region."""
    if region.x != 0:
        return (0, 0, 0, 0)
    inset = scaled(HIGHLIGHT_TOPBAR_INSET)
    x = scaled(x_unscaled)
    w = scaled(w_unscaled)
    x = max(0, min(x, region.width - 1))
    w = min(w, region.width - x)
    h = max(0, region.height - 2 * inset)
    return (x, inset, w, h)


def topbar_mode_button_bounds(region) -> tuple:
    return topbar_strip_bounds(
        TOPBAR_MODE_BUTTON_X, TOPBAR_MODE_BUTTON_W, region,
    )


def bubble_area_bounds(region) -> tuple:
    """Bounds of the FULL Agent Bubble area in the region's local coords."""
    try:
        area = bpy.context.area
        if area is None or not area.regions:
            return (0, 0, 0, 0)
        if area.width < 300 or area.height < 150:
            return (0, 0, 0, 0)
        visible = [r for r in area.regions if r.width > 1 and r.height > 1]
        if not visible:
            return (0, 0, 0, 0)
        x_min = min(r.x for r in visible)
        y_min = min(r.y for r in visible)
        x_max = max(r.x + r.width for r in visible)
        y_max = max(r.y + r.height for r in visible)
        return (
            x_min - region.x,
            y_min - region.y,
            x_max - x_min,
            y_max - y_min,
        )
    except Exception:
        return (0, 0, 0, 0)
