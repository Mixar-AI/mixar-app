# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the video card.

The card is the video and nothing else: a dark rounded background only
``config.CARD_PAD`` larger than the frame, a hairline progress bar along the
frame's bottom edge and the caption pill. The controls (pause, speed, skip,
exit) sit in a translucent strip INSIDE the bottom of the video and are
drawn multiplied by ``controls_alpha`` — at 0 nothing of them is painted;
the session eases that toward 1 on hover / pause / exit dialog. Hit testing
and QA targets ignore visibility, so the harness can always click them.

``compute_card_layout`` turns a beat's card variant/placement into the
*target* rects inside a host rect, lifting the card above the floating Agent
island when they would overlap and shrinking it, aspect kept, when the host
is small. ``layout_from_card_rect`` rebuilds a full layout from an animated
card rect so the session can glide between targets. ``draw_card`` paints a
layout (with an optional freeze-frame film while a gate waits);
``draw_caption_under`` seats a hint-style pill centred under the card for
copy that belongs to the moment, not the video (the outro's replay note);
``hit_test`` and ``qa_targets`` read a layout back. The exit confirmation
lives in ``exit_dialog`` and is re-exported here.

Layout is pure arithmetic over ``config`` numbers, so it runs under the
test mocks; only ``draw_card`` touches the GPU.
"""

from dataclasses import dataclass, field
from typing import Optional

import gpu
from gpu_extras.batch import batch_for_shader

from mixar.config.logging_config import get_logger
from mixar.modules.common.notifications.toast_renderer_shapes import (
    draw_circle,
    draw_rect,
    draw_rounded_rect,
)

from .. import beats, config
from .exit_dialog import (  # noqa: F401 — re-exported API
    ExitConfirmLayout,
    compute_exit_confirm_layout,
    draw_exit_confirm,
    hit_test_exit_confirm,
)
from .text import draw_text_centered, text_width as _text_width

logger = get_logger(__name__)

__all__ = (
    "CardLayout", "compute_card_layout", "layout_from_card_rect", "draw_card",
    "draw_caption_under", "caption_under_rect",
    "hit_test", "qa_targets", "format_rate",
    "ExitConfirmLayout", "compute_exit_confirm_layout", "draw_exit_confirm",
    "hit_test_exit_confirm",
)

BUTTON_ORDER = ("pause", "speed", "skip", "exit")
BUTTON_PAD_X = 8.0            # logical px inside each text button
ISLAND_GAP = 12.0             # logical px between the island and a lifted card
MIN_VIDEO_W = 96.0
VIDEO_PLACEHOLDER = (0.03, 0.03, 0.04, 1.0)
CONTROL_TEXT_HOVER = (1.0, 1.0, 1.0, 1.0)
GATE_CAPTION = "Your turn"
GATE_CAPTION_INSET = 10.0     # logical px from the video's right edge
GATE_FILM = (0.0, 0.0, 0.0, 1.0)
CAPTION_PAD_X = 12.0          # logical px, the hint pill's padding
CAPTION_PAD_Y = 7.0


@dataclass
class CardLayout:
    card: tuple
    video: tuple
    controls: tuple               # strip inside the bottom of ``video``
    buttons: dict = field(default_factory=dict)


def _with_alpha(color: tuple, alpha: float) -> tuple:
    return (color[0], color[1], color[2], color[3] * max(0.0, min(1.0, alpha)))


def format_rate(rate: float) -> str:
    """``1.0`` → ``"1×"``, ``1.25`` → ``"1.25×"``."""
    text = f"{rate:.2f}".rstrip("0").rstrip(".")
    return f"{text}×"


def _widest(labels, px: float) -> float:
    return max((_text_width(label, px) for label in labels), default=0.0)


def _place(placement: str, w: float, h: float, host: tuple, margin: float) -> tuple:
    hxmin, hymin, hxmax, hymax = host
    cx = (hxmin + hxmax) * 0.5
    cy = (hymin + hymax) * 0.5
    left, right = hxmin + margin, hxmax - margin - w
    bottom, top = hymin + margin, hymax - margin - h
    if placement == beats.PLACE_CENTER:
        return cx - w * 0.5, cy - h * 0.5
    if placement == beats.PLACE_TOP_LEFT:
        return left, top
    if placement == beats.PLACE_TOP_RIGHT:
        return right, top
    if placement == beats.PLACE_BOTTOM_RIGHT:
        return right, bottom
    if placement == beats.PLACE_BOTTOM_CENTER:
        return cx - w * 0.5, bottom
    return left, bottom  # PLACE_BOTTOM_LEFT and anything unknown


def _intersects(a: tuple, b: tuple) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def layout_from_card_rect(card_rect: tuple, ui_scale: float) -> CardLayout:
    """Video, inner controls strip and buttons for a given card rect.

    Pure: the session feeds it the animated rect every tick, and
    ``compute_card_layout`` builds its target through it, so both agree."""
    s = max(0.1, float(ui_scale))
    xmin, ymin, xmax, ymax = (float(v) for v in card_rect)
    pad = config.CARD_PAD * s
    video = (xmin + pad, ymin + pad, xmax - pad, ymax - pad)
    video_h = max(0.0, video[3] - video[1])
    ctrl_h = min(config.CARD_CONTROLS_H * s, video_h)
    controls = (video[0], video[1], video[2], video[1] + ctrl_h)

    px = config.CONTROL_FONT_PX * s
    gap = config.CONTROL_GAP * s
    bpad = BUTTON_PAD_X * s
    widths = {
        "pause": _widest((config.CONTROL_PAUSE, config.CONTROL_RESUME), px),
        "speed": _widest([format_rate(r) for r in config.SPEED_OPTIONS], px),
        "skip": _text_width(config.CONTROL_SKIP, px),
        "exit": _text_width(config.CONTROL_EXIT, px),
    }
    buttons = {}
    cursor_x = controls[0] + gap * 0.5
    for name in ("pause", "speed"):
        w = widths[name] + 2 * bpad
        buttons[name] = (cursor_x, controls[1], cursor_x + w, controls[3])
        cursor_x += w + gap
    cursor_x = controls[2] - gap * 0.5
    for name in ("exit", "skip"):
        w = widths[name] + 2 * bpad
        buttons[name] = (cursor_x - w, controls[1], cursor_x, controls[3])
        cursor_x -= w + gap
    return CardLayout(card=(xmin, ymin, xmax, ymax), video=video,
                      controls=controls, buttons=buttons)


def compute_card_layout(variant: str, placement: str, host_rect: tuple,
                        ui_scale: float, island_rect: Optional[tuple] = None) -> CardLayout:
    """Target card rect for a beat (video + ``CARD_PAD``), in window px."""
    s = max(0.1, float(ui_scale))
    hxmin, hymin, hxmax, hymax = host_rect
    host_w = max(0.0, hxmax - hxmin)
    host_h = max(0.0, hymax - hymin)
    pad = config.CARD_PAD * s
    # Margins give way before the card does on a small host.
    margin = min(config.CARD_MARGIN * s, host_w * 0.05, host_h * 0.05)

    video_w = float(config.CARD_VARIANTS.get(variant, config.CARD_VARIANTS["half"])) * s
    max_video_w = host_w - 2 * margin - 2 * pad
    max_video_h = host_h - 2 * margin - 2 * pad
    video_w = min(video_w, max_video_w, max_video_h * config.CARD_ASPECT)
    video_w = max(video_w, min(MIN_VIDEO_W * s, max_video_w))
    video_h = video_w / config.CARD_ASPECT

    card_w = video_w + 2 * pad
    card_h = video_h + 2 * pad
    x, y = _place(placement, card_w, card_h, host_rect, margin)

    if island_rect is not None and placement in (
        beats.PLACE_BOTTOM_LEFT, beats.PLACE_BOTTOM_RIGHT, beats.PLACE_BOTTOM_CENTER,
    ):
        if _intersects((x, y, x + card_w, y + card_h), island_rect):
            y = island_rect[3] + ISLAND_GAP * s

    # Never leave the host.
    x = min(max(x, hxmin), max(hxmin, hxmax - card_w))
    y = min(max(y, hymin), max(hymin, hymax - card_h))
    return layout_from_card_rect((x, y, x + card_w, y + card_h), s)


# -- painters ---------------------------------------------------------------

def _draw_video(texture, rect: tuple, alpha: float) -> None:
    xmin, ymin, xmax, ymax = rect
    if texture is None:
        draw_rect(xmin, ymin, xmax - xmin, ymax - ymin,
                  _with_alpha(VIDEO_PLACEHOLDER, alpha))
        return
    try:
        from .. import video
        video.draw_textured_quad(texture, xmin, ymin, xmax - xmin, ymax - ymin)
        if alpha < 1.0:
            # The IMAGE shader has no colour uniform: fade the frame toward
            # the card background instead.
            r, g, b, _a = config.CARD_BG
            draw_rect(xmin, ymin, xmax - xmin, ymax - ymin, (r, g, b, 1.0 - alpha))
    except Exception as exc:
        logger.debug("Tour video quad failed, drawing placeholder: %s", exc)
        draw_rect(xmin, ymin, xmax - xmin, ymax - ymin,
                  _with_alpha(VIDEO_PLACEHOLDER, alpha))


def _draw_caption(video_rect: tuple, caption: str, px: float, s: float, alpha: float) -> None:
    """Small pill over the video's top-left naming the part of the tour."""
    if not caption:
        return
    pad_x, pad_y, inset = 10 * s, 5 * s, 10 * s
    tw = _text_width(caption, px)
    w, h = tw + 2 * pad_x, px + 2 * pad_y
    xmin = video_rect[0] + inset
    ymax = video_rect[3] - inset
    draw_rounded_rect(xmin, ymax - h, w, h, h * 0.5,
                      _with_alpha(config.HINT_BG, alpha * 0.9))
    draw_text_centered((xmin, ymax - h, xmin + w, ymax), caption, px,
                       _with_alpha(config.HINT_TEXT, alpha))


def _draw_controls_film(controls: tuple, alpha: float) -> None:
    """Bottom-up film under the labels: stacked bands fake a gradient."""
    xmin, ymin, xmax, ymax = controls
    w, h = xmax - xmin, ymax - ymin
    bands = max(1, int(config.CONTROLS_FILM_BANDS))
    band_h = h / bands
    for i in range(bands):
        # Densest band at the bottom; each band adds on top of the ones
        # below it, so the visible alpha ramps toward the video's edge.
        draw_rect(xmin, ymin + i * band_h, w, h - i * band_h,
                  _with_alpha(config.CONTROLS_FILM, alpha / bands))


def _draw_controls(layout: CardLayout, paused: bool, rate: float, px: float,
                   hover: Optional[str], alpha: float) -> None:
    if alpha <= 0.0:
        return
    _draw_controls_film(layout.controls, alpha)
    labels = {
        "pause": config.CONTROL_RESUME if paused else config.CONTROL_PAUSE,
        "speed": format_rate(rate),
        "skip": config.CONTROL_SKIP,
        "exit": config.CONTROL_EXIT,
    }
    for name in BUTTON_ORDER:
        rect = layout.buttons.get(name)
        if rect is None:
            continue
        color = CONTROL_TEXT_HOVER if hover == name else config.CONTROL_TEXT
        draw_text_centered(rect, labels[name], px, _with_alpha(color, alpha))


def _draw_gate_caption(layout: CardLayout, px: float, s: float,
                       alpha: float, controls_alpha: float) -> None:
    """Dim "Your turn" at the video's bottom-right; slides left of the
    Next button as the controls reveal so the two never overlap."""
    cw = _text_width(GATE_CAPTION, px)
    hidden_right = layout.video[2] - GATE_CAPTION_INSET * s
    skip = layout.buttons.get("skip")
    shown_right = (skip[0] - config.CONTROL_GAP * s) if skip else hidden_right
    # Snap, never interpolate: a half-revealed strip would put the caption
    # halfway across the skip button.
    right = shown_right if controls_alpha > 0.02 else hidden_right
    speed = layout.buttons.get("speed")
    left_limit = (speed[2] + config.CONTROL_GAP * s) if speed else layout.video[0]
    if right - cw < left_limit:
        return
    a = alpha * max(config.GATE_CAPTION_ALPHA_FLOOR, controls_alpha)
    draw_text_centered((right - cw, layout.controls[1], right, layout.controls[3]),
                       GATE_CAPTION, px, _with_alpha(config.CONTROL_TEXT_DIM, a))


def _draw_paused_glyph(video_rect: tuple, s: float, alpha: float) -> None:
    """Translucent disc with a play triangle centred over the video."""
    cx = (video_rect[0] + video_rect[2]) * 0.5
    cy = (video_rect[1] + video_rect[3]) * 0.5
    r = config.PAUSED_DISC_RADIUS * s
    draw_circle(cx, cy, r, _with_alpha(config.PAUSED_DISC, alpha), segments=32)
    t = r * 0.42
    verts = ((cx - t * 0.8, cy - t), (cx - t * 0.8, cy + t), (cx + t, cy))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=((0, 1, 2),))
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", _with_alpha(config.PAUSED_GLYPH, alpha))
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def draw_card(layout: CardLayout, texture, progress: float, paused: bool, rate: float,
              alpha: float = 1.0, ui_scale: float = 1.0,
              gate_seconds_left: Optional[float] = None,
              hover: Optional[str] = None, caption: str = "",
              controls_alpha: float = 0.0, gate_film: float = 0.0) -> None:
    """Paint the card: background, video, gate film, caption, controls strip
    (scaled by ``controls_alpha``), progress hairline, gate caption, pause
    glyph. ``gate_film`` (0..1, eased by the session) darkens the held frame
    by ``GATE_FILM_ALPHA`` while a gate waits, so the pause reads as a
    deliberate freeze-frame rather than a stall."""
    if alpha <= 0.0:
        return
    try:
        s = max(0.1, float(ui_scale))
        ca = max(0.0, min(1.0, float(controls_alpha)))
        xmin, ymin, xmax, ymax = layout.card
        draw_rounded_rect(xmin, ymin, xmax - xmin, ymax - ymin, config.CARD_RADIUS * s,
                          _with_alpha(config.CARD_BG, alpha))

        _draw_video(texture, layout.video, alpha)
        film = max(0.0, min(1.0, float(gate_film)))
        if film > 0.0:
            vx0, vy0, vx1, vy1 = layout.video
            draw_rect(vx0, vy0, vx1 - vx0, vy1 - vy0,
                      _with_alpha(GATE_FILM, alpha * config.GATE_FILM_ALPHA * film))
        px = config.CONTROL_FONT_PX * s
        _draw_caption(layout.video, caption, px, s, alpha)
        _draw_controls(layout, paused, rate, px, hover, alpha * ca)

        vxmin, vymin, vxmax, _vymax = layout.video
        bar_h = config.CARD_PROGRESS_H * s
        vw = vxmax - vxmin
        draw_rect(vxmin, vymin, vw, bar_h, _with_alpha(config.CARD_PROGRESS_BG, alpha))
        p = max(0.0, min(1.0, float(progress)))
        if p > 0.0:
            draw_rect(vxmin, vymin, vw * p, bar_h, _with_alpha(config.CARD_PROGRESS_FG, alpha))

        if gate_seconds_left is not None:
            _draw_gate_caption(layout, px, s, alpha, ca)
        if paused:
            _draw_paused_glyph(layout.video, s, alpha)
    except Exception as exc:
        logger.debug("Tour card draw failed: %s", exc)


