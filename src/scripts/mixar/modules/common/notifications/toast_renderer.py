# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Liquid-glass toasts with native typography and one measured input layout."""

import bpy
import blf

from .constants import (
    BADGE_RADIUS, BUTTON_BORDER_WIDTH, BUTTON_CORNER_RADIUS,
    TOAST_CORNER_RADIUS, TOAST_MARGIN, get_toast_colors,
)
from .store import get_notification_store
from .toast_layout import _scale, layout_toast, toast_lane
from .toast_renderer_shapes import draw_circle, draw_rounded_rect, draw_rounded_rect_outline

_draw_handle = {"handler": None}
_FONT_ID = 0
# Drawn content is also the source for read-only QA targets and scroll limits.
toast_layouts_by_region = {}
toast_scroll_offsets = {}

# Hit-test bounding boxes, keyed by region pointer (each View3D region draws
# its own toast layout). Rebuilt every draw pass, consumed by the click and
# hover operators via bounds_for_region().
#   {region_ptr: {"close":  [(nid, x, y, w, h), ...],
#                 "action": [(nid, operator_idname, url, x, y, w, h), ...],
#                 "url":    [(nid, url, x, y, w, h), ...]}}
toast_bounds_by_region: dict[int, dict[str, list]] = {}

# Interaction state shared with the click/hover operators. Keys:
#   ("close", nid) | ("action", nid, operator_idname or url) | ("url", nid)
toast_hover_state: dict = {"key": None}
toast_pressed_state: dict = {"key": None}



def bounds_for_region(region_ptr: int) -> dict[str, list] | None:
    """Return the hit-test bounds recorded for a region, if any."""
    return toast_bounds_by_region.get(region_ptr)


def point_in_rect(mx: float, my: float, bx: float, by: float, bw: float, bh: float) -> bool:
    """Test whether a point lies inside an axis-aligned rect."""
    return bx <= mx <= bx + bw and by <= my <= by + bh


def point_in_any_toast_control(region_ptr: int, mx: float, my: float) -> bool:
    """True if a region-local point lies on a toast button, close X, or link.

    Pure predicate (no hover-state mutation) so input-blocking modals can
    ask "should this click reach the toast?" before consuming it. Only the
    interactive controls count, not the toast card body: a click that
    misses them makes ``notification.toast_click`` return CANCELLED, and
    the event would fall through to the viewport keymaps the modal exists
    to block.
    """
    bounds = toast_bounds_by_region.get(region_ptr)
    if not bounds:
        return False
    for _nid, bx, by, bw, bh in bounds["close"]:
        if point_in_rect(mx, my, bx, by, bw, bh):
            return True
    for _nid, _op, _url, bx, by, bw, bh in bounds["action"]:
        if point_in_rect(mx, my, bx, by, bw, bh):
            return True
    for _nid, _url, bx, by, bw, bh in bounds["url"]:
        if point_in_rect(mx, my, bx, by, bw, bh):
            return True
    return False


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
            for nid, op, url, bx, by, bw, bh in bounds["action"]:
                if point_in_rect(mx, my, bx, by, bw, bh):
                    key = ("action", nid, op or url)
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



def _apply_opacity(color: tuple, opacity: float) -> tuple:
    """Return a copy of an RGBA color with alpha scaled by opacity."""
    return (*color[:3], color[3] * opacity)


def scroll_toast(region_ptr, mx, my, delta):
    """Consume scrolling only over a card with overflowing content."""
    for card in toast_layouts_by_region.get(region_ptr, []):
        if card['max_scroll'] > 0 and point_in_rect(mx, my, *card['rect']):
            key = (region_ptr, card['id'])
            toast_scroll_offsets[key] = min(card['max_scroll'], max(0.0,
                toast_scroll_offsets.get(key, 0.0) + delta))
            return True
    return False


def _intersection(rect, clip):
    x, y, w, h = rect
    cx, cy, cw, ch = clip
    left, bottom = max(x, cx), max(y, cy)
    right, top = min(x + w, cx + cw), min(y + h, cy + ch)
    return (left, bottom, right-left, top-bottom) if right > left and top > bottom else None


def _draw_lines(lines, x, top, font_size, line_height, color, clip, samples, kind,
                center_width=None, font_id=_FONT_ID):
    blf.size(font_id, font_size)
    blf.color(font_id, *color)
    blf.clipping(font_id, clip[0], clip[1], clip[0]+clip[2], clip[1]+clip[3])
    blf.enable(font_id, blf.CLIPPING)
    try:
        for i, line in enumerate(lines):
            baseline = round(top - font_size - i * line_height)
            width, height = blf.dimensions(font_id, line)
            px = round(x if center_width is None else x + (center_width-width) * .5)
            visible = _intersection((px, baseline-font_size*.3, width, line_height), clip)
            if visible and line:
                blf.position(font_id, px, baseline, 0)
                blf.draw(font_id, line)
                samples.append(dict(kind=kind, text=line, rect=visible,
                                    font_size=font_size, glyph_height=height, font_id=font_id))
    finally:
        blf.disable(font_id, blf.CLIPPING)


