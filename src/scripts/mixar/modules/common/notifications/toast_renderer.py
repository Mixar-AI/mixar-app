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

import bpy
import blf

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
    CLOSE_BUTTON_SIZE,
    CLOSE_BUTTON_RADIUS,
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
    """Word-wrap text to fit within max_width pixels using BLF metrics."""
    blf.size(_FONT_ID, font_size)
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
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


def _measure_button_width(label: str) -> float:
    """Measure the pixel width a button needs for its label."""
    blf.size(_FONT_ID, BUTTON_FONT_SIZE)
    tw, _ = blf.dimensions(_FONT_ID, label)
    return tw + BUTTON_PADDING_X * 2


def _draw_single_toast(
    item: NotificationItem, x_right: float, y_top: float, bounds: dict[str, list],
) -> float:
    """Render one toast and return its total height (including margin).

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
    dim_color = _apply_opacity(colors["dim_text"], opacity)
    badge_color = _apply_opacity(badge_base, opacity)

    inner_width = TOAST_WIDTH - 2 * TOAST_PADDING_X
    # Badge + gap takes space on title line
    badge_space = BADGE_RADIUS * 2 + 10
    title_max_width = inner_width - badge_space - CLOSE_BUTTON_SIZE - 8

    # -- Measure title --
    blf.size(_FONT_ID, TITLE_FONT_SIZE)
    _, title_h = blf.dimensions(_FONT_ID, item.title or "N")
    title_h = max(title_h, TITLE_FONT_SIZE)

    # -- Measure body --
    body_lines = _wrap_text(item.body, BODY_FONT_SIZE, inner_width) if item.body else []
    blf.size(_FONT_ID, BODY_FONT_SIZE)
    _, body_line_h = blf.dimensions(_FONT_ID, "Ag")
    body_line_h = max(body_line_h, BODY_FONT_SIZE)
    body_line_spacing = body_line_h * 1.35
    body_height = body_line_spacing * len(body_lines) if body_lines else 0.0

    # -- Measure action URL --
    url_lines: list[str] = []
    url_line_spacing = 0.0
    url_height = 0.0
    if item.action_url:
        url_lines = _wrap_text(item.action_url, ACTION_URL_FONT_SIZE, inner_width)
        blf.size(_FONT_ID, ACTION_URL_FONT_SIZE)
        _, url_line_h = blf.dimensions(_FONT_ID, "Ag")
        url_line_h = max(url_line_h, ACTION_URL_FONT_SIZE)
        url_line_spacing = url_line_h * 1.35
        url_height = url_line_spacing * len(url_lines)

    # -- Measure action buttons --
    has_buttons = bool(item.actions)
    buttons_height = (BUTTON_HEIGHT + TOAST_PADDING_Y) if has_buttons else 0

    # -- Total toast height --
    gap_body = 8 if body_lines else 0
    gap_url = 4 if url_lines else 0
    content_h = title_h + gap_body + body_height + gap_url + url_height + buttons_height
    toast_h = content_h + 2 * TOAST_PADDING_Y

    # Position: top-right, growing downward
    x = x_right - TOAST_WIDTH
    y = y_top - toast_h

    # -- Background (rounded) --
    draw_rounded_rect(x, y, TOAST_WIDTH, toast_h, TOAST_CORNER_RADIUS, bg_color)

    # -- Badge dot --
    badge_cx = x + TOAST_PADDING_X + BADGE_RADIUS
    badge_cy = y + toast_h - TOAST_PADDING_Y - title_h * 0.5
    draw_circle(badge_cx, badge_cy, BADGE_RADIUS, badge_color)

    # -- Close button (circular) \u2014 omitted for non-dismissible toasts --
    if item.dismissible:
        close_cx = x + TOAST_WIDTH - TOAST_PADDING_X - CLOSE_BUTTON_RADIUS
        close_cy = y + toast_h - TOAST_PADDING_Y - CLOSE_BUTTON_RADIUS
        close_hovered = toast_hover_state["key"] == ("close", item.id)
        close_base = _hovered(colors["close_bg"]) if close_hovered else colors["close_bg"]
        draw_circle(close_cx, close_cy, CLOSE_BUTTON_RADIUS, _apply_opacity(close_base, opacity))

        # "x" glyph centered in circle
        close_icon = colors["close_icon"]
        if close_hovered:
            close_icon = (*close_icon[:3], 1.0)
        blf.size(_FONT_ID, 16)
        xw, xh = blf.dimensions(_FONT_ID, "\u00d7")
        blf.color(_FONT_ID, *_apply_opacity(close_icon, opacity))
        blf.position(_FONT_ID, close_cx - xw * 0.5, close_cy - xh * 0.5, 0)
        blf.draw(_FONT_ID, "\u00d7")

        # Record close-button bounds (square around circle for easier hit-testing)
        close_box_x = close_cx - CLOSE_BUTTON_RADIUS
        close_box_y = close_cy - CLOSE_BUTTON_RADIUS
        bounds["close"].append((
            item.id, close_box_x, close_box_y,
            CLOSE_BUTTON_SIZE, CLOSE_BUTTON_SIZE,
        ))

    # -- Title text --
    title_x = x + TOAST_PADDING_X + badge_space
    title_y = y + toast_h - TOAST_PADDING_Y - title_h
    blf.size(_FONT_ID, TITLE_FONT_SIZE)
    blf.color(_FONT_ID, *text_color)
    blf.position(_FONT_ID, title_x, title_y, 0)
    blf.draw(_FONT_ID, item.title)

    # -- Body lines --
    cursor_y = title_y - gap_body
    if body_lines:
        blf.size(_FONT_ID, BODY_FONT_SIZE)
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
        blf.size(_FONT_ID, ACTION_URL_FONT_SIZE)

        url_block_top = cursor_y
        for line in url_lines:
            cursor_y -= url_line_spacing
            blf.color(_FONT_ID, *link_color)
            blf.position(_FONT_ID, title_x, cursor_y, 0)
            blf.draw(_FONT_ID, line)
            # Underline
            lw, _ = blf.dimensions(_FONT_ID, line)
            draw_rect(title_x, cursor_y - 2, lw, 1, underline_color)

        # Record URL bounds for click handling
        url_block_h = url_block_top - cursor_y
        bounds["url"].append((
            item.id, item.action_url,
            title_x, cursor_y, inner_width, url_block_h,
        ))

    # -- Action buttons (right-aligned) --
    if has_buttons:
        btn_y = y + TOAST_PADDING_Y
        btn_right = x + TOAST_WIDTH - TOAST_PADDING_X

        _button_style_map = {
            "primary": colors["button_primary"],
            "secondary": colors["button_secondary"],
            "danger": colors["button_danger"],
        }

        # Draw buttons right-to-left (last action = rightmost = primary)
        for action in reversed(item.actions):
            style = _button_style_map.get(action.style, colors["button_secondary"])
            btn_w = _measure_button_width(action.label)
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
                btn_x, btn_y, btn_w, BUTTON_HEIGHT,
                BUTTON_CORNER_RADIUS, _apply_opacity(fill, opacity),
            )
            if border:
                draw_rounded_rect_outline(
                    btn_x, btn_y, btn_w, BUTTON_HEIGHT,
                    BUTTON_CORNER_RADIUS, _apply_opacity(border, opacity),
                    BUTTON_BORDER_WIDTH,
                )

            # Button label centered
            blf.size(_FONT_ID, BUTTON_FONT_SIZE)
            tw, th = blf.dimensions(_FONT_ID, action.label)
            blf.color(_FONT_ID, *_apply_opacity(style["text"], opacity))
            blf.position(
                _FONT_ID,
                btn_x + (btn_w - tw) * 0.5,
                btn_y + (BUTTON_HEIGHT - th) * 0.5,
                0,
            )
            blf.draw(_FONT_ID, action.label)

            # Record bounds for hit-testing
            bounds["action"].append((
                item.id, action.operator,
                btn_x, btn_y, btn_w, BUTTON_HEIGHT,
            ))

            btn_right = btn_x - BUTTON_GAP

    return toast_h + TOAST_MARGIN


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

    x_right = region.width - TOAST_CORNER_OFFSET_X
    y_cursor = region.height - TOAST_CORNER_OFFSET_Y

    for item in toasts:
        consumed = _draw_single_toast(item, x_right, y_cursor, bounds)
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
