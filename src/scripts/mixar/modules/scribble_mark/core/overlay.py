# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Painting the frozen frame and its marks.

A ``POST_PIXEL`` handler on the 3D viewport. While mark mode is armed it
paints, bottom to top: the captured still over the whole region, a light
scrim so the frame reads as *paused* rather than merely idle, every settled
mark, the stroke currently under the pen, and a hint pill.

Draw callbacks **only read**. They run on every mouse move, and the repo's
handler rule is absolute — depsgraph work and property writes belong in
operators and timers. The live stroke is handed here by the modal operator
through a module-level buffer rather than being read back off RNA, so a
redraw never touches scene data.

The still is drawn from a cached ``GPUTexture``. Rebuilding it per frame
re-uploads a full-screen image on every mouse move; the cache is keyed on the
image's name and update tag so a re-arm swaps it and nothing else does.
"""

from __future__ import annotations

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from mixar.config.logging_config import get_logger

from . import freeze
from ..constants import (
    MARK_HINT_ACCENT_COLOR,
    MARK_HINT_BG_COLOR,
    MARK_HINT_FONT_PX,
    MARK_HINT_HEIGHT_PX,
    MARK_HINT_IDLE,
    MARK_HINT_MARKED,
    MARK_HINT_PAD_X_PX,
    MARK_HINT_TEXT_COLOR,
    MARK_HINT_TOP_GAP_PX,
    MARK_INK_COLOR,
    MARK_INK_COLOR_SETTLED,
    MARK_INK_WIDTH,
    MARK_SCRIM_COLOR,
)

_FONT_ID = 0

logger = get_logger(__name__)

_handle = None

#: Strokes of the mark currently being drawn, in region pixels. Owned by the
#: modal operator; the draw pass only reads it.
_live_strokes = []

#: Settled marks of this freeze, as lists of strokes. Kept here rather than
#: re-parsed from the scene every frame — a draw callback must not do work
#: that grows with the number of marks.
_settled_strokes = []

_texture = None
_texture_key = None


# =============================================================================
# State handed in by the operator
# =============================================================================

def set_live_strokes(strokes):
    global _live_strokes
    _live_strokes = strokes


def push_settled(strokes):
    _settled_strokes.append([list(s) for s in strokes])


def pop_settled():
    if _settled_strokes:
        _settled_strokes.pop()


def reset():
    """Forget everything the overlay was drawing. Called on disarm."""
    global _live_strokes, _texture, _texture_key
    _live_strokes = []
    _settled_strokes.clear()
    _texture = None
    _texture_key = None


# =============================================================================
# Drawing
# =============================================================================

def _ui_scale():
    try:
        return float(bpy.context.preferences.system.ui_scale)
    except Exception:  # noqa: BLE001
        return 1.0


def _armed():
    wm = getattr(bpy.context, "window_manager", None)
    return bool(getattr(wm, "mixar_mark_armed", False))


def _frozen_texture(scene):
    """Cached GPUTexture of the frozen still, or None."""
    global _texture, _texture_key

    name = getattr(scene, "mixar_mark_frame_name", "") or ""
    if not name:
        return None
    image = freeze.get_image(name)
    if image is None:
        _texture, _texture_key = None, None
        return None

    key = (name, getattr(image, "is_dirty", False), tuple(image.size))
    if _texture is not None and _texture_key == key:
        return _texture

    try:
        _texture = gpu.texture.from_image(image)
        _texture_key = key
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: frozen frame texture failed: %s", exc)
        _texture, _texture_key = None, None
    return _texture


def _draw_still(region, texture):
    width, height = float(region.width), float(region.height)
    verts = ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height))
    uvs = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))

    shader = gpu.shader.from_builtin('IMAGE')
    batch = batch_for_shader(
        shader, 'TRIS',
        {"pos": verts, "texCoord": uvs},
        indices=((0, 1, 2), (0, 2, 3)),
    )
    shader.bind()
    shader.uniform_sampler("image", texture)
    batch.draw(shader)


def _draw_scrim(region):
    width, height = float(region.width), float(region.height)
    verts = ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(
        shader, 'TRIS', {"pos": verts}, indices=((0, 1, 2), (0, 2, 3))
    )
    shader.bind()
    shader.uniform_float("color", MARK_SCRIM_COLOR)
    batch.draw(shader)


def _draw_strokes(strokes, color, width):
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    shader.bind()
    viewport = gpu.state.viewport_get()
    shader.uniform_float("viewportSize", (viewport[2], viewport[3]))
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    for stroke in strokes:
        # A single sample is a dot, and LINE_STRIP of one point draws nothing;
        # doubling it gives the polyline shader a segment to round off, so a
        # deliberate tap is still visible ink.
        points = list(stroke)
        if len(points) == 1:
            points = points * 2
        if len(points) < 2:
            continue
        batch_for_shader(shader, 'LINE_STRIP', {"pos": points}).draw(shader)


def _hint_text(scene):
    """What the pill says, given how much has been drawn."""
    try:
        count = len(getattr(scene, "mixar_marks", ()) or ())
    except Exception:  # noqa: BLE001
        count = 0
    if not count:
        return MARK_HINT_IDLE
    return MARK_HINT_MARKED.format(count=count, plural="" if count == 1 else "s")


def _draw_hint(region, scene, scale):
    """A legend across the top of the frozen frame.

    Load-bearing, not decoration: the freeze consumes every pointer event over
    the region, so without a visible way out the user is looking at a picture
    of their scene with no idea how to get their viewport back.
    """
    text = _hint_text(scene)
    height = MARK_HINT_HEIGHT_PX * scale
    pad_x = MARK_HINT_PAD_X_PX * scale

    blf.size(_FONT_ID, int(round(MARK_HINT_FONT_PX * scale)))
    text_w, text_h = blf.dimensions(_FONT_ID, text)

    width = text_w + pad_x * 2.0
    x0 = (region.width - width) / 2.0
    y1 = region.height - MARK_HINT_TOP_GAP_PX * scale
    y0 = y1 - height

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(
        shader, 'TRIS',
        {"pos": ((x0, y0), (x0 + width, y0), (x0 + width, y1), (x0, y1))},
        indices=((0, 1, 2), (0, 2, 3)),
    )
    shader.bind()
    shader.uniform_float("color", MARK_HINT_BG_COLOR)
    batch.draw(shader)

    colour = MARK_HINT_ACCENT_COLOR if _live_strokes else MARK_HINT_TEXT_COLOR
    blf.color(_FONT_ID, *colour)
    blf.position(_FONT_ID, x0 + pad_x, y0 + (height - text_h) / 2.0, 0)
    blf.draw(_FONT_ID, text)


def _draw_callback():
    try:
        if not _armed():
            return
        area = bpy.context.area
        region = bpy.context.region
        if area is None or area.type != 'VIEW_3D':
            return
        if region is None or region.type != 'WINDOW':
            return

        scene = bpy.context.scene
        texture = _frozen_texture(scene)

        gpu.state.blend_set('ALPHA')
        try:
            if texture is not None:
                _draw_still(region, texture)
            _draw_scrim(region)

            scale = _ui_scale()
            width = MARK_INK_WIDTH * scale
            for strokes in _settled_strokes:
                _draw_strokes(strokes, MARK_INK_COLOR_SETTLED, width)
            if _live_strokes:
                _draw_strokes(_live_strokes, MARK_INK_COLOR, width)

            _draw_hint(region, scene, scale)
        finally:
            gpu.state.blend_set('NONE')
    except Exception as exc:  # noqa: BLE001 — a draw handler must never raise
        logger.warning("Scribble mark overlay draw failed: %s", exc, exc_info=True)


# =============================================================================
# Lifecycle
# =============================================================================

def install():
    """Attach the overlay to the 3D viewport WINDOW region. Idempotent."""
    global _handle
    if _handle is not None:
        return
    cls = getattr(bpy.types, "SpaceView3D", None)
    if cls is None or not hasattr(cls, "draw_handler_add"):
        logger.warning("Scribble mark: SpaceView3D unavailable, no overlay")
        return
    _handle = cls.draw_handler_add(_draw_callback, (), "WINDOW", "POST_PIXEL")


def remove():
    global _handle
    if _handle is None:
        return
    try:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: overlay handler removal failed: %s", exc)
    _handle = None
    reset()


def tag_redraw():
    """Invalidate 3D viewports so the ink follows the pen."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: redraw tag failed: %s", exc)
