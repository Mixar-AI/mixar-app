# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the video card's player controls.

Laid out like a video player: **Back**, **Play/Pause** and **Next** sit as a
cluster of discs in the middle of the video. They show only while the pointer
is over the card, the tour is paused or the exit dialog is up
(``controls_alpha``), over a light scrim across the whole frame so the white
glyphs read on a bright shot. The centre button is the only play/pause icon:
Play while paused, Pause while playing. **Skip tour** is a small pill in the
video's top-right corner. It never fully hides (``SKIP_TOUR_REST_ALPHA``), so
leaving the tour is always one obvious click away without competing with the
founder video.

``button_rects`` is pure arithmetic over ``config`` (it runs under the test
mocks); the painters touch the GPU. Button keys are stable QA contract
names: ``skip`` is Next and ``exit`` is Skip tour (``tour_skip`` /
``tour_exit`` in the harness).
"""

from typing import Optional

import gpu
from gpu_extras.batch import batch_for_shader

from mixar.modules.common.i18n import iface_
from mixar.modules.common.notifications.toast_renderer_shapes import (
    draw_circle,
    draw_rect,
    draw_rounded_rect,
)

from .. import config
from .text import draw_text_centered, text_width as _text_width

# Hit-test order; also the order of ``qa_targets``.
BUTTON_ORDER = ("back", "pause", "skip", "exit")
TRANSPORT = ("back", "pause", "skip")
GATE_CAPTION = "Your turn"
GATE_CAPTION_INSET = 10.0     # logical px from the video's right edge
CONTROL_TEXT_HOVER = (1.0, 1.0, 1.0, 1.0)


def with_alpha(color: tuple, alpha: float) -> tuple:
    return (color[0], color[1], color[2], color[3] * max(0.0, min(1.0, alpha)))


def skip_tour_rect(video: tuple, s: float) -> tuple:
    """The Skip tour pill, inset from the video's top-right corner."""
    px = config.SKIP_TOUR_FONT_PX * s
    w = _text_width(iface_(config.CONTROL_EXIT), px) + 2 * config.SKIP_TOUR_PAD_X * s
    h = px + 2 * config.SKIP_TOUR_PAD_Y * s
    inset = config.SKIP_TOUR_INSET * s
    xmax, ymax = video[2] - inset, video[3] - inset
    return (max(video[0], xmax - w), max(video[1], ymax - h), xmax, ymax)


def _cluster_scale(video: tuple, s: float) -> float:
    """``s``, shrunk when the video is too small for the full cluster."""
    w = (config.CONTROL_SIDE_D * 2 + config.CONTROL_PLAY_D
         + config.CONTROL_CLUSTER_GAP * 2) * s
    vw, vh = video[2] - video[0], video[3] - video[1]
    fit = min(1.0, vw * 0.8 / w if w else 1.0,
              vh * 0.6 / (config.CONTROL_PLAY_D * s) if s else 1.0)
    return s * max(0.0, fit)


def controls_rect(video: tuple, s: float) -> tuple:
    """The transport cluster's bounding box, centred on the video."""
    k = _cluster_scale(video, s)
    w = (config.CONTROL_SIDE_D * 2 + config.CONTROL_PLAY_D
         + config.CONTROL_CLUSTER_GAP * 2) * k
    h = config.CONTROL_PLAY_D * k
    cx, cy = (video[0] + video[2]) * 0.5, (video[1] + video[3]) * 0.5
    return (cx - w * 0.5, cy - h * 0.5, cx + w * 0.5, cy + h * 0.5)


def button_rects(video: tuple, s: float) -> dict:
    """Every control's hit rect: the three transport discs' squares in the
    middle of the video, and Skip tour over its top-right corner."""
    k = _cluster_scale(video, s)
    side, play = config.CONTROL_SIDE_D * k, config.CONTROL_PLAY_D * k
    gap = config.CONTROL_CLUSTER_GAP * k
    cx, cy = (video[0] + video[2]) * 0.5, (video[1] + video[3]) * 0.5
    buttons = {"pause": (cx - play * 0.5, cy - play * 0.5, cx + play * 0.5, cy + play * 0.5)}
    left = cx - play * 0.5 - gap
    buttons["back"] = (left - side, cy - side * 0.5, left, cy + side * 0.5)
    right = cx + play * 0.5 + gap
    buttons["skip"] = (right, cy - side * 0.5, right + side, cy + side * 0.5)
    buttons["exit"] = skip_tour_rect(video, s)
    return buttons


# -- glyphs -----------------------------------------------------------------

