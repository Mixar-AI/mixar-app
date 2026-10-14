# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the video card.

The card is the video and nothing else: a dark rounded background only
``config.CARD_PAD`` larger than the frame, a hairline progress bar along the
frame's bottom edge and the caption pill. The player controls live in
``card_controls``: Back / Play-Pause / Next as a cluster in the middle of
the video, drawn multiplied by ``controls_alpha`` (the session eases that
toward 1 on hover / pause / exit dialog), and a quiet
Skip tour pill in the top-right corner that never fully hides. Hit testing
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

from mixar.config.logging_config import get_logger
from mixar.modules.common.notifications.toast_renderer_shapes import (
    draw_rect,
    draw_rounded_rect,
)

from .. import beats, config
from .card_controls import (
    BUTTON_ORDER,
    button_rects,
    controls_rect,
    draw_controls,
    draw_gate_caption,
    draw_skip_tour,
    with_alpha as _with_alpha,
)
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
    "draw_caption_under", "caption_under_rect", "caption_rect", "fit_text",
    "hit_test", "qa_targets",
    "ExitConfirmLayout", "compute_exit_confirm_layout", "draw_exit_confirm",
    "hit_test_exit_confirm",
)

ISLAND_GAP = 12.0             # logical px between the island and a lifted card
MIN_VIDEO_W = 96.0
VIDEO_PLACEHOLDER = (0.03, 0.03, 0.04, 1.0)
GATE_FILM = (0.0, 0.0, 0.0, 1.0)
CAPTION_PAD_X = 12.0          # logical px, the hint pill's padding
CAPTION_PAD_Y = 7.0


@dataclass
class CardLayout:
    card: tuple
    video: tuple
    controls: tuple               # the transport cluster, centred on ``video``
    buttons: dict = field(default_factory=dict)


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
    """Video, transport cluster and buttons for a given card rect.

    Pure: the session feeds it the animated rect every tick, and
    ``compute_card_layout`` builds its target through it, so both agree."""
    s = max(0.1, float(ui_scale))
    xmin, ymin, xmax, ymax = (float(v) for v in card_rect)
    pad = config.CARD_PAD * s
    video = (xmin + pad, ymin + pad, xmax - pad, ymax - pad)
    return CardLayout(card=(xmin, ymin, xmax, ymax), video=video,
                      controls=controls_rect(video, s), buttons=button_rects(video, s))


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


CAPTION_PAD_X_OVER = 10.0     # logical px, the act caption pill over the video
CAPTION_PAD_Y_OVER = 5.0
CAPTION_INSET = 10.0
CAPTION_SKIP_GAP = 8.0        # clear air between the caption and Skip tour
_ELLIPSIS = "\u2026"


def fit_text(text: str, px: float, max_w: float) -> str:
    """``text`` shortened with an ellipsis so it measures at most ``max_w``
    at ``px``. Pure; the whole text when it already fits."""
    if not text or _text_width(text, px) <= max_w:
        return text
    if _text_width(_ELLIPSIS, px) > max_w:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _text_width(text[:mid].rstrip() + _ELLIPSIS, px) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + _ELLIPSIS


def caption_rect(video_rect: tuple, caption: str, px: float, s: float,
                 clear_right: Optional[float] = None) -> tuple:
    """The act caption pill over the video's top-left: ``(rect, text)``.
    ``text`` is the caption shortened so the pill's right edge stays
    ``CAPTION_SKIP_GAP`` left of ``clear_right`` (the Skip tour pill on a
    narrow card or a long translation). Pure, for the tests."""
    pad_x, pad_y, inset = CAPTION_PAD_X_OVER * s, CAPTION_PAD_Y_OVER * s, CAPTION_INSET * s
    xmin = video_rect[0] + inset
    ymax = video_rect[3] - inset
    text = caption or ""
    if text and clear_right is not None:
        max_w = clear_right - CAPTION_SKIP_GAP * s - xmin - 2 * pad_x
        text = fit_text(text, px, max_w) if max_w > 0 else ""
    w, h = _text_width(text, px) + 2 * pad_x, px + 2 * pad_y
    return (xmin, ymax - h, xmin + w, ymax), text


def _draw_caption(video_rect: tuple, caption: str, px: float, s: float, alpha: float,
                  clear_right: Optional[float] = None) -> None:
    """Small pill over the video's top-left naming the part of the tour."""
    rect, text = caption_rect(video_rect, caption, px, s, clear_right)
    if not text:
        return
    xmin, ymin, xmax, ymax = rect
    h = ymax - ymin
    draw_rounded_rect(xmin, ymin, xmax - xmin, h, h * 0.5,
                      _with_alpha(config.HINT_BG, alpha * 0.9))
    draw_text_centered(rect, text, px, _with_alpha(config.HINT_TEXT, alpha))


