# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Card — GPU Renderer

Paints the Apple-Freeform-style card given a pre-computed
:class:`CardLayout`. Reuses the rounded-rect / circle / blf
primitives from the notification toast renderer.

Layout (top → bottom):

    ┌────────────────────────────────┐
    │           ▣ icon slot          │
    │        Title (centred)         │
    │      Body line 1 (centred)     │
    │      Body line 2 (centred)     │
    │           • • ● • •            │  ← step dots
    │  Skip          [ Continue ]    │  ← buttons row
    └────────────────────────────────┘
"""

import math

import blf
import gpu
from gpu_extras.batch import batch_for_shader

from mixar.modules.common.notifications.toast_renderer_shapes import (
    draw_circle,
    draw_rect,
    draw_rounded_rect,
)
from mixar.modules.onboarding.constants import (
    CARD_BG_COLOR,
    CARD_BODY_COLOR,
    CARD_BORDER_COLOR,
    CARD_BORDER_WIDTH,
    CARD_BTN_PRIMARY_BG,
    CARD_BTN_PRIMARY_BG_HOVER,
    CARD_BTN_PRIMARY_BG_HOVER_TOP,
    CARD_BTN_PRIMARY_BG_TOP,
    CARD_BTN_ALT_BG,
    CARD_BTN_ALT_BG_HOVER,
    CARD_BTN_ALT_TEXT,
    CARD_BTN_PRIMARY_TEXT,
    CARD_BTN_SKIP_TEXT,
    CARD_BTN_SKIP_TEXT_HOVER,
    CARD_DOT_ACTIVE,
    CARD_DOT_ACTIVE_PILL_WIDTH_RATIO,
    CARD_DOT_INACTIVE,
    CARD_TITLE_COLOR,
    CARD_TITLE_SHADOW_COLOR,
    CARD_TITLE_SHADOW_OFFSET,
    OVERLAY_HINT_BOTTOM_GAP,
    OVERLAY_HINT_COLOR,
    OVERLAY_HINT_FONT,
    OVERLAY_HINT_TEXT,
)

from . import icons

_FONT_ID = 0


def _draw_text(x: int, y: int, text: str, size: int, color: tuple) -> None:
    blf.size(_FONT_ID, size)
    blf.color(_FONT_ID, *color)
    blf.position(_FONT_ID, x, y, 0)
    blf.draw(_FONT_ID, text)


def _draw_text_with_shadow(x: int, y: int, text: str, size: int,
                            color: tuple, shadow_color: tuple,
                            shadow_offset: tuple) -> None:
    """Draw ``text`` once at an offset (the shadow), then on top in
    ``color``. Cheap polish that gives titles a subtle depth without
    needing a separate bold-weight font file."""
    sx, sy = shadow_offset
    _draw_text(x + sx, y + sy, text, size, shadow_color)
    _draw_text(x, y, text, size, color)


def _draw_text_double(x: int, y: int, text: str, size: int,
                       color: tuple) -> None:
    """A faux-bold draw — paint the same glyphs twice with a 1-px x
    offset so strokes thicken without needing a bold weight."""
    _draw_text(x, y, text, size, color)
    _draw_text(x + 1, y, text, size, color)


def _draw_rounded_rect_gradient(x: float, y: float, w: float, h: float,
                                 radius: float, top_color: tuple,
                                 bottom_color: tuple,
                                 segments: int = 8) -> None:
    """Filled rounded rect with a vertical gradient (top → bottom).

    Uses ``SMOOTH_COLOR`` so each vertex carries its own colour and
    the GPU interpolates across the surface. We assign ``top_color``
    to vertices in the upper half of the shape and ``bottom_color``
    to the lower half; the fan center sits in between.
    """
    r = min(radius, w * 0.5, h * 0.5)
    if r < 1.0:
        # Degenerate — fall back to two-rect approximation.
        draw_rect(x, y, w, h * 0.5, bottom_color)
        draw_rect(x, y + h * 0.5, w, h * 0.5, top_color)
        return

    cx = x + w * 0.5
    cy = y + h * 0.5
    mid_color = tuple(
        (top_color[i] + bottom_color[i]) * 0.5 for i in range(4)
    )

    corners = (
        (x + r,     y + r),         # bottom-left
        (x + w - r, y + r),         # bottom-right
        (x + w - r, y + h - r),     # top-right
        (x + r,     y + h - r),     # top-left
    )
    start_angles = (math.pi, 1.5 * math.pi, 0.0, 0.5 * math.pi)

    verts = [(cx, cy)]
    colors = [mid_color]
    for (ccx, ccy), start in zip(corners, start_angles):
        for i in range(segments + 1):
            angle = start + (math.pi * 0.5) * (i / segments)
            vx = ccx + r * math.cos(angle)
            vy = ccy + r * math.sin(angle)
            verts.append((vx, vy))
            # Linear vertical blend across the rect.
            t = (vy - y) / max(h, 1.0)
            t = max(0.0, min(1.0, t))
            color = tuple(
                bottom_color[i] * (1.0 - t) + top_color[i] * t
                for i in range(4)
            )
            colors.append(color)

    indices = []
    n = len(verts)
    for i in range(1, n - 1):
        indices.append((0, i, i + 1))
    indices.append((0, n - 1, 1))

    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    batch = batch_for_shader(shader, 'TRIS',
                             {"pos": verts, "color": colors},
                             indices=indices)
    gpu.state.blend_set('ALPHA')
    shader.bind()
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def _draw_border(x: int, y: int, w: int, h: int) -> None:
    """Hairline border drawn as four 1-px rects framing the card."""
    bw = max(1, CARD_BORDER_WIDTH)
    color = CARD_BORDER_COLOR
    draw_rect(x, y + h - bw, w, bw, color)
    draw_rect(x, y, w, bw, color)
    draw_rect(x, y, bw, h, color)
    draw_rect(x + w - bw, y, bw, h, color)


def _draw_dots(layout, x_offset: int = 0, y_offset: int = 0) -> None:
    """Apple-style step indicator with per-call render offset."""
    if not layout.dots_centers or layout.dot_radius <= 0:
        return

    pill_w_ratio = CARD_DOT_ACTIVE_PILL_WIDTH_RATIO
    pill_w = int(round(layout.dot_radius * 2 * pill_w_ratio))
    pill_h = layout.dot_radius * 2
    pill_radius = layout.dot_radius

    for i, (cx, cy) in enumerate(layout.dots_centers, start=1):
        cx_o = cx + x_offset
        cy_o = cy + y_offset
        active = (i == layout.dots_current)
        if active:
            draw_rounded_rect(
                cx_o - pill_w // 2, cy_o - pill_h // 2,
                pill_w, pill_h, pill_radius, CARD_DOT_ACTIVE,
            )
        else:
            draw_circle(cx_o, cy_o, layout.dot_radius,
                        CARD_DOT_INACTIVE, segments=18)


def _draw_primary_button(rect: tuple, label: str, font_size: int,
                          radius: int, hover: bool) -> None:
    bx, by, bw, bh = rect
    if hover:
        top = CARD_BTN_PRIMARY_BG_HOVER_TOP
        bottom = CARD_BTN_PRIMARY_BG_HOVER
    else:
        top = CARD_BTN_PRIMARY_BG_TOP
        bottom = CARD_BTN_PRIMARY_BG
    _draw_rounded_rect_gradient(bx, by, bw, bh, radius, top, bottom)

    blf.size(_FONT_ID, font_size)
    tw, th = blf.dimensions(_FONT_ID, label)
    label_x = bx + (bw - tw) * 0.5
    label_y = by + (bh - th) * 0.5
    # Faux-bold the button label so it pops on the green pill.
    _draw_text_double(int(label_x), int(label_y), label,
                      font_size, CARD_BTN_PRIMARY_TEXT)


def _draw_alt_button(rect: tuple, label: str, font_size: int,
                      radius: int, hover: bool) -> None:
    """Muted counterpart to the primary pill — flat fill, no gradient,
    so the green Continue button still wins the eye."""
    bx, by, bw, bh = rect
    draw_rounded_rect(
        bx, by, bw, bh, radius,
        CARD_BTN_ALT_BG_HOVER if hover else CARD_BTN_ALT_BG,
    )

    blf.size(_FONT_ID, font_size)
    tw, th = blf.dimensions(_FONT_ID, label)
    _draw_text(
        int(bx + (bw - tw) * 0.5), int(by + (bh - th) * 0.5),
        label, font_size, CARD_BTN_ALT_TEXT,
    )


def _draw_skip_link(rect: tuple, label: str, font_size: int,
                     hover: bool) -> None:
    sx, sy, _sw, _sh = rect
    color = CARD_BTN_SKIP_TEXT_HOVER if hover else CARD_BTN_SKIP_TEXT
    _draw_text(int(sx), int(sy), label, font_size, color)
    if hover:
        blf.size(_FONT_ID, font_size)
        tw, _ = blf.dimensions(_FONT_ID, label)
        draw_rect(int(sx), int(sy) - 2, int(tw), 1,
                  (*color[:3], color[3] * 0.6))


def draw_dismiss_hint(region_w: int, region_h: int) -> None:
    """Paint a small centred hint near the bottom of the host region
    telling the user the tour is escapable. Drawn on the dim film
    (not the card) so it never affects card geometry/placement."""
    blf.size(_FONT_ID, OVERLAY_HINT_FONT)
    tw, _th = blf.dimensions(_FONT_ID, OVERLAY_HINT_TEXT)
    x = int((region_w - tw) * 0.5)
    y = int(OVERLAY_HINT_BOTTOM_GAP)
    _draw_text(x, y, OVERLAY_HINT_TEXT, OVERLAY_HINT_FONT, OVERLAY_HINT_COLOR)


def draw_card(layout, hover_target: str,
              x_offset: int = 0, y_offset: int = 0) -> None:
    """Paint the card. ``hover_target`` is one of ``"primary"``,
    ``"skip"``, ``"card"``, or ``None``.

    ``x_offset`` / ``y_offset`` shift every primitive draw call. Used
    by multi-region drawing for ``CARD_POS_WINDOW_CENTER`` — the
    layout stores positions in window coords and each region's
    callback passes ``(-region.x, -region.y)`` so the same card spans
    multiple areas without per-region clipping.

    All visual sizes (corner radius, font sizes, button radius) come
    from the layout so per-step scale takes effect uniformly.
    """
    ox, oy = x_offset, y_offset

    # Card background + hairline border.
    draw_rounded_rect(
        layout.x + ox, layout.y + oy, layout.w, layout.h,
        layout.corner_radius, CARD_BG_COLOR,
    )
    _draw_border(layout.x + ox, layout.y + oy, layout.w, layout.h)

    # Icon slot at the top.
    if layout.icon_id and layout.icon_rect[2] > 0:
        ix, iy, isize, _ = layout.icon_rect
        icons.draw_icon(layout.icon_id, ix + ox, iy + oy,
                        isize, layout.scale)

    # Title with soft shadow + faux-bold pass.
    if layout.title_text:
        tx, ty = layout.title_baseline
        sx, sy = CARD_TITLE_SHADOW_OFFSET
        _draw_text(int(tx + ox + sx), int(ty + oy + sy), layout.title_text,
                   layout.title_font, CARD_TITLE_SHADOW_COLOR)
        _draw_text_double(int(tx + ox), int(ty + oy), layout.title_text,
                          layout.title_font, CARD_TITLE_COLOR)

    # Body lines (centred per-line in compute_layout).
    for line, (lx, ly) in zip(layout.body_lines, layout.body_baselines):
        _draw_text(int(lx + ox), int(ly + oy), line,
                   layout.body_font, CARD_BODY_COLOR)

    # Step dots.
    _draw_dots(layout, ox, oy)

    # Primary "Continue" button.
    bx, by, bw, bh = layout.primary_rect
    _draw_primary_button(
        (bx + ox, by + oy, bw, bh), layout.primary_label,
        layout.button_font, layout.primary_btn_radius,
        hover=(hover_target == "primary"),
    )

    # Secondary button, left of the primary one.
    if layout.alt_visible:
        ax, ay, aw, ah = layout.alt_rect
        _draw_alt_button(
            (ax + ox, ay + oy, aw, ah), layout.alt_label,
            layout.button_font, layout.primary_btn_radius,
            hover=(hover_target == "alt"),
        )

    # Skip link.
    if layout.skip_visible:
        sx, sy, sw, sh = layout.skip_rect
        _draw_skip_link(
            (sx + ox, sy + oy, sw, sh), layout.skip_label,
            layout.button_font,
            hover=(hover_target == "skip"),
        )

    # Back link — same discreet styling as Skip.
    if layout.back_visible:
        bx, by, bw, bh = layout.back_rect
        _draw_skip_link(
            (bx + ox, by + oy, bw, bh), layout.back_label,
            layout.button_font,
            hover=(hover_target == "back"),
        )
