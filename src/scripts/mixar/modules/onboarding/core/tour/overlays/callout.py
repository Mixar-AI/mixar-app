# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the callout box.

A larger sibling of the hint pill for a beat that introduces something
the viewer can act on later: a dark box with an accent edge, a small
pointer to its anchor (under a topbar button, or beside a row of an open
menu), a title, one or two lines of copy and a footer (the menu path).

Layout is pure math (``callout_rect``) so tests pin it without a GPU.
"""

import gpu
from gpu_extras.batch import batch_for_shader

from mixar.config.logging_config import get_logger
from mixar.modules.common.notifications.toast_renderer_shapes import (
    draw_rounded_rect,
    draw_rounded_rect_outline,
)

from .. import config
from .text import draw_text, text_height, text_width

logger = get_logger(__name__)

PAD_X = 16.0
PAD_Y = 14.0
LINE_GAP = 6.0
POINTER = 8.0          # pointer half-width and height
GAP = 6.0              # pointer tip to anchor
MAX_BODY_CHARS = 46    # wrap the body at about this many characters
RADIUS = 8.0

_shader = None


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader


def _with_alpha(color: tuple, alpha: float) -> tuple:
    return (color[0], color[1], color[2], color[3] * alpha)


def wrap(text: str, limit: int = MAX_BODY_CHARS) -> list:
    """Greedy word wrap by character count (deterministic, GPU-free)."""
    lines, line = [], ""
    for word in (text or "").split():
        trial = f"{line} {word}".strip()
        if line and len(trial) > limit:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def _lines(title: str, body: str, footer: str):
    return title, wrap(body), footer


def callout_rect(title: str, body: str, footer: str, anchor_rect: tuple,
                 window_rect: tuple, ui_scale: float = 1.0, side: str = "below") -> tuple:
    """The box (without the pointer). ``side="below"``: under
    ``anchor_rect``, left edge aligned to it, flipped above when there is no
    room below. ``side="right"``: beside it, vertically centred on it (a
    row of an open menu). Always clamped into ``window_rect``."""
    s = ui_scale
    title, body_lines, footer = _lines(title, body, footer)
    tpx, bpx = config.CALLOUT_TITLE_PX * s, config.CALLOUT_BODY_PX * s
    widths = [text_width(title, tpx)] + [text_width(l, bpx) for l in body_lines]
    if footer:
        widths.append(text_width(footer, bpx))
    w = max(widths or [0.0]) + 2 * PAD_X * s
    h = text_height(tpx) + 2 * PAD_Y * s
    h += len(body_lines) * (text_height(bpx) + LINE_GAP * s)
    if footer:
        h += text_height(bpx) + 2 * LINE_GAP * s
    axmin, aymin, axmax, aymax = anchor_rect
    wxmin, wymin, wxmax, wymax = window_rect
    drop = (GAP + POINTER) * s
    if side == "right":
        xmin = min(axmax + drop, wxmax - 8 * s - w)
        cy = (aymin + aymax) * 0.5
        ymin = max(wymin + 8 * s, min(cy - h * 0.5, wymax - 8 * s - h))
        return (xmin, ymin, xmin + w, ymin + h)
    ymax = aymin - drop
    ymin = ymax - h
    if ymin < wymin:
        ymin = aymax + drop
        ymax = ymin + h
    xmin = max(wxmin + 8 * s, min(axmin - PAD_X * s, wxmax - 8 * s - w))
    return (xmin, ymin, xmin + w, ymax)


def draw_callout(title: str, body: str, footer: str, anchor_rect: tuple,
                 window_rect: tuple, ui_scale: float = 1.0,
                 alpha: float = 1.0, side: str = "below") -> tuple:
    """Draw the callout; returns its rect."""
    rect = callout_rect(title, body, footer, anchor_rect, window_rect, ui_scale, side)
    if alpha <= 0.0:
        return rect
    s = ui_scale
    try:
        xmin, ymin, xmax, ymax = rect
        w, h = xmax - xmin, ymax - ymin
        bg = _with_alpha(config.CALLOUT_BG, alpha)
        draw_rounded_rect(xmin, ymin, w, h, RADIUS * s, bg)
        draw_rounded_rect_outline(xmin, ymin, w, h, RADIUS * s,
                                  _with_alpha(config.ACCENT, alpha * 0.9),
                                  width=1.5 * s)
        _draw_pointer(rect, anchor_rect, bg, s)
        title, body_lines, footer = _lines(title, body, footer)
        tpx, bpx = config.CALLOUT_TITLE_PX * s, config.CALLOUT_BODY_PX * s
        x = xmin + PAD_X * s
        y = ymax - PAD_Y * s - tpx * 0.82
        draw_text(x, y, title, tpx, _with_alpha(config.HINT_TEXT, alpha))
        y -= text_height(tpx) * 0.35 + LINE_GAP * s
        for line in body_lines:
            y -= text_height(bpx)
            draw_text(x, y, line, bpx, _with_alpha(config.CONTROL_TEXT_DIM, alpha))
            y -= LINE_GAP * s
        if footer:
            y -= text_height(bpx) + LINE_GAP * s
            draw_text(x, y, footer, bpx, _with_alpha(config.ACCENT, alpha))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Tour callout draw failed: %s", exc)
    return rect


def _draw_pointer(rect, anchor_rect, color, s) -> None:
    """A small triangle from the box edge toward the anchor's centre."""
    xmin, ymin, xmax, ymax = rect
    ax = (anchor_rect[0] + anchor_rect[2]) * 0.5
    ax = max(xmin + (RADIUS + POINTER) * s, min(ax, xmax - (RADIUS + POINTER) * s))
    p = POINTER * s
    if anchor_rect[2] <= xmin:          # anchor left of the box
        ay = (anchor_rect[1] + anchor_rect[3]) * 0.5
        ay = max(ymin + (RADIUS + POINTER) * s, min(ay, ymax - (RADIUS + POINTER) * s))
        tri = ((xmin, ay - p), (xmin, ay + p), (xmin - p, ay))
    elif anchor_rect[1] >= ymax:        # anchor above the box
        tri = ((ax - p, ymax), (ax + p, ymax), (ax, ymax + p))
    else:                               # anchor below the box
        tri = ((ax - p, ymin), (ax + p, ymin), (ax, ymin - p))
    shader = _get_shader()
    batch = batch_for_shader(shader, 'TRIS', {"pos": tri})
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