def caption_under_rect(layout: CardLayout, text: str, ui_scale: float = 1.0) -> tuple:
    """Where ``draw_caption_under`` puts its pill: centred on the card,
    ``CAPTION_UNDER_GAP`` below ``layout.card``. Pure, for the tests."""
    s = max(0.1, float(ui_scale))
    px = config.HINT_FONT_PX * s
    w = _text_width(text, px) + 2 * CAPTION_PAD_X * s
    h = px + 2 * CAPTION_PAD_Y * s
    cx = (layout.card[0] + layout.card[2]) * 0.5
    ymax = layout.card[1] - config.CAPTION_UNDER_GAP * s
    return (cx - w * 0.5, ymax - h, cx + w * 0.5, ymax)


def draw_caption_under(layout: CardLayout, text: str, ui_scale: float = 1.0,
                       alpha: float = 1.0) -> Optional[tuple]:
    """A hint-style pill (``HINT_BG`` / ``HINT_TEXT``) centred under the
    card; returns its rect, or None when nothing was drawn."""
    if not text or alpha <= 0.0:
        return None
    try:
        s = max(0.1, float(ui_scale))
        rect = caption_under_rect(layout, text, s)
        xmin, ymin, xmax, ymax = rect
        w, h = xmax - xmin, ymax - ymin
        draw_rounded_rect(xmin, ymin, w, h, h * 0.5, _with_alpha(config.HINT_BG, alpha))
        draw_text_centered(rect, text, config.HINT_FONT_PX * s,
                           _with_alpha(config.HINT_TEXT, alpha))
        return rect
    except Exception as exc:
        logger.debug("Tour caption draw failed: %s", exc)
        return None


