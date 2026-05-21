# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Step Highlight

Paints a rounded green-gradient border around the UI element each
step is describing — the moodboard canvas for STEP_INFO_MOODBOARD,
the active sidebar tool panel for the three sidebar steps, and the
floating Agent Bubble for STEP_INFO_MIXIE_CHAT. The chat-step
border is painted *inside* the bubble's own window region, since
the bubble is a separate OS-level Blender window (WM_window_open_temp)
that draw handlers in the main Mixar window can't reach.

Architecture: a POST_PIXEL draw handler is attached to each relevant
``(Space, region_type)`` pair. On every redraw the callback consults
the current onboarding step, looks up the matching rule, computes
region-local bounds (sized in unscaled UI px and multiplied by
``ui_scale`` so it tracks across DPI / scale settings), and strokes
a rounded gradient border around it. No editor content is modified
— the border is purely overlay paint.
"""

import math

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from mixar.config.logging_config import get_logger
from mixar.modules.onboarding.constants import (
    DEFAULT_STEP,
    HIGHLIGHT_BOTTOM_COLOR,
    HIGHLIGHT_CORNER_RADIUS,
    HIGHLIGHT_THICKNESS,
    HIGHLIGHT_TOP_COLOR,
    STEP_INFO_ENGINE_MODE,
    STEP_INFO_IMAGE_TO_3D,
    STEP_INFO_IMAGEGEN,
    STEP_INFO_MIXIE_CHAT,
    STEP_INFO_MOODBOARD,
    STEP_INFO_RETOPOLOGY,
    WM_PROP_STEP,
)
from mixar.modules.onboarding.core.overlay.bounds import (
    scaled,
    bubble_area_bounds,
    full_window_bounds,
    image_to_3d_bounds,
    imagegen_bounds,
    retopology_bounds,
    topbar_mode_button_bounds,
)

logger = get_logger(__name__)


# step_id → list of (area_type, region_type, bounds_fn) rules.
_RULES: dict = {
    STEP_INFO_MOODBOARD:    [("MIXIE",   "WINDOW", full_window_bounds)],
    STEP_INFO_IMAGEGEN:     [("MIXIE",   "UI",     imagegen_bounds)],
    STEP_INFO_IMAGE_TO_3D:  [("MIXIE",   "UI",     image_to_3d_bounds)],
    STEP_INFO_RETOPOLOGY:   [("MIXIE",   "UI",     retopology_bounds)],
    STEP_INFO_MIXIE_CHAT:   [
        ("AGENT_BUBBLE", None, bubble_area_bounds),
    ],
    STEP_INFO_ENGINE_MODE: [("TOPBAR", "HEADER", topbar_mode_button_bounds)],
}


# ---------------------------------------------------------------------------
# Drawing — a rounded ring (outer rounded rect minus inner rounded
# rect, stitched as triangles between the two perimeters).
# ---------------------------------------------------------------------------

def _color_at_y(y: float, y0: float, h: float,
                bottom: tuple, top: tuple) -> tuple:
    if h <= 0:
        return top
    t = (y - y0) / h
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return tuple(bottom[i] * (1.0 - t) + top[i] * t for i in range(4))


def _build_corner(cx: float, cy: float, radius_outer: float,
                  radius_inner: float, start_angle: float,
                  segments: int) -> tuple:
    outer = []
    inner = []
    for i in range(segments + 1):
        a = start_angle + (math.pi * 0.5) * (i / segments)
        c, s = math.cos(a), math.sin(a)
        outer.append((cx + radius_outer * c, cy + radius_outer * s))
        inner.append((cx + radius_inner * c, cy + radius_inner * s))
    return outer, inner


def _draw_rounded_ring(x: float, y: float, w: float, h: float,
                        thickness: float, radius: float,
                        bottom_color: tuple, top_color: tuple,
                        corner_segments: int = 10) -> None:
    if w <= thickness * 2 or h <= thickness * 2:
        return

    radius_outer = max(thickness + 0.5, min(radius, w * 0.5, h * 0.5))
    radius_inner = max(0.0, radius_outer - thickness)

    corners = (
        (x + radius_outer,         y + radius_outer,         math.pi),
        (x + w - radius_outer,     y + radius_outer,         1.5 * math.pi),
        (x + w - radius_outer,     y + h - radius_outer,     0.0),
        (x + radius_outer,         y + h - radius_outer,     0.5 * math.pi),
    )

    outer_pts: list = []
    inner_pts: list = []
    for cx, cy, start in corners:
        co, ci = _build_corner(cx, cy, radius_outer, radius_inner,
                                start, corner_segments)
        outer_pts.extend(co)
        inner_pts.extend(ci)

    n = len(outer_pts)
    verts: list = []
    colors: list = []
    for i in range(n):
        verts.append(outer_pts[i])
        colors.append(_color_at_y(outer_pts[i][1], y, h,
                                  bottom_color, top_color))
        verts.append(inner_pts[i])
        colors.append(_color_at_y(inner_pts[i][1], y, h,
                                  bottom_color, top_color))

    indices: list = []
    for i in range(n - 1):
        a = i * 2
        b = i * 2 + 1
        c = (i + 1) * 2
        d = (i + 1) * 2 + 1
        indices.append((a, b, c))
        indices.append((b, d, c))
    a = (n - 1) * 2
    b = (n - 1) * 2 + 1
    c = 0
    d = 1
    indices.append((a, b, c))
    indices.append((b, d, c))

    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    batch = batch_for_shader(
        shader, 'TRIS',
        {"pos": verts, "color": colors},
        indices=indices,
    )
    gpu.state.blend_set('ALPHA')
    shader.bind()
    batch.draw(shader)
    gpu.state.blend_set('NONE')


# ---------------------------------------------------------------------------
# Draw callback + handler registry.
# ---------------------------------------------------------------------------

_handles: dict = {}


def _current_step_id() -> str:
    try:
        wm = bpy.context.window_manager
    except Exception:
        return DEFAULT_STEP
    if wm is None:
        return DEFAULT_STEP
    return getattr(wm, WM_PROP_STEP, DEFAULT_STEP) or DEFAULT_STEP


_first_fire_logged: set = set()


def _draw_callback() -> None:
    try:
        step_id = _current_step_id()
        rules = _RULES.get(step_id)
        if not rules:
            return

        area = bpy.context.area
        region = bpy.context.region
        if area is None or region is None:
            return

        thickness = max(2, scaled(HIGHLIGHT_THICKNESS))
        radius = max(thickness + 1, scaled(HIGHLIGHT_CORNER_RADIUS))

        for target_area, target_region, bounds_fn in rules:
            if area.type != target_area:
                continue
            if target_region is not None and region.type != target_region:
                continue

            x, y, w, h = bounds_fn(region)
            if w <= 0 or h <= 0:
                continue

            key = (step_id, area.type, region.type)
            if key not in _first_fire_logged:
                _first_fire_logged.add(key)
                logger.debug(
                    "Onboarding highlight first-fire: step=%s area=%s "
                    "region=%s (region %dx%d) bounds=(%d,%d %dx%d)",
                    step_id, area.type, region.type,
                    region.width, region.height, x, y, w, h,
                )

            _draw_rounded_ring(
                x, y, w, h, thickness, radius,
                HIGHLIGHT_BOTTOM_COLOR, HIGHLIGHT_TOP_COLOR,
            )
    except Exception as exc:
        logger.warning(
            "Onboarding highlight draw failed: %s", exc, exc_info=True,
        )


# ---------------------------------------------------------------------------
# Install / remove.
# ---------------------------------------------------------------------------

_TARGETS = (
    ("SpaceMixie",       "WINDOW"),
    ("SpaceMixie",       "UI"),
    ("SpaceAgentBubble", "WINDOW"),
    ("SpaceAgentBubble", "HEADER"),
    ("SpaceAgentBubble", "TOOLS"),
    ("SpaceTopBar",      "HEADER"),
)


def install_draw_handlers() -> None:
    """Attach the highlight callback to every space+region pair the
    rules table needs. Idempotent."""
    attached = []
    for space_name, region_type in _TARGETS:
        key = (space_name, region_type)
        if key in _handles:
            continue
        cls = getattr(bpy.types, space_name, None)
        if cls is None or not hasattr(cls, "draw_handler_add"):
            logger.warning(
                "Onboarding highlight: %s not available, skipping %s",
                space_name, region_type,
            )
            continue
        try:
            handle = cls.draw_handler_add(
                _draw_callback, (), region_type, "POST_PIXEL",
            )
        except Exception as exc:
            logger.warning(
                "Onboarding highlight: attach to %s/%s failed: %s",
                space_name, region_type, exc,
            )
            continue
        _handles[key] = (cls, region_type, handle)
        attached.append(f"{space_name}/{region_type}")
    if attached:
        logger.debug(
            "Onboarding highlight: attached to %s",
            ", ".join(attached),
        )


def remove_draw_handlers() -> None:
    for key, (cls, region_type, handle) in list(_handles.items()):
        try:
            cls.draw_handler_remove(handle, region_type)
        except Exception as exc:
            logger.debug(
                "Onboarding highlight: remove %s failed: %s", key, exc,
            )
        _handles.pop(key, None)


def tag_redraw() -> None:
    """Invalidate every area the highlight might paint into."""
    try:
        windows = bpy.data.window_managers[0].windows
    except Exception:
        return
    for window in windows:
        areas = []
        if window.screen is not None:
            areas.extend(window.screen.areas)
        globals_coll = getattr(window, "global_areas", None)
        if globals_coll is not None:
            areas.extend(globals_coll)
        for area in areas:
            if area.type in ("MIXIE", "AGENT_BUBBLE", "TOPBAR"):
                try:
                    area.tag_redraw()
                except Exception:
                    pass
                if area.type == "TOPBAR":
                    for region in area.regions:
                        try:
                            region.tag_redraw()
                        except Exception:
                            pass