def _draw_subtitle(layout: CardLayout, text: str, px: float, s: float, alpha: float) -> None:
    """Subtitle band inside the bottom of the video: centred lines on a
    translucent film, wrapped to the video width, on the video's bottom
    edge below the centred transport."""
    if not text:
        return
    from .. import srt
    vx0, vy0, vx1, _vy1 = layout.video
    pad_x, pad_y, gap = 12 * s, 5 * s, 6 * s
    max_w = (vx1 - vx0) - 2 * pad_x - 2 * gap
    lines = srt.wrap(text, max_w, lambda t: _text_width(t, px))
    # Translations can expand. Fit them without silently discarding the
    # end of the spoken sentence; keep the full cue at the minimum size.
    while len(lines) > config.SUBTITLE_MAX_LINES and px > 10 * s:
        px -= s
        lines = srt.wrap(text, max_w, lambda t: _text_width(t, px))
    line_h = px * 1.3
    w = max(_text_width(ln, px) for ln in lines) + 2 * pad_x
    h = line_h * len(lines) + 2 * pad_y
    ymin = vy0 + gap
    xmin = (vx0 + vx1) * 0.5 - w * 0.5
    draw_rounded_rect(xmin, ymin, w, h, 4 * s, _with_alpha(config.SUBTITLE_BG, alpha))
    for i, ln in enumerate(lines):
        top = ymin + h - pad_y - i * line_h
        draw_text_centered((xmin, top - line_h, xmin + w, top), ln, px,
                           _with_alpha(config.SUBTITLE_TEXT, alpha))


def _draw_loading(video_rect: tuple, text: str, px: float, s: float, alpha: float) -> None:
    """A film over the video with the loading line centred: shown while a
    language pack's first part is fetched, or a later part has not arrived
    when its act starts."""
    vx0, vy0, vx1, vy1 = video_rect
    draw_rect(vx0, vy0, vx1 - vx0, vy1 - vy0, _with_alpha(GATE_FILM, alpha * 0.55))
    pad_x, pad_y = 14 * s, 7 * s
    w, h = _text_width(text, px) + 2 * pad_x, px + 2 * pad_y
    cx, cy = (vx0 + vx1) * 0.5, (vy0 + vy1) * 0.5
    draw_rounded_rect(cx - w * 0.5, cy - h * 0.5, w, h, h * 0.5,
                      _with_alpha(config.HINT_BG, alpha * 0.9))
    draw_text_centered((cx - w * 0.5, cy - h * 0.5, cx + w * 0.5, cy + h * 0.5), text, px,
                       _with_alpha(config.HINT_TEXT, alpha))


def draw_card(layout: CardLayout, texture, progress: float, paused: bool,
              alpha: float = 1.0, ui_scale: float = 1.0,
              gate_seconds_left: Optional[float] = None,
              hover: Optional[str] = None, caption: str = "",
              controls_alpha: float = 0.0, gate_film: float = 0.0,
              subtitle: str = "", loading_text: str = "") -> None:
    """Paint the card: background, video, gate film, the centred controls
    and their scrim (scaled by ``controls_alpha``; the centre button is the
    only play/pause glyph), caption, Skip tour pill, subtitle band,
    progress hairline, gate caption. ``gate_film`` (0..1, eased by the session) darkens the held frame
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
        # The controls' scrim goes under the caption and Skip tour pills.
        draw_controls(layout, paused, s, hover, alpha * ca)
        _draw_caption(layout.video, caption, px, s, alpha,
                      clear_right=layout.buttons["exit"][0])
        draw_skip_tour(layout, s, hover, alpha, ca)
        _draw_subtitle(layout, subtitle, config.SUBTITLE_FONT_PX * s, s, alpha)
        if loading_text:
            _draw_loading(layout.video, loading_text, config.SUBTITLE_FONT_PX * s, s, alpha)

        vxmin, vymin, vxmax, _vymax = layout.video
        bar_h = (config.CARD_PROGRESS_H
                 + (config.CARD_PROGRESS_H_REVEALED - config.CARD_PROGRESS_H) * ca) * s
        vw = vxmax - vxmin
        draw_rect(vxmin, vymin, vw, bar_h, _with_alpha(config.CARD_PROGRESS_BG, alpha))
        p = max(0.0, min(1.0, float(progress)))
        if p > 0.0:
            draw_rect(vxmin, vymin, vw * p, bar_h, _with_alpha(config.CARD_PROGRESS_FG, alpha))

        if gate_seconds_left is not None:
            draw_gate_caption(layout, s, alpha, ca)
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
    """``"back"``, ``"pause"``, ``"skip"``, ``"exit"``, ``"card"`` or None.
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