# -- hit testing / QA -------------------------------------------------------

def _inside(rect: tuple, x: float, y: float) -> bool:
    return rect[0] <= x < rect[2] and rect[1] <= y < rect[3]


def hit_test(layout: CardLayout, x: float, y: float) -> Optional[str]:
    """``"pause"``, ``"speed"``, ``"skip"``, ``"exit"``, ``"card"`` or None.
    Buttons hit whether or not the strip is currently visible."""
    for name in BUTTON_ORDER:
        rect = layout.buttons.get(name)
        if rect is not None and _inside(rect, x, y):
            return name
    if _inside(layout.card, x, y):
        return "card"
    return None


def qa_targets(layout: Optional[CardLayout],
               exit_layout: Optional[ExitConfirmLayout] = None) -> list:
    """Named rects for the QA harness: ``tour_<button>`` and
    ``tour_confirm_<button>``."""
    targets = []
    if layout is not None:
        for name in BUTTON_ORDER:
            rect = layout.buttons.get(name)
            if rect is not None:
                targets.append({"name": f"tour_{name}", "rect": [float(v) for v in rect]})
    if exit_layout is not None:
        for name in ("continue", "exit"):
            rect = exit_layout.buttons.get(name)
            if rect is not None:
                targets.append({"name": f"tour_confirm_{name}",
                                "rect": [float(v) for v in rect]})
    return targets
