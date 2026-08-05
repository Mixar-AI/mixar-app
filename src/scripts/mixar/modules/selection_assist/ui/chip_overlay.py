# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hint chip overlay + module wiring for selection assist.

Draws a small bottom-center pill in the 3D viewport whenever the engine
has suggestions: the next suggestion's label with its key, plus cycle
position once cycling started. POST_PIXEL draw handler — same machinery
as the agent viewport-lock halo; the ghost outlines themselves are drawn
natively by the C++ overlay engine (see constants.GHOST_PROP).

This file also owns runtime wiring (engine timer, registry handlers,
load_post reset) so the whole feature registers through bootstrap's
normal ui discovery.
"""

import math

import bpy
import blf
import gpu
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader

from mixar.config.logging_config import get_logger

from ..constants import (
    CHIP_BG_COLOR,
    CHIP_BORDER_COLOR,
    CHIP_FONT_SIZE,
    CHIP_KEY_COLOR,
    CHIP_MARGIN_BOTTOM,
    CHIP_PAD_X,
    CHIP_PAD_Y,
    CHIP_RADIUS,
    CHIP_TEXT_COLOR,
)
from ..core import registry
from ..core.engine import ENGINE

logger = get_logger(__name__)

_draw_handle = None
_FONT_ID = 0
_SEGMENT_GAP = 8


def _rounded_rect_points(x, y, w, h, radius, arc_steps=6):
    """Rounded-rect outline points, counter-clockwise."""
    r = max(1.0, min(radius, w * 0.5, h * 0.5))
    corners = (
        (x + w - r, y + r, -0.5 * math.pi),      # bottom right
        (x + w - r, y + h - r, 0.0),             # top right
        (x + r, y + h - r, 0.5 * math.pi),       # top left
        (x + r, y + r, math.pi),                 # bottom left
    )
    points = []
    for cx, cy, start in corners:
        for i in range(arc_steps + 1):
            a = start + (i / arc_steps) * (0.5 * math.pi)
            points.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return points


def _fill_tris(points):
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    coords = []
    for i in range(len(points)):
        coords += [(cx, cy), points[i], points[(i + 1) % len(points)]]
    return coords


def _draw_chip():
    context = bpy.context
    if context.mode != 'OBJECT':
        return
    segments = ENGINE.chip_segments()
    if not segments:
        return
    region = context.region
    if region is None or region.width < 320:
        return

    try:
        ui_scale = context.preferences.system.ui_scale
    except Exception:
        ui_scale = 1.0

    blf.size(_FONT_ID, int(CHIP_FONT_SIZE * ui_scale))
    gap = _SEGMENT_GAP * ui_scale
    widths = []
    text_h = 0.0
    for _is_key, text in segments:
        tw, th = blf.dimensions(_FONT_ID, text)
        widths.append(tw)
        text_h = max(text_h, th)

    pad_x = CHIP_PAD_X * ui_scale
    pad_y = CHIP_PAD_Y * ui_scale
    chip_w = sum(widths) + gap * (len(segments) - 1) + 2 * pad_x
    chip_h = text_h + 2 * pad_y
    x = region.width * 0.5 - chip_w * 0.5
    y = CHIP_MARGIN_BOTTOM * ui_scale

    points = _rounded_rect_points(x, y, chip_w, chip_h, CHIP_RADIUS * ui_scale)

    gpu.state.blend_set('ALPHA')
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    fill = batch_for_shader(shader, 'TRIS', {"pos": _fill_tris(points)})
    shader.uniform_float("color", CHIP_BG_COLOR)
    fill.draw(shader)

    gpu.state.line_width_set(1.5)
    # LINE_LOOP/TRI_FAN are deprecated gpu primitives — close the strip manually.
    border = batch_for_shader(shader, 'LINE_STRIP', {"pos": points + [points[0]]})
    shader.uniform_float("color", CHIP_BORDER_COLOR)
    border.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')

    tx = x + pad_x
    ty = y + pad_y
    for (is_key, text), tw in zip(segments, widths):
        blf.position(_FONT_ID, tx, ty, 0)
        blf.color(_FONT_ID, *(CHIP_KEY_COLOR if is_key else CHIP_TEXT_COLOR))
        blf.draw(_FONT_ID, text)
        tx += tw + gap


@persistent
def _on_load_post(_filepath=None):
    ENGINE.reset()


def register():
    global _draw_handle
    registry.register_handlers()
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if not bpy.app.timers.is_registered(ENGINE.on_timer):
        bpy.app.timers.register(ENGINE.on_timer, first_interval=1.0, persistent=True)
    if not bpy.app.background and _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_chip, (), 'WINDOW', 'POST_PIXEL'
        )


def unregister():
    global _draw_handle
    if _draw_handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        except Exception:
            pass
        _draw_handle = None
    if bpy.app.timers.is_registered(ENGINE.on_timer):
        try:
            bpy.app.timers.unregister(ENGINE.on_timer)
        except Exception:
            pass
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    registry.unregister_handlers()
    ENGINE.reset()
