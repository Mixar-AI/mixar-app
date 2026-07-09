# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Toast Renderer

Draws notification toasts in the 3D viewport using GPU and BLF.
Modern Apple-style cards with rounded corners, type badge, action
buttons, and a circular close button.

Buttons carry full interaction states: bordered idle look, hover
highlight (driven by MOUSEMOVE forwarded from view3d_toast_click.cc),
and a pressed flash before the action fires.
"""

import os

import bpy
import blf

from mixar.config.logging_config import get_logger

from .constants import (
    ACTION_URL_FONT_SIZE,
    BADGE_RADIUS,
    BODY_FONT_SIZE,
    BUTTON_BORDER_WIDTH,
    BUTTON_CORNER_RADIUS,
    BUTTON_FONT_SIZE,
    BUTTON_GAP,
    BUTTON_HEIGHT,
    BUTTON_PADDING_X,
    EXTRABOLD_FONT_FILE,
    PRIMARY_BUTTON_FONT_SIZE,
    CLOSE_BUTTON_SIZE,
    CLOSE_BUTTON_RADIUS,
    CLOSE_ICON_FONT_SIZE,
    TITLE_FONT_SIZE,
    TOAST_CORNER_OFFSET_X,
    TOAST_CORNER_OFFSET_Y,
    TOAST_CORNER_RADIUS,
    TOAST_MARGIN,
    TOAST_PADDING_X,
    TOAST_PADDING_Y,
    TOAST_WIDTH,
    get_toast_colors,
)
from .store import NotificationItem, get_notification_store
from .toast_renderer_shapes import (
    draw_circle,
    draw_rect,
    draw_rounded_rect,
    draw_rounded_rect_outline,
)

# Draw handler reference
_draw_handle = {"handler": None}

# Font ID (0 = default Blender font)
_FONT_ID = 0

logger = get_logger(__name__)

# Cached blf font id for Manrope ExtraBold used on primary CTA labels.
#   None  = not yet attempted
#   >= 0  = loaded custom font id
#   -1    = tried, unavailable (use the default font)
_primary_font = {"id": None}


def _get_primary_font_id() -> int:
    """Return a blf font id for the bundled Manrope ExtraBold (cached).

    Falls back to the default font (which is Manrope Regular) when the
    ExtraBold file isn't found or blf can't load it.
    """
    cached = _primary_font["id"]
    if cached is not None:
        return cached if cached >= 0 else _FONT_ID

    fid = _FONT_ID
    try:
        base = bpy.utils.system_resource('DATAFILES')
        path = os.path.join(base, "fonts", EXTRABOLD_FONT_FILE) if base else ""
        if path and os.path.exists(path):
            loaded = blf.load(path)
            if loaded is not None and loaded >= 0:
                fid = loaded
        else:
            logger.debug("ExtraBold font not found at %s", path)
    except Exception as e:  # noqa: BLE001 — never let font loading break drawing
        logger.debug("ExtraBold font load failed: %s", e)

    _primary_font["id"] = fid if fid != _FONT_ID else -1
    return fid

# Hit-test bounding boxes, keyed by region pointer (each View3D region draws
# its own toast layout). Rebuilt every draw pass, consumed by the click and
# hover operators via bounds_for_region().
#   {region_ptr: {"close":  [(nid, x, y, w, h), ...],
#                 "action": [(nid, operator_idname, x, y, w, h), ...],
#                 "url":    [(nid, url, x, y, w, h), ...]}}
toast_bounds_by_region: dict[int, dict[str, list]] = {}

# Interaction state shared with the click/hover operators. Keys:
#   ("close", nid) | ("action", nid, operator_idname) | ("url", nid)
toast_hover_state: dict = {"key": None}
toast_pressed_state: dict = {"key": None}


# The layout constants were authored on a Retina display where Blender's
# UI_SCALE_FAC (``preferences.system.ui_scale`` == ``U.scale_factor`` ==
# ``dpi / 72``, which folds in the native pixel size) is ~2.0. We normalise
# by that so the toast keeps its authored size on Retina and scales down on
# lower-DPI external monitors — matching how every native Blender widget
# scales. Without this the toast draws at fixed pixels and looks oversized
# when the window moves to a display with a different scale factor.
_AUTHORED_SCALE = 2.0


def _scale() -> float:
    """Current UI scale relative to the authored (Retina) baseline."""
    try:
        return float(bpy.context.preferences.system.ui_scale) / _AUTHORED_SCALE
    except Exception:  # noqa: BLE001 — preferences unavailable (headless/tests)
        return 1.0


def _fsize(base: float, s: float) -> int:
    """Scale a font point size, clamped to a sane minimum."""
    return max(1, int(round(base * s)))


def bounds_for_region(region_ptr: int) -> dict[str, list] | None:
    """Return the hit-test bounds recorded for a region, if any."""
    return toast_bounds_by_region.get(region_ptr)


def point_in_rect(mx: float, my: float, bx: float, by: float, bw: float, bh: float) -> bool:
    """Test whether a point lies inside an axis-aligned rect."""
    return bx <= mx <= bx + bw and by <= my <= by + bh


def update_hover_state(region_ptr: int, mx: float, my: float) -> bool:
    """Recompute the hovered element for a mouse position.

    Returns True when the hover target changed (caller should redraw).
    """
    bounds = toast_bounds_by_region.get(region_ptr)
    key = None
    if bounds:
        for nid, bx, by, bw, bh in bounds["close"]:
            if point_in_rect(mx, my, bx, by, bw, bh):
                key = ("close", nid)
                break
        if key is None:
            for nid, op, bx, by, bw, bh in bounds["action"]:
                if point_in_rect(mx, my, bx, by, bw, bh):
                    key = ("action", nid, op)
                    break
        if key is None:
            for nid, url, bx, by, bw, bh in bounds["url"]:
                if point_in_rect(mx, my, bx, by, bw, bh):
                    key = ("url", nid)
                    break

    if key != toast_hover_state["key"]:
        toast_hover_state["key"] = key
        return True
    return False


def _hovered(color: tuple) -> tuple:
    """Brighten a color for the hover state."""
    return (
        min(color[0] + 0.10, 1.0),
        min(color[1] + 0.10, 1.0),
        min(color[2] + 0.10, 1.0),
        min(color[3] + 0.12, 1.0),
    )


def _pressed(color: tuple) -> tuple:
    """Darken (and solidify) a color for the pressed state."""
    return (
        color[0] * 0.75,
        color[1] * 0.75,
        color[2] * 0.75,
        min(color[3] + 0.25, 1.0),
    )


def _wrap_text(text: str, font_size: int, max_width: float) -> list[str]:
    """Word-wrap text to fit within max_width pixels using BLF metrics.

    Explicit newlines in *text* are honored as hard line breaks — each is
    wrapped independently — so callers can force a new line with ``\\n``.
    """
    blf.size(_FONT_ID, font_size)

    lines: list[str] = []
    for segment in text.split("\n"):
        words = segment.split()
        if not words:
            continue

        current_line = words[0]
        for word in words[1:]:
            test = current_line + " " + word
            w, _ = blf.dimensions(_FONT_ID, test)
            if w <= max_width:
                current_line = test
            else:
                lines.append(current_line)
                current_line = word

        lines.append(current_line)

    return lines


def _apply_opacity(color: tuple, opacity: float) -> tuple:
    """Return a copy of an RGBA color with alpha scaled by opacity."""
    return (*color[:3], color[3] * opacity)


def _button_font(style: str, s: float) -> tuple[int, int]:
    """Return the (font_id, font_size) a button label draws with.

    Primary CTAs use Manrope ExtraBold at the larger primary size; other
    styles use the default font at the base button size. Sizes are scaled
    by the current UI scale ``s``.
    """
    if style == "primary":
        return _get_primary_font_id(), _fsize(PRIMARY_BUTTON_FONT_SIZE, s)
    return _FONT_ID, _fsize(BUTTON_FONT_SIZE, s)


def _measure_button_width(label: str, style: str, s: float) -> float:
    """Measure the pixel width a button needs for its label."""
    font_id, font_size = _button_font(style, s)
    blf.size(font_id, font_size)
    tw, _ = blf.dimensions(font_id, label)
    return tw + BUTTON_PADDING_X * s * 2


def _draw_single_toast(
    item: NotificationItem, x_right: float, y_top: float, bounds: dict[str, list],
    s: float,
) -> float:
    """Render one toast and return its total height (including margin).

    All pixel dimensions are multiplied by the UI scale ``s`` so the toast
    tracks Blender's widgets across displays with different DPI / scale.

    Layout:
        +---------------------------------------------+
        |  *  Title Text                          (x) |
        |                                             |
        |     Body text line 1                        |
        |     Body text line 2                        |
        |     action_url (dimmed)                     |
        |                                             |
        |              [ Secondary ]  [ Primary ]     |
        +---------------------------------------------+
    """
    opacity = item.opacity
    if opacity <= 0:
        return 0.0

    colors = get_toast_colors(item.type)
    bg_base = colors["bg"]
    text_base = colors["text"]
    badge_base = colors["badge"]

    bg_color = _apply_opacity(bg_base, opacity)
    text_color = _apply_opacity(text_base, opacity)
    badge_color = _apply_opacity(badge_base, opacity)

    # -- Scaled layout metrics --
    width = TOAST_WIDTH * s
    pad_x = TOAST_PADDING_X * s
    pad_y = TOAST_PADDING_Y * s
    corner = TOAST_CORNER_RADIUS * s
    badge_r = BADGE_RADIUS * s
    close_sz = CLOSE_BUTTON_SIZE * s
    close_r = CLOSE_BUTTON_RADIUS * s
    btn_h = BUTTON_HEIGHT * s
    btn_gap = BUTTON_GAP * s
    btn_corner = BUTTON_CORNER_RADIUS * s
    btn_border = max(1.0, BUTTON_BORDER_WIDTH * s)
    badge_gap = 10 * s

    title_sz = _fsize(TITLE_FONT_SIZE, s)
    body_sz = _fsize(BODY_FONT_SIZE, s)
    url_sz = _fsize(ACTION_URL_FONT_SIZE, s)

    inner_width = width - 2 * pad_x
    # Badge + gap takes space on title line
    badge_space = badge_r * 2 + badge_gap

    # -- Measure title --
    blf.size(_FONT_ID, title_sz)
    _, title_h = blf.dimensions(_FONT_ID, item.title or "N")
    title_h = max(title_h, title_sz)

    # -- Measure body --
    body_lines = _wrap_text(item.body, body_sz, inner_width) if item.body else []
    blf.size(_FONT_ID, body_sz)
    _, body_line_h = blf.dimensions(_FONT_ID, "Ag")
    body_line_h = max(body_line_h, body_sz)
    body_line_spacing = body_line_h * 1.35
    body_height = body_line_spacing * len(body_lines) if body_lines else 0.0

    # -- Measure action URL --
    url_lines: list[str] = []
    url_line_spacing = 0.0
    url_height = 0.0
    if item.action_url:
        url_lines = _wrap_text(item.action_url, url_sz, inner_width)
        blf.size(_FONT_ID, url_sz)
        _, url_line_h = blf.dimensions(_FONT_ID, "Ag")
        url_line_h = max(url_line_h, url_sz)
        url_line_spacing = url_line_h * 1.35
        url_height = url_line_spacing * len(url_lines)

    # -- Measure action buttons --
    has_buttons = bool(item.actions)
    buttons_height = (btn_h + pad_y) if has_buttons else 0

    # -- Total toast height --
    gap_body = 8 * s if body_lines else 0
    gap_url = 4 * s if url_lines else 0
    content_h = title_h + gap_body + body_height + gap_url + url_height + buttons_height
    toast_h = content_h + 2 * pad_y

    # Position: top-right, growing downward
    x = x_right - width
    y = y_top - toast_h

    # -- Background (rounded) --
    draw_rounded_rect(x, y, width, toast_h, corner, bg_color)

    # -- Badge dot --
    badge_cx = x + pad_x + badge_r
    badge_cy = y + toast_h - pad_y - title_h * 0.5
    draw_circle(badge_cx, badge_cy, badge_r, badge_color)

    # -- Close button (circular) \u2014 omitted for non-dismissible toasts --
    if item.dismissible:
        close_cx = x + width - pad_x - close_r
        close_cy = y + toast_h - pad_y - close_r
        close_hovered = toast_hover_state["key"] == ("close", item.id)
        close_base = _hovered(colors["close_bg"]) if close_hovered else colors["close_bg"]
        draw_circle(close_cx, close_cy, close_r, _apply_opacity(close_base, opacity))

        # "x" glyph centered in circle
        close_icon = colors["close_icon"]
        if close_hovered:
            close_icon = (*close_icon[:3], 1.0)
        blf.size(_FONT_ID, _fsize(CLOSE_ICON_FONT_SIZE, s))
        xw, xh = blf.dimensions(_FONT_ID, "\u00d7")
        blf.color(_FONT_ID, *_apply_opacity(close_icon, opacity))
        blf.position(_FONT_ID, close_cx - xw * 0.5, close_cy - xh * 0.5, 0)
        blf.draw(_FONT_ID, "\u00d7")

        # Record close-button bounds (square around circle for easier hit-testing)
        close_box_x = close_cx - close_r
        close_box_y = close_cy - close_r
        bounds["close"].append((
            item.id, close_box_x, close_box_y,
            close_sz, close_sz,
        ))

    # -- Title text --
    title_x = x + pad_x + badge_space
    title_y = y + toast_h - pad_y - title_h
    blf.size(_FONT_ID, title_sz)
    blf.color(_FONT_ID, *text_color)
    blf.position(_FONT_ID, title_x, title_y, 0)
    blf.draw(_FONT_ID, item.title)

    # -- Body lines --
    cursor_y = title_y - gap_body
    if body_lines:
        blf.size(_FONT_ID, body_sz)
        blf.color(_FONT_ID, *text_color)
        for line in body_lines:
            cursor_y -= body_line_spacing
            blf.position(_FONT_ID, title_x, cursor_y, 0)
            blf.draw(_FONT_ID, line)

    # -- Action URL (styled as clickable link) --
    if url_lines:
        cursor_y -= gap_url
        url_hovered = toast_hover_state["key"] == ("url", item.id)
        url_base = _hovered(badge_base) if url_hovered else badge_base
        link_color = _apply_opacity(url_base, opacity)
        underline_alpha = 1.0 if url_hovered else 0.5
        underline_color = (*url_base[:3], url_base[3] * opacity * underline_alpha)
        blf.size(_FONT_ID, url_sz)

        url_block_top = cursor_y
        for line in url_lines:
            cursor_y -= url_line_spacing
            blf.color(_FONT_ID, *link_color)
            blf.position(_FONT_ID, title_x, cursor_y, 0)
            blf.draw(_FONT_ID, line)
            # Underline
            lw, _ = blf.dimensions(_FONT_ID, line)
            draw_rect(title_x, cursor_y - 2 * s, lw, max(1.0, s), underline_color)

        # Record URL bounds for click handling
        url_block_h = url_block_top - cursor_y
        bounds["url"].append((
            item.id, item.action_url,
            title_x, cursor_y, inner_width, url_block_h,
        ))

    # -- Action buttons (right-aligned) --
    if has_buttons:
        btn_y = y + pad_y
        btn_right = x + width - pad_x

        _button_style_map = {
            "primary": colors["button_primary"],
            "secondary": colors["button_secondary"],
            "danger": colors["button_danger"],
        }

        # Draw buttons right-to-left (last action = rightmost = primary)
        for action in reversed(item.actions):
            style = _button_style_map.get(action.style, colors["button_secondary"])
            btn_w = _measure_button_width(action.label, action.style, s)
            btn_x = btn_right - btn_w

            key = ("action", item.id, action.operator)
            is_pressed = toast_pressed_state["key"] == key
            is_hovered = toast_hover_state["key"] == key

            fill = style["bg"]
            border = style.get("border")
            if is_pressed:
                fill = _pressed(fill)
            elif is_hovered:
                fill = _hovered(fill)
                if border:
                    border = (*border[:3], min(border[3] + 0.25, 1.0))

            draw_rounded_rect(
                btn_x, btn_y, btn_w, btn_h,
                btn_corner, _apply_opacity(fill, opacity),
            )
            if border:
                draw_rounded_rect_outline(
                    btn_x, btn_y, btn_w, btn_h,
                    btn_corner, _apply_opacity(border, opacity),
                    btn_border,
                )

            # Button label centered (primary CTA in Manrope ExtraBold)
            label_font, label_size = _button_font(action.style, s)
            blf.size(label_font, label_size)
            tw, th = blf.dimensions(label_font, action.label)
            blf.color(label_font, *_apply_opacity(style["text"], opacity))
            blf.position(
                label_font,
                btn_x + (btn_w - tw) * 0.5,
                btn_y + (btn_h - th) * 0.5,
                0,
            )
            blf.draw(label_font, action.label)

            # Record bounds for hit-testing
            bounds["action"].append((
                item.id, action.operator,
                btn_x, btn_y, btn_w, btn_h,
            ))

            btn_right = btn_x - btn_gap

    return toast_h + TOAST_MARGIN * s


def _draw_toast_callback() -> None:
    """SpaceView3D POST_PIXEL draw callback -- renders all visible toasts."""
    store = get_notification_store()
    toasts = store.get_visible()
    if not toasts:
        return

    region = bpy.context.region
    if region is None:
        return

    # Rebuild this region's bounds from scratch each draw pass
    bounds: dict[str, list] = {"close": [], "action": [], "url": []}
    toast_bounds_by_region[region.as_pointer()] = bounds

    s = _scale()
    x_right = region.width - TOAST_CORNER_OFFSET_X * s
    y_cursor = region.height - TOAST_CORNER_OFFSET_Y * s

    for item in toasts:
        consumed = _draw_single_toast(item, x_right, y_cursor, bounds, s)
        y_cursor -= consumed


def install_draw_handler() -> None:
    """Register the toast draw callback on SpaceView3D."""
    if _draw_handle["handler"] is None:
        _draw_handle["handler"] = bpy.types.SpaceView3D.draw_handler_add(
            _draw_toast_callback, (), 'WINDOW', 'POST_PIXEL'
        )


def remove_draw_handler() -> None:
    """Unregister the toast draw callback from SpaceView3D."""
    if _draw_handle["handler"] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle["handler"], 'WINDOW')
        _draw_handle["handler"] = None
    toast_bounds_by_region.clear()
    toast_hover_state["key"] = None
    toast_pressed_state["key"] = None
