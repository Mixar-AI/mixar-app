# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Host area / region resolution for onboarding cards.

Finds the best visible area+region to host a card, computes fit-scale
so the card doesn't overflow, maps area types to Space classes for
draw-handler attachment, and locates the Agent Bubble window for
proximity-positioning.
"""

import bpy

from mixar.modules.onboarding.constants import (
    CARD_AREA_MARGIN,
    CARD_BUBBLE_GAP,
    CARD_CHAT_INPUT_GUTTER,
    CARD_POS_ABOVE_INPUT,
    CARD_POS_SIDEBAR_ADJACENT,
    CARD_SIDEBAR_WIDTH,
)

# Proportion-of-region caps.
_CARD_REGION_WIDTH_CAP = 0.6
_CARD_REGION_HEIGHT_CAP = 0.78
_CARD_MIN_SCALE = 0.5

# Default edge margin used by ``fit_scale_for_region`` (px). Shared so
# clearance computations can express "reserved" space in the same
# convention (``avail_h = height - 2 * margin - reserved_h``).
_FIT_MARGIN = 80


def find_host(area_type: str):
    """Find a visible area of ``area_type`` and its WINDOW region.

    Returns ``(window, area, region)`` or ``(None, None, None)``.
    Falls back through MIXIE → VIEW_3D.
    """
    try:
        windows = bpy.data.window_managers[0].windows
    except Exception:
        return None, None, None

    for try_type in (area_type, "MIXIE", "VIEW_3D"):
        for window in windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type != try_type:
                    continue
                for region in area.regions:
                    if region.type == "WINDOW":
                        return window, area, region
    return None, None, None


def find_largest_window_region():
    """Return ``(window, area, region)`` for the largest visible WINDOW region."""
    try:
        windows = bpy.data.window_managers[0].windows
    except Exception:
        return None, None, None
    if not windows:
        return None, None, None
    window = windows[0]
    if window.screen is None:
        return None, None, None

    best = (None, None)
    best_score = -1
    for area in window.screen.areas:
        for region in area.regions:
            if region.type != "WINDOW":
                continue
            score = region.width * region.height
            if score > best_score:
                best_score = score
                best = (area, region)

    area, region = best
    if area is None or region is None:
        return None, None, None
    return window, area, region


def fit_scale_for_region(region, target_scale: float,
                         base_w: int, base_h: int,
                         margin: int = _FIT_MARGIN,
                         reserved_w: int = 0,
                         reserved_h: int = 0) -> float:
    """Return the largest scale <= ``target_scale`` that fits the region."""
    avail_w = max(1, region.width - 2 * margin - reserved_w)
    avail_h = max(1, region.height - 2 * margin - reserved_h)
    margin_scale_x = avail_w / base_w
    margin_scale_y = avail_h / base_h
    proportion_scale_x = (region.width * _CARD_REGION_WIDTH_CAP) / base_w
    proportion_scale_y = (region.height * _CARD_REGION_HEIGHT_CAP) / base_h
    fit = min(
        target_scale,
        margin_scale_x, margin_scale_y,
        proportion_scale_x, proportion_scale_y,
    )
    return max(_CARD_MIN_SCALE, fit)


def reserved_space_for_position(pos_kind: str) -> tuple:
    """Return ``(reserved_w, reserved_h)`` for the given position kind."""
    if pos_kind == CARD_POS_SIDEBAR_ADJACENT:
        return (CARD_SIDEBAR_WIDTH + CARD_AREA_MARGIN, 0)
    if pos_kind == CARD_POS_ABOVE_INPUT:
        return (0, CARD_CHAT_INPUT_GUTTER)
    return (0, 0)


def space_type_for_area_type(area_type: str):
    """Map an area type string to the matching ``bpy.types.Space*`` class."""
    candidate = {
        "MIXIE": "SpaceMixie",
        "MIXIE_CHAT": "SpaceMixieChat",
        "AGENT_BUBBLE": "SpaceAgentBubble",
        "VIEW_3D": "SpaceView3D",
    }.get(area_type)
    if candidate is None:
        return None
    return getattr(bpy.types, candidate, None)


def find_bubble_window():
    """Return the Blender Window hosting the floating Agent Bubble, or None."""
    try:
        wm = bpy.context.window_manager
    except Exception:
        return None
    if wm is None:
        return None
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "AGENT_BUBBLE":
                return window
    return None


def bubble_clearance_height(host_window_origin: tuple, region) -> int:
    """Vertical space to reserve (in ``fit_scale_for_region``'s
    ``reserved_h`` convention) so a TOP-anchored card's bottom clears
    the floating Agent Bubble window.

    The bubble is a separate OS-level window docked over the host
    region's bottom-left corner, so a tall top-left card can end up
    cropped behind it (the welcome / completion cards). Returns 0 when
    no bubble window is open, or when the bubble sits in the right
    half of the region where it can't collide with a left-anchored
    card.
    """
    anchor = bubble_anchor_in_region(
        host_window_origin, (region.x, region.y),
    )
    if anchor is None:
        return 0
    bcx, bcy, bw, bh = anchor
    bubble_left = bcx - bw // 2
    bubble_top = bcy + bh // 2
    if bubble_left > region.width * 0.5:
        return 0
    if bubble_top <= 0 or bubble_top >= region.height:
        return 0
    # fit_scale uses avail_h = height - 2*margin - reserved_h; we want
    # card_h <= height - margin(top) - bubble_top - gap, hence:
    return max(0, bubble_top + CARD_BUBBLE_GAP - _FIT_MARGIN)


def bubble_anchor_in_region(host_window_origin: tuple,
                            host_region_origin: tuple) -> tuple:
    """Return ``(cx, cy, bw, bh)`` of the bubble in region-local coords, or None."""
    bubble = find_bubble_window()
    if bubble is None:
        return None
    try:
        bx = int(bubble.x)
        by = int(bubble.y)
        bw = int(bubble.width)
        bh = int(bubble.height)
    except Exception:
        return None
    host_win_x, host_win_y = host_window_origin
    region_x, region_y = host_region_origin
    bcx_screen = bx + bw // 2
    bcy_screen = by + bh // 2
    region_origin_x = host_win_x + region_x
    region_origin_y = host_win_y + region_y
    cx = bcx_screen - region_origin_x
    cy = bcy_screen - region_origin_y
    return (cx, cy, bw, bh)