def _draw_single_toast(item, x_right, y_top, bounds, scale, width, available_height, region,
                       layout=None):
    opacity = item.opacity
    if opacity <= 0:
        return None
    layout = layout if layout is not None else layout_toast(item, width, scale)
    height = min(layout['height'], available_height)
    x, y = x_right-width, y_top-height
    pad_y, pad_x = layout['pad_y'], layout['pad_x']
    clip = (x + layout['content_x'], y + pad_y,
            layout['content_width'], max(1.0, height - 2 * pad_y))
    max_scroll = max(0.0, layout['content_height'] - clip[3])
    key = (region.as_pointer(), item.id)
    scroll = min(max_scroll, max(0.0, toast_scroll_offsets.get(key, 0.0)))
    toast_scroll_offsets[key] = scroll
    content_top = y_top - pad_y + scroll
    colors = get_toast_colors(item.type)
    text_color = _apply_opacity(colors['text'], opacity)
    samples = []
    card = dict(id=item.id, title=item.title, rect=(x, y, width, height),
                clip=clip, font_size=layout['font_size'], samples=samples,
                max_scroll=max_scroll, scroll=scroll, layout=layout)
    region.mixar_draw_glass(tuple(round(v) for v in (x, y, x_right, y_top)),
                           radius=TOAST_CORNER_RADIUS * scale, alpha=opacity)

    badge_radius = BADGE_RADIUS * scale
    close_size = layout['close_size']
    close_inset = layout['close_inset']
    center_y = y_top - close_inset - close_size * .5
    draw_circle(x + pad_x + badge_radius, center_y, badge_radius,
                _apply_opacity(colors['badge'], opacity))
    if item.dismissible:
        close_rect = (x_right - close_inset - close_size, y_top-close_inset-close_size,
                      close_size, close_size)
        hovered = toast_hover_state['key'] == ('close', item.id)
        bx, by, bw, bh = close_rect
        region.mixar_draw_card_close(tuple(round(v) for v in (bx, by, bx+bw, by+bh)),
                                      alpha=opacity, hovered=hovered)
        bounds['close'].append((item.id, *close_rect))

    for block in layout['blocks']:
        color = _apply_opacity(colors['title'], opacity) if block['kind'] == 'title' else text_color
        if block['kind'] == 'url':
            link = colors['link']
            if toast_hover_state['key'] == ('url', item.id):
                link = _hovered(link)
            color = _apply_opacity(link, opacity)
        top = content_top - block['top']
        _draw_lines(block['lines'], clip[0], top, layout['font_size'],
                    layout['line_height'], color, clip, samples, block['kind'],
                    font_id=block['font_id'])
        if block['kind'] == 'url':
            visible = _intersection((clip[0], top-block['height'], clip[2], block['height']), clip)
            if visible:
                bounds['url'].append((item.id, item.action_url, *visible))

    for button in layout['buttons']:
        action = button['action']
        bx = clip[0] + button['x']
        top = content_top - button['top']
        rect = (bx, top-button['height'], button['width'], button['height'])
        visible = _intersection(rect, clip)
        if not visible:
            continue
        style = colors.get('button_'+action.style, colors['button_secondary'])
        key = ('action', item.id, action.operator or action.url)
        fill = style['bg']
        if toast_pressed_state['key'] == key:
            fill = _pressed(fill)
        elif toast_hover_state['key'] == key:
            fill = _hovered(fill)
        draw_rounded_rect(*visible, BUTTON_CORNER_RADIUS*scale, _apply_opacity(fill, opacity))
        draw_rounded_rect_outline(*visible, BUTTON_CORNER_RADIUS*scale,
                                  _apply_opacity(style['border'], opacity),
                                  max(1.0, BUTTON_BORDER_WIDTH*scale))
        label_top = top - (button['height']-len(button['lines'])*layout['line_height']) * .5
        _draw_lines(button['lines'], bx, label_top, layout['font_size'],
                    layout['line_height'], _apply_opacity(style['text'], opacity),
                    clip, samples, 'action', button['width'], font_id=button['font_id'])
        bounds['action'].append((item.id, action.operator, action.url, *visible))

    if max_scroll > 0:
        track_h = clip[3]
        thumb_h = max(18*scale, track_h * track_h / layout['content_height'])
        thumb_y = clip[1] + (track_h-thumb_h) * (1-scroll/max_scroll)
        draw_rounded_rect(x_right-8*scale, thumb_y, 3*scale, thumb_h, 1.5*scale,
                          _apply_opacity((1, 1, 1, .5), opacity))
    return card


def _draw_toast_callback():
    region = bpy.context.region
    if region is None:
        return
    ptr = region.as_pointer()
    bounds = {'close': [], 'action': [], 'url': []}
    toast_bounds_by_region[ptr] = bounds
    cards = []
    toast_layouts_by_region[ptr] = cards
    toasts = get_notification_store().get_visible()
    scale = _scale()
    left, y_cursor, x_right, top = toast_lane(
        region, bpy.context.area, bpy.context.window_manager, scale)
    width = x_right - left
    # Leave enough room for a glyph plus the badge, close control and padding.
    if width < 180 * scale:
        return
    for item in toasts:
        available = top - y_cursor
        if available < 120 * scale:
            break
        layout = layout_toast(item, width, scale)
        height = min(layout['height'], available)
        card = _draw_single_toast(item, x_right, y_cursor + height, bounds, scale,
                                  width, available, region, layout)
        if card:
            cards.append(card)
            y_cursor += card['rect'][3] + TOAST_MARGIN * scale
    live_ids = {item.id for item in toasts}
    for key in list(toast_scroll_offsets):
        if key[0] == ptr and key[1] not in live_ids:
            del toast_scroll_offsets[key]


def install_draw_handler():
    if _draw_handle['handler'] is None:
        _draw_handle['handler'] = bpy.types.SpaceView3D.draw_handler_add(
            _draw_toast_callback, (), 'WINDOW', 'POST_PIXEL')


def remove_draw_handler():
    if _draw_handle['handler'] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle['handler'], 'WINDOW')
        _draw_handle['handler'] = None
    toast_bounds_by_region.clear()
    toast_layouts_by_region.clear()
    toast_scroll_offsets.clear()
    toast_hover_state['key'] = None
    toast_pressed_state['key'] = None
