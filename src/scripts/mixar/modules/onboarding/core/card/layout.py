# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Card — Layout & Hit Testing

Measures a card's geometry given step content, picks an anchor point
inside the host area, and exposes a hit test for the modal operator.

All coords are **region-relative** (origin = bottom-left of the host
area's WINDOW region), since that's the coord system the GPU draw
callback runs in. The modal operator translates window-space mouse
events to region space using the host region's ``(x, y)`` origin.
"""

from dataclasses import dataclass, field

from mixar.modules.onboarding.core.card.text_utils import (
    FONT_ID as _FONT_ID,
    measure_text_h as _measure_text_h,
    measure_text_w as _measure_text_w,
    wrap_line as _wrap_line,
)
from mixar.modules.onboarding.constants import (
    CARD_AREA_MARGIN,
    CARD_BODY_DOTS_GAP,
    CARD_BODY_LINE_SPACING,
    CARD_BTN_HEIGHT,
    CARD_BTN_PADDING_X,
    CARD_BTN_RADIUS,
    CARD_CHAT_INPUT_GUTTER,
    CARD_CORNER_RADIUS,
    CARD_DOTS_BUTTONS_GAP,
    CARD_DOT_GAP,
    CARD_DOT_RADIUS,
    CARD_FONT_BODY,
    CARD_FONT_BUTTON,
    CARD_FONT_PROGRESS,
    CARD_FONT_TITLE,
    CARD_ICON_BOTTOM_GAP,
    CARD_ICON_SIZE,
    CARD_ICON_TOP_GAP,
    CARD_MIN_HEIGHT,
    CARD_PADDING_X,
    CARD_PADDING_Y,
    CARD_BUBBLE_GAP,
    CARD_POS_ABOVE_INPUT,
    CARD_POS_AREA_CENTER,
    CARD_POS_NEAR_BUBBLE,
    CARD_POS_SIDEBAR_ADJACENT,
    CARD_POS_TOP_LEFT,
    CARD_POS_TOP_RIGHT,
    CARD_POS_WINDOW_CENTER,
    CARD_SIDEBAR_WIDTH,
    CARD_SKIP_GAP,
    CARD_TITLE_BODY_GAP,
    CARD_WIDTH,
)

def _ui_scale_factor() -> float:
    """Best-effort approximation of Blender's ``UI_SCALE_FAC``.

    Combines the user's ui_scale preference (default 1.0) with the
    DPI ratio (default 72 → 1.0; retina ≈ 144 → 2.0). Falls back to
    1.0 if preferences aren't available.
    """
    try:
        import bpy
        sys = bpy.context.preferences.system
        return float(sys.ui_scale) * max(1.0, float(sys.dpi) / 72.0)
    except Exception:
        return 1.0


@dataclass
class CardLayout:
    """Geometry of a rendered card in region-relative coords."""
    # Outer card rect.
    x: int = 0
    y: int = 0
    w: int = CARD_WIDTH
    h: int = CARD_MIN_HEIGHT

    # Per-step rendering values, scaled from the base constants by
    # ``scale`` so the renderer doesn't have to know about scale.
    corner_radius: int = 0
    title_font: int = 0
    body_font: int = 0
    button_font: int = 0
    progress_font: int = 0
    scale: float = 1.0

    # Icon slot (Apple-style top-of-card glyph).
    icon_id: str = ""
    icon_rect: tuple = (0, 0, 0, 0)  # (x, y, size, size)

    # Title (centred, bold) and body (centred, multi-line).
    title_text: str = ""
    title_baseline: tuple = (0, 0)

    body_lines: tuple = ()
    body_baselines: tuple = field(default_factory=tuple)  # one (x, y) per line

    # Step progress dots (current/total). ``current`` is 1-based;
    # ``total == 0`` means "don't draw dots" (welcome / completion).
    dots_current: int = 0
    dots_total: int = 0
    dots_centers: tuple = field(default_factory=tuple)  # ((cx, cy), …)
    dot_radius: int = 0

    # Primary button rect (bottom-left x, y, w, h).
    primary_label: str = "Next step"
    primary_rect: tuple = (0, 0, 0, 0)
    primary_btn_radius: int = 0

    # Skip-tour link rect (always laid out; renderer can hide it).
    skip_label: str = "Skip tour"
    skip_rect: tuple = (0, 0, 0, 0)
    skip_visible: bool = True

    # Coord system: True if all positions (x/y, baselines, rects)
    # are in **window** coords (used for CARD_POS_WINDOW_CENTER, where
    # the card spans multiple regions). The renderer subtracts the
    # current region's origin per draw call. False = positions are
    # already region-local (the standard single-region case).
    is_window_coords: bool = False


# ---------------------------------------------------------------------------
# Scale plumbing.
#
# Every visual constant in ``constants.py`` is the value at scale=1.0.
# Per-step configs can request a smaller card (chat especially —
# it has to fit above the input strip without clipping). We thread
# ``scale`` through every measurement function and store the resulting
# scaled values on the :class:`CardLayout` so the renderer doesn't
# need to know about scaling.
# ---------------------------------------------------------------------------

def _scaled_int(value, scale: float, minimum: int = 1) -> int:
    return max(minimum, int(round(value * scale)))


def _wrap_body(body_lines: tuple, scale: float) -> tuple:
    """Wrap every line in ``body_lines`` to fit the (scaled) card's
    inner content width."""
    inner_w = _scaled_int(CARD_WIDTH - 2 * CARD_PADDING_X, scale)
    body_font = _scaled_int(CARD_FONT_BODY, scale, minimum=10)
    out = []
    for line in body_lines:
        out.extend(_wrap_line(body_font, inner_w, line))
    return tuple(out)


def measure_card(
    title_text: str,
    body_lines: tuple,
    has_dots: bool,
    scale: float,
) -> tuple:
    """Return ``(width, height)`` for the new Apple-style layout.

    Stack from top to bottom:
      padding · icon · gap · title · gap · body · dots-gap · dots · btn-gap · button · padding
    Width is fixed at scaled ``CARD_WIDTH``.
    """
    title_h = _measure_text_h(_scaled_int(CARD_FONT_TITLE, scale, minimum=10))
    body_font = _scaled_int(CARD_FONT_BODY, scale, minimum=10)
    body_line_h = _measure_text_h(body_font)
    body_step = int(body_line_h * CARD_BODY_LINE_SPACING)

    if body_lines:
        body_h = body_step * len(body_lines) - (body_step - body_line_h)
    else:
        body_h = 0

    icon_size = _scaled_int(CARD_ICON_SIZE, scale)
    icon_top_gap = _scaled_int(CARD_ICON_TOP_GAP, scale)
    icon_bottom_gap = _scaled_int(CARD_ICON_BOTTOM_GAP, scale)
    title_body_gap = _scaled_int(CARD_TITLE_BODY_GAP, scale) if body_lines else 0

    btn_h = _scaled_int(CARD_BTN_HEIGHT, scale)
    padding_y = _scaled_int(CARD_PADDING_Y, scale)

    if has_dots:
        body_dots_gap = _scaled_int(CARD_BODY_DOTS_GAP, scale)
        dot_size = _scaled_int(CARD_DOT_RADIUS, scale) * 2
        dots_btn_gap = _scaled_int(CARD_DOTS_BUTTONS_GAP, scale)
    else:
        body_dots_gap = 0
        dot_size = 0
        dots_btn_gap = _scaled_int(CARD_DOTS_BUTTONS_GAP, scale)

    inner_h = (
        icon_top_gap + icon_size + icon_bottom_gap +
        title_h + title_body_gap +
        body_h +
        body_dots_gap + dot_size +
        dots_btn_gap + btn_h
    )

    w = _scaled_int(CARD_WIDTH, scale)
    h = max(_scaled_int(CARD_MIN_HEIGHT, scale), inner_h + 2 * padding_y)
    return (w, h)


def position_card(
    pos_kind: str,
    area_w: int,
    area_h: int,
    card_w: int,
    card_h: int,
    window_w: int = 0,
    window_h: int = 0,
    region_x: int = 0,
    region_y: int = 0,
    bubble_anchor: tuple = None,
) -> tuple:
    """Return ``(x, y)`` in region-relative coords for the card's
    bottom-left corner, given the requested position kind.

    ``window_w / window_h`` and ``region_x / region_y`` are required
    only for ``CARD_POS_WINDOW_CENTER`` — they let us centre the card
    on the whole Mixar window and translate the result into the host
    region's local coords. Other position kinds ignore them.

    ``bubble_anchor``, when given, is a 4-tuple
    ``(cx, cy, bw, bh)`` describing the Agent Bubble's centre and
    size in the host region's local coord system. Required only for
    ``CARD_POS_NEAR_BUBBLE``; ``None`` falls back to ``AREA_CENTER``.
    """
    if pos_kind == CARD_POS_TOP_LEFT:
        x = CARD_AREA_MARGIN
        y = max(CARD_AREA_MARGIN, area_h - card_h - CARD_AREA_MARGIN)
        return (int(x), int(y))

    if pos_kind == CARD_POS_TOP_RIGHT:
        x = max(CARD_AREA_MARGIN, area_w - card_w - CARD_AREA_MARGIN)
        y = max(CARD_AREA_MARGIN, area_h - card_h - CARD_AREA_MARGIN)
        return (int(x), int(y))

    if pos_kind == CARD_POS_SIDEBAR_ADJACENT:
        # Right side of the area, with a gap between the card and
        # the sidebar so the sidebar tab + active panel header stays
        # visible to the right of the card.
        x = area_w - CARD_SIDEBAR_WIDTH - CARD_AREA_MARGIN - card_w
        x = max(CARD_AREA_MARGIN, x)
        y = max(CARD_AREA_MARGIN, (area_h - card_h) // 2)
        return (int(x), int(y))

    if pos_kind == CARD_POS_ABOVE_INPUT:
        # Center horizontally; sit a comfortable distance above the
        # chat input strip so the Ask / Generate / Agent dropdown is
        # never covered. Region coords are post-scale, so scale the
        # base gutter by the active UI scale factor — at 2x retina
        # the input strip is roughly twice as tall in real pixels.
        x = (area_w - card_w) // 2
        gutter = int(CARD_CHAT_INPUT_GUTTER * _ui_scale_factor())
        y = gutter
        # Don't let the top spill above the area.
        max_y = area_h - card_h - CARD_AREA_MARGIN
        y = min(y, max(CARD_AREA_MARGIN, max_y))
        return (int(x), int(y))

    if pos_kind == CARD_POS_NEAR_BUBBLE and bubble_anchor is not None:
        # Place the card directly ABOVE the bubble (in screen / region
        # coords), centred horizontally on the bubble. We prefer
        # above-bubble because the bubble's input strip is at the
        # bottom and the card mustn't cover the user's affordances.
        # If the card doesn't fit above (bubble near the top of the
        # region), fall back to placing it below. All values are in
        # region-local coords; the projection from screen coords is
        # done in ``card_modal_op._bubble_anchor_in_region``.
        bcx, bcy, _bw, bh = bubble_anchor
        gap = int(CARD_BUBBLE_GAP * _ui_scale_factor())
        x = bcx - card_w // 2
        # Above-bubble: card bottom sits ``gap`` px above bubble top.
        y_above = (bcy + bh // 2) + gap
        # Below-bubble fallback: card top sits ``gap`` px under bubble bottom.
        y_below = (bcy - bh // 2) - gap - card_h
        if y_above + card_h <= area_h - CARD_AREA_MARGIN:
            y = y_above
        elif y_below >= CARD_AREA_MARGIN:
            y = y_below
        else:
            # Bubble fills the host region vertically — centre vertically.
            y = (area_h - card_h) // 2
        x = max(CARD_AREA_MARGIN, min(x, area_w - card_w - CARD_AREA_MARGIN))
        y = max(CARD_AREA_MARGIN, min(y, area_h - card_h - CARD_AREA_MARGIN))
        return (int(x), int(y))

    if pos_kind == CARD_POS_WINDOW_CENTER:
        # Centre the card on the full Mixar window, expressed in the
        # **host region's local coords**. The modal op picks a host
        # area that's tall + wide enough to fit the entire card so
        # there's no per-region clipping — the card lives fully in
        # one region but its visual centre lines up with the window
        # centre.
        win_cx = window_w * 0.5
        win_cy = window_h * 0.5
        card_x_win = win_cx - card_w * 0.5
        card_y_win = win_cy - card_h * 0.5
        x = card_x_win - region_x
        y = card_y_win - region_y
        return (int(x), int(y))

    # Default: AREA_CENTER.
    x = (area_w - card_w) // 2
    y = (area_h - card_h) // 2
    return (int(x), int(y))


def compute_layout(
    title_text: str,
    body_lines: tuple,
    primary_label: str,
    skip_label: str,
    pos_kind: str,
    area_w: int,
    area_h: int,
    icon_id: str,
    dots_current: int,
    dots_total: int,
    skip_visible: bool,
    scale: float = 1.0,
    window_w: int = 0,
    window_h: int = 0,
    region_x: int = 0,
    region_y: int = 0,
    bubble_anchor: tuple = None,
) -> CardLayout:
    """Build a :class:`CardLayout` for the Apple-style vertical
    layout — icon at top, centred title, centred body, optional
    step dots, button row at the bottom.

    ``scale`` multiplies every dimension; per-step configs can
    request smaller cards (e.g. chat step).

    ``dots_total > 0`` enables the step-progress dots row.
    """
    title_font = _scaled_int(CARD_FONT_TITLE, scale, minimum=10)
    body_font = _scaled_int(CARD_FONT_BODY, scale, minimum=10)
    button_font = _scaled_int(CARD_FONT_BUTTON, scale, minimum=10)
    progress_font = _scaled_int(CARD_FONT_PROGRESS, scale, minimum=8)
    padding_x = _scaled_int(CARD_PADDING_X, scale)
    padding_y = _scaled_int(CARD_PADDING_Y, scale)
    title_body_gap = _scaled_int(CARD_TITLE_BODY_GAP, scale)
    btn_h = _scaled_int(CARD_BTN_HEIGHT, scale)
    btn_pad_x = _scaled_int(CARD_BTN_PADDING_X, scale)
    corner_radius = _scaled_int(CARD_CORNER_RADIUS, scale)
    btn_radius = _scaled_int(CARD_BTN_RADIUS, scale)
    icon_size = _scaled_int(CARD_ICON_SIZE, scale)
    icon_top_gap = _scaled_int(CARD_ICON_TOP_GAP, scale)
    icon_bottom_gap = _scaled_int(CARD_ICON_BOTTOM_GAP, scale)
    body_dots_gap = _scaled_int(CARD_BODY_DOTS_GAP, scale)
    dots_btn_gap = _scaled_int(CARD_DOTS_BUTTONS_GAP, scale)
    dot_radius = _scaled_int(CARD_DOT_RADIUS, scale)
    dot_gap = _scaled_int(CARD_DOT_GAP, scale)
    min_btn_w = _scaled_int(220, scale)

    has_dots = dots_total > 0
    wrapped_body = _wrap_body(tuple(body_lines), scale)

    layout = CardLayout(
        title_text=title_text,
        body_lines=wrapped_body,
        primary_label=primary_label,
        skip_label=skip_label,
        skip_visible=skip_visible,
        corner_radius=corner_radius,
        title_font=title_font,
        body_font=body_font,
        button_font=button_font,
        progress_font=progress_font,
        primary_btn_radius=btn_radius,
        scale=scale,
        icon_id=icon_id,
        dots_current=dots_current,
        dots_total=dots_total,
        dot_radius=dot_radius,
        # The card is always drawn in single-region mode now. The
        # WINDOW_CENTER position kind selects a *host area* big enough
        # for the card; layout coords are always region-local.
        is_window_coords=False,
    )

    layout.w, layout.h = measure_card(
        title_text, wrapped_body, has_dots, scale,
    )
    layout.x, layout.y = position_card(
        pos_kind, area_w, area_h, layout.w, layout.h,
        window_w=window_w, window_h=window_h,
        region_x=region_x, region_y=region_y,
        bubble_anchor=bubble_anchor,
    )

    cx_card = layout.x + layout.w * 0.5

    # Top-down stacking, starting at the top inside-edge of the card.
    cursor_y = layout.y + layout.h - padding_y - icon_top_gap

    # Icon slot — centred horizontally, top-justified.
    icon_x = int(cx_card - icon_size * 0.5)
    icon_y = cursor_y - icon_size
    layout.icon_rect = (icon_x, icon_y, icon_size, icon_size)
    cursor_y = icon_y - icon_bottom_gap

    # Title — centred horizontally.
    title_h = _measure_text_h(title_font)
    title_w = _measure_text_w(title_font, title_text)
    layout.title_baseline = (
        int(cx_card - title_w * 0.5),
        cursor_y - title_h,
    )
    cursor_y -= title_h
    if wrapped_body:
        cursor_y -= title_body_gap

    # Body — each line centred.
    if wrapped_body:
        body_line_h = _measure_text_h(body_font)
        body_step = int(body_line_h * CARD_BODY_LINE_SPACING)
        baselines = []
        line_y = cursor_y - body_line_h
        for line in wrapped_body:
            line_w = _measure_text_w(body_font, line) if line else 0
            baselines.append((int(cx_card - line_w * 0.5), line_y))
            line_y -= body_step
        layout.body_baselines = tuple(baselines)
        cursor_y = baselines[-1][1] - (body_step - body_line_h)

    # Step dots — centred row near the bottom (above the buttons).
    if has_dots:
        cursor_y -= body_dots_gap
        total_w = (dots_total - 1) * dot_gap
        first_cx = cx_card - total_w * 0.5
        dot_y = cursor_y - dot_radius
        layout.dots_centers = tuple(
            (int(first_cx + i * dot_gap), int(dot_y))
            for i in range(dots_total)
        )

    # Primary "Continue" button — bottom-right.
    btn_w = _measure_text_w(button_font, primary_label) + 2 * btn_pad_x
    btn_w = max(min_btn_w, btn_w)
    btn_x = layout.x + layout.w - padding_x - btn_w
    btn_y = layout.y + padding_y
    layout.primary_rect = (btn_x, btn_y, btn_w, btn_h)

    # Skip link — bottom-left, vertically centred against the button.
    skip_w = _measure_text_w(button_font, skip_label)
    skip_h = _measure_text_h(button_font)
    skip_x = layout.x + padding_x
    skip_y = btn_y + (btn_h - skip_h) // 2
    layout.skip_rect = (skip_x, skip_y, skip_w, skip_h)

    return layout


def hit_test(layout: CardLayout, region_x: int, region_y: int):
    """Return ``"primary"``, ``"skip"``, ``"card"``, or ``None``.

    ``"card"`` means inside the card body but not on a button — the
    modal uses this to swallow stray clicks so the click doesn't fall
    through to whatever is underneath.
    """
    px, py, pw, ph = layout.primary_rect
    if px <= region_x <= px + pw and py <= region_y <= py + ph:
        return "primary"

    if layout.skip_visible:
        sx, sy, sw, sh = layout.skip_rect
        # Slightly enlarge the skip-link hit box so it's easy to click.
        pad = 6
        if (sx - pad) <= region_x <= (sx + sw + pad) and \
           (sy - pad) <= region_y <= (sy + sh + pad):
            return "skip"

    if layout.x <= region_x <= layout.x + layout.w and \
       layout.y <= region_y <= layout.y + layout.h:
        return "card"

    return None