def _tris(tris: list, color: tuple) -> None:
    """Fill a list of triangles ``((x, y), (x, y), (x, y))``."""
    verts = [v for tri in tris for v in tri]
    indices = [(i, i + 1, i + 2) for i in range(0, len(verts), 3)]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def _quad(x0, y0, x1, y1) -> list:
    return [((x0, y0), (x1, y0), (x1, y1)), ((x0, y0), (x1, y1), (x0, y1))]


def _draw_glyph(name: str, paused: bool, rect: tuple, size: float, color: tuple) -> None:
    cx = (rect[0] + rect[2]) * 0.5
    cy = (rect[1] + rect[3]) * 0.5
    h = size * 0.5
    bar = max(1.5, size * 0.16)
    if name == "pause" and paused:        # play: a right-pointing triangle
        _tris([((cx - h * 0.75, cy - h), (cx - h * 0.75, cy + h), (cx + h, cy))], color)
    elif name == "pause":                 # pause: two bars
        gap = size * 0.18
        w = size * 0.24
        _tris(_quad(cx - gap - w, cy - h, cx - gap, cy + h)
              + _quad(cx + gap, cy - h, cx + gap + w, cy + h), color)
    elif name == "skip":                  # next: triangle into a bar
        tri_w = size * 0.7
        x0 = cx - (tri_w + bar) * 0.5
        _tris([((x0, cy - h), (x0, cy + h), (x0 + tri_w, cy))]
              + _quad(x0 + tri_w, cy - h, x0 + tri_w + bar, cy + h), color)
    elif name == "back":                  # previous: a bar, then a triangle
        tri_w = size * 0.7
        x0 = cx - (tri_w + bar) * 0.5
        _tris(_quad(x0, cy - h, x0 + bar, cy + h)
              + [((x0 + bar + tri_w, cy - h), (x0 + bar + tri_w, cy + h), (x0 + bar, cy))],
              color)


# -- painters ---------------------------------------------------------------

def draw_controls(layout, paused: bool, s: float,
                  hover: Optional[str], alpha: float) -> None:
    """A light scrim over the video, then the transport discs and glyphs."""
    if alpha <= 0.0:
        return
    vx0, vy0, vx1, vy1 = layout.video
    draw_rect(vx0, vy0, vx1 - vx0, vy1 - vy0, with_alpha(config.CONTROLS_SCRIM, alpha))
    for name in TRANSPORT:
        rect = layout.buttons.get(name)
        if rect is None:
            continue
        d = min(rect[2] - rect[0], rect[3] - rect[1])
        disc = config.CONTROL_DISC_HOVER if hover == name else config.CONTROL_DISC
        draw_circle((rect[0] + rect[2]) * 0.5, (rect[1] + rect[3]) * 0.5, d * 0.5,
                    with_alpha(disc, alpha), segments=40)
        color = CONTROL_TEXT_HOVER if hover == name else config.CONTROL_TEXT
        _draw_glyph(name, paused, rect, d * config.CONTROL_GLYPH_FRAC,
                    with_alpha(color, alpha))


def draw_skip_tour(layout, s: float, hover: Optional[str], alpha: float,
                   controls_alpha: float) -> None:
    """The Skip tour pill: a dimmed label at rest, full while the card is
    hovered, darker under the pointer. The pill's film never dims, so the
    label reads over any frame."""
    rect = layout.buttons.get("exit")
    if rect is None or alpha <= 0.0:
        return
    rest = config.SKIP_TOUR_REST_ALPHA
    text_a = alpha * (rest + (1.0 - rest) * max(0.0, min(1.0, controls_alpha)))
    hovered = hover == "exit"
    xmin, ymin, xmax, ymax = rect
    h = ymax - ymin
    bg = config.SKIP_TOUR_BG_HOVER if hovered else config.SKIP_TOUR_BG
    draw_rounded_rect(xmin, ymin, xmax - xmin, h, h * 0.5, with_alpha(bg, alpha))
    color = CONTROL_TEXT_HOVER if hovered else config.CONTROL_TEXT
    draw_text_centered(rect, iface_(config.CONTROL_EXIT), config.SKIP_TOUR_FONT_PX * s,
                       with_alpha(color, text_a))


def draw_gate_caption(layout, s: float, alpha: float, controls_alpha: float) -> None:
    """Dim "Your turn" at the video's bottom-right corner."""
    px = config.CONTROL_FONT_PX * s
    cw = _text_width(iface_(GATE_CAPTION), px)
    inset = GATE_CAPTION_INSET * s
    right = layout.video[2] - inset
    if right - cw < layout.video[0] + inset:
        return
    bottom = layout.video[1] + inset
    a = alpha * max(config.GATE_CAPTION_ALPHA_FLOOR, controls_alpha)
    draw_text_centered((right - cw, bottom, right, bottom + px * 1.6),
                       iface_(GATE_CAPTION), px, with_alpha(config.CONTROL_TEXT_DIM, a))

