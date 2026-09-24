# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — hand-drawn marks and hints.

* ``draw_scribble`` — an accent ring around an anchor rect that fades in
  over ``reveal`` plus a five-stroke starburst at the top-left corner whose
  strokes appear one by one, like ink being laid down.
* ``draw_hint`` — a small dark pill with a short label under (or over) an
  anchor.
* ``draw_spotlight_dim`` — the film behind hero beats and "your turn"
  gates, with the target and the video card left bright.

Strokes are thin rotated quads through the ``UNIFORM_COLOR`` shader, so
nothing here depends on the viewport-size uniform of the polyline shader.
"""

import math

import gpu
from gpu_extras.batch import batch_for_shader

from mixar.config.logging_config import get_logger
from mixar.modules.common.notifications.toast_renderer_shapes import (
    draw_rounded_rect_outline,
    draw_rect,
    draw_rounded_rect,
)

from .. import config
from .ring import draw_rounded_ring
from .text import draw_text, text_height, text_width

logger = get_logger(__name__)

STARBURST_STROKES = 5
STARBURST_LENGTH = 14.0       # logical px
STARBURST_WIDTH = 2.6
STARBURST_GAP = 5.0           # from the ring's outer corner
# Fan of stroke directions (radians) around the up-left diagonal.
_STARBURST_ANGLES = tuple(
    math.radians(180.0 - 12.0 - i * (72.0 / (STARBURST_STROKES - 1)))
    for i in range(STARBURST_STROKES)
)  # ~168° … 96°, i.e. left → up
HINT_PAD_X = 12.0
HINT_PAD_Y = 7.0
HINT_GAP = 10.0

_shader = None


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader


def _with_alpha(color: tuple, alpha: float) -> tuple:
    return (color[0], color[1], color[2], color[3] * max(0.0, min(1.0, alpha)))


def _lighter(color: tuple, amount: float = 0.18) -> tuple:
    return (min(1.0, color[0] + amount), min(1.0, color[1] + amount),
            min(1.0, color[2] + amount), color[3])


def _stroke_quad(x0: float, y0: float, x1: float, y1: float, width: float) -> tuple:
    """A line segment as a thin quad (four vertices, CCW)."""
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return ((x0, y0), (x0, y0), (x0, y0), (x0, y0))
    nx, ny = -dy / length * width * 0.5, dx / length * width * 0.5
    return ((x0 + nx, y0 + ny), (x0 - nx, y0 - ny),
            (x1 - nx, y1 - ny), (x1 + nx, y1 + ny))


def _draw_strokes(quads: list, color: tuple) -> None:
    if not quads:
        return
    verts: list = []
    indices: list = []
    for quad in quads:
        base = len(verts)
        verts.extend(quad)
        indices.append((base, base + 1, base + 2))
        indices.append((base, base + 2, base + 3))
    shader = _get_shader()
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def starburst_quads(corner_x: float, corner_y: float, reveal: float,
                    ui_scale: float = 1.0) -> list:
    """Stroke quads radiating up-left from ``(corner_x, corner_y)``.

    Stroke ``i`` exists once ``reveal > i / STARBURST_STROKES`` and grows to
    its full length over the following fifth of the reveal.
    """
    quads = []
    gap = STARBURST_GAP * ui_scale
    length = STARBURST_LENGTH * ui_scale
    width = STARBURST_WIDTH * ui_scale
    for i, angle in enumerate(_STARBURST_ANGLES):
        start = i / STARBURST_STROKES
        if reveal <= start:
            continue
        grow = min(1.0, (reveal - start) * STARBURST_STROKES)
        c, s = math.cos(angle), math.sin(angle)
        x0 = corner_x + c * gap
        y0 = corner_y + s * gap
        x1 = x0 + c * length * grow
        y1 = y0 + s * length * grow
        quads.append(_stroke_quad(x0, y0, x1, y1, width))
    return quads


RING_EDGE_INSET = 2.0   # logical px kept between a ring and the window edge


def draw_scribble(rect: tuple, reveal: float, alpha: float = 1.0,
                  ui_scale: float = 1.0, bounds: tuple = None,
                  starburst: bool = True) -> None:
    """Accent ring padded around ``rect`` plus the corner starburst.
    ``bounds`` (the window rect) keeps the ring inside the window: a tab in
    the island's header sits a few px from a rounded window edge, and a
    ring pushed past it gets cut."""
    reveal = max(0.0, min(1.0, reveal))
    if reveal <= 0.0 or alpha <= 0.0:
        return
    try:
        pad = config.SCRIBBLE_PAD * ui_scale
        xmin, ymin, xmax, ymax = rect
        # A region-sized anchor (a whole panel or window) gets an INSET ring:
        # padding outward would land the stroke in the neighbouring region.
        if (xmax - xmin) > 600 * ui_scale and (ymax - ymin) > 400 * ui_scale:
            pad = -pad
        if bounds is not None and pad > 0:
            # Shrink the padding uniformly so the ring keeps its shape and
            # stays clear of the window edge (a clamp would flatten one
            # side); with no room at all, draw it just inside the target.
            bx0, by0, bx1, by1 = bounds
            edge = RING_EDGE_INSET * ui_scale
            room = min(xmin - bx0, ymin - by0, bx1 - xmax, by1 - ymax) - edge
            pad = min(pad, room)
            if pad < 1.5 * ui_scale:
                pad = -2.0 * ui_scale
        x, y = xmin - pad, ymin - pad
        w, h = (xmax - xmin) + 2 * pad, (ymax - ymin) + 2 * pad
        if w <= 0 or h <= 0:
            return
        ring_alpha = alpha * reveal
        bottom = _with_alpha(config.ACCENT, ring_alpha)
        top = _with_alpha(_lighter(config.ACCENT), ring_alpha)
        draw_rounded_ring(
            x, y, w, h,
            config.SCRIBBLE_THICKNESS * ui_scale,
            config.SCRIBBLE_RADIUS * ui_scale,
            bottom, top,
        )
        # The starburst fans out above-left of the ring. Where that would
        # cross the window edge (a tab in the island's header) it would be
        # cut mid-stroke, so it is skipped rather than drawn clipped.
        reach = (STARBURST_GAP + STARBURST_LENGTH) * ui_scale
        if starburst and (bounds is None
                          or (x - reach >= bounds[0] and y + h + reach <= bounds[3])):
            quads = starburst_quads(x, y + h, reveal, ui_scale)
            _draw_strokes(quads, _with_alpha(config.ACCENT, alpha))
    except Exception as exc:
        logger.debug("Tour scribble draw failed: %s", exc)


def hint_rect(text: str, anchor_rect: tuple, window_rect: tuple,
              ui_scale: float = 1.0, side: str = "auto") -> tuple:
    """Where the hint pill for ``text`` goes: centred below ``anchor_rect``,
    flipped above when it would leave ``window_rect``, clamped sideways.
    ``side="left"`` seats it to the left of the anchor instead (for targets
    inside an overlapping region such as the moodboard drawer, whose own
    paint would cover a pill placed inside it)."""
    px = config.HINT_FONT_PX * ui_scale
    w = text_width(text, px) + 2 * HINT_PAD_X * ui_scale
    h = text_height(px) + 2 * HINT_PAD_Y * ui_scale
    gap = HINT_GAP * ui_scale
    axmin, aymin, axmax, aymax = anchor_rect
    wxmin, wymin, wxmax, wymax = window_rect

    if side == "left":
        xmax = axmin - gap
        xmin = xmax - w
        cy = (aymin + aymax) * 0.5
        ymin = cy - h * 0.5
        ymax = ymin + h
        if xmin < wxmin:
            xmin, xmax = wxmin, wxmin + w
        if ymin < wymin:
            ymin, ymax = wymin, wymin + h
        if ymax > wymax:
            ymax, ymin = wymax, wymax - h
        return (xmin, ymin, xmax, ymax)

    cx = (axmin + axmax) * 0.5
    # A region-sized anchor (the whole viewport) has no "below": seat the
    # pill inside it, a little under its top edge, where the eye lands.
    if (aymax - aymin) > 0.5 * (wymax - wymin):
        ymax = aymax - 3 * gap
        ymin = ymax - h
        xmin = cx - w * 0.5
        return (xmin, ymin, xmin + w, ymax)
    ymax = aymin - gap
    ymin = ymax - h
    if ymin < wymin:
        ymin = aymax + gap
        ymax = ymin + h
        if ymax > wymax:
            ymax = wymax
            ymin = ymax - h
    xmin = cx - w * 0.5
    xmax = xmin + w
    if xmax > wxmax:
        xmax = wxmax
        xmin = xmax - w
    if xmin < wxmin:
        xmin = wxmin
        xmax = xmin + w
    return (xmin, ymin, xmax, ymax)


def draw_hint(text: str, anchor_rect: tuple, window_rect: tuple,
              ui_scale: float = 1.0, alpha: float = 1.0, side: str = "auto",
              accent: bool = False) -> tuple:
    """Dark rounded pill with ``text``; returns the pill rect."""
    rect = hint_rect(text, anchor_rect, window_rect, ui_scale, side=side)
    if alpha <= 0.0 or not text:
        return rect
    try:
        xmin, ymin, xmax, ymax = rect
        w, h = xmax - xmin, ymax - ymin
        draw_rounded_rect(xmin, ymin, w, h, h * 0.5, _with_alpha(config.HINT_BG, alpha))
        if accent:
            draw_rounded_rect_outline(xmin, ymin, xmax - xmin, ymax - ymin, h * 0.5,
                                      _with_alpha(config.ACCENT, alpha * 0.9), width=1.5 * ui_scale)
        px = config.HINT_FONT_PX * ui_scale
        draw_text(xmin + HINT_PAD_X * ui_scale,
                  ymin + HINT_PAD_Y * ui_scale + px * 0.18,
                  text, px, _with_alpha(config.HINT_TEXT, alpha))
    except Exception as exc:
        logger.debug("Tour hint draw failed: %s", exc)
    return rect


def draw_success_flash(rect: tuple, t: float, ui_scale: float = 1.0,
                       bounds: tuple = None) -> None:
    """A ring that grows out of ``rect`` and fades over ``t`` in 0..1 — the
    "you did it" beat when the user completes a gate."""
    t = max(0.0, min(1.0, t))
    if t >= 1.0:
        return
    grow = config.GATE_DONE_FLASH_GROW * ui_scale * t
    xmin, ymin, xmax, ymax = rect
    x, y = xmin - grow, ymin - grow
    w, h = (xmax - xmin) + 2 * grow, (ymax - ymin) + 2 * grow
    if bounds is not None:
        x, y = max(x, bounds[0]), max(y, bounds[1])
        w, h = min(x + w, bounds[2]) - x, min(y + h, bounds[3]) - y
    if w <= 0 or h <= 0:
        return
    a = 1.0 - t
    draw_rounded_ring(x, y, w, h, config.SCRIBBLE_THICKNESS * ui_scale,
                       config.SCRIBBLE_RADIUS * ui_scale + grow,
                       _with_alpha(config.ACCENT, a), _with_alpha(_lighter(config.ACCENT), a))


def _subtract(rects: list, hole: tuple) -> list:
    """Split every rect in ``rects`` around ``hole`` (up to four bands each)."""
    hx0, hy0, hx1, hy1 = hole
    out = []
    for (xmin, ymin, xmax, ymax) in rects:
        cx0, cy0, cx1, cy1 = max(xmin, hx0), max(ymin, hy0), min(xmax, hx1), min(ymax, hy1)
        if cx1 <= cx0 or cy1 <= cy0:
            out.append((xmin, ymin, xmax, ymax))
            continue
        if cy0 > ymin:
            out.append((xmin, ymin, xmax, cy0))       # below
        if ymax > cy1:
            out.append((xmin, cy1, xmax, ymax))       # above
        if cx0 > xmin:
            out.append((xmin, cy0, cx0, cy1))         # left
        if xmax > cx1:
            out.append((cx1, cy0, xmax, cy1))         # right
    return out


def draw_spotlight_dim(rect: tuple, hole: tuple, color: tuple = config.GATE_DIM,
                       pad: float = 0.0, keep=()) -> None:
    """Dim ``rect`` except a window of light around ``hole`` (padded) and
    any ``keep`` rects (unpadded, e.g. the video card)."""
    pieces = [tuple(rect)]
    if hole is not None:
        hx0, hy0, hx1, hy1 = hole
        pieces = _subtract(pieces, (hx0 - pad, hy0 - pad, hx1 + pad, hy1 + pad))
    for k in keep:
        if k is not None:
            pieces = _subtract(pieces, tuple(k))
    for (x0, y0, x1, y1) in pieces:
        if x1 > x0 and y1 > y0:
            draw_rect(x0, y0, x1 - x0, y1 - y0, color)
