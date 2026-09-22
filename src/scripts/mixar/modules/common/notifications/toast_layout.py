# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Measured toast layout, shared by painting, input and QA targets."""

import bpy
import blf

from .constants import (
    BADGE_RADIUS, BUTTON_GAP, BUTTON_HEIGHT, BUTTON_PADDING_X,
    CLOSE_BUTTON_SIZE, CLOSE_BUTTON_INSET, TOAST_CORNER_OFFSET_X, TOAST_CORNER_OFFSET_Y,
    TOAST_PADDING_X, TOAST_PADDING_Y, TOAST_MARGIN,
)
from .core.typography import emphasis_font_id, text_measure

_FONT_ID = 0
_AUTHORED_SCALE = 2.0


def _scale() -> float:
    """Geometry constants use the original Retina pixel baseline."""
    try:
        return float(bpy.context.preferences.system.ui_scale) / _AUTHORED_SCALE
    except Exception:
        return 1.0


def body_font_size() -> float:
    """Exactly the Agent/native widget points times Blender's UI_SCALE_FAC."""
    prefs = bpy.context.preferences
    return float(prefs.ui_styles[0].widget.points) * float(prefs.system.ui_scale)


def _wrap_text(text, font_size, max_width, measure=None):
    """Preserve hard breaks and split overlong words/URLs at measured glyphs."""
    if not text:
        return []
    if measure is None:
        blf.size(_FONT_ID, font_size)
        measure = lambda value: blf.dimensions(_FONT_ID, value)[0]
    max_width = max(1.0, max_width)
    lines = []
    for paragraph in text.split('\n'):
        current = ''
        for word in paragraph.split():
            candidate = current + ' ' + word if current else word
            if measure(candidate) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ''
            while measure(word) > max_width and len(word) > 1:
                lo, hi = 1, len(word)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if measure(word[:mid]) <= max_width:
                        lo = mid
                    else:
                        hi = mid - 1
                lines.append(word[:lo])
                word = word[lo:]
            current = word
        lines.append(current)
    return lines


def layout_toast(item, width, scale, font_size=None, measure=None, emphasis_measure=None):
    """Lay out every label without truncation or width-dependent font scaling.

    Positions are relative to the padded content's top, increasing downward.
    The side rails reserve the badge and fixed close control while content
    scrolls. Actions retain their order and wrap into right-aligned rows.
    """
    font_size = body_font_size() if font_size is None else font_size
    bold_font = emphasis_font_id() if measure is None else _FONT_ID
    if measure is None:
        measure = text_measure(_FONT_ID, font_size)
    if emphasis_measure is None:
        emphasis_measure = text_measure(bold_font, font_size) if bold_font else measure
    pad_x, pad_y = TOAST_PADDING_X * scale, TOAST_PADDING_Y * scale
    close_size = CLOSE_BUTTON_SIZE * scale
    close_inset = CLOSE_BUTTON_INSET * scale
    badge_space = (BADGE_RADIUS * 2 + 10) * scale
    left = pad_x + badge_space
    right = close_inset + close_size + 10 * scale if item.dismissible else pad_x
    content_width = max(1.0, width - left - right)
    line_height = font_size * 1.35
    blocks, buttons = [], []
    cursor = 0.0
    for kind, text in (('title', item.title), ('body', item.body), ('url', item.action_url)):
        font_id = bold_font if kind == 'title' else _FONT_ID
        measure_block = emphasis_measure if kind == 'title' else measure
        lines = _wrap_text(text, font_size, content_width, measure_block)
        if not lines:
            continue
        if blocks:
            cursor += (20 if blocks[-1]['kind'] == 'title' else 10) * scale
        block = dict(kind=kind, text=text, lines=lines, top=cursor,
                     height=len(lines) * line_height, font_id=font_id)
        blocks.append(block)
        cursor += block['height']

    rows, row, row_width = [], [], 0.0
    gap = BUTTON_GAP * scale
    button_pad = min(BUTTON_PADDING_X * scale, content_width * .15)
    for action in item.actions:
        label_width = max(1.0, content_width - 2 * button_pad)
        lines = _wrap_text(action.label, font_size, label_width, emphasis_measure) or ['']
        button_width = min(content_width, max(emphasis_measure(line) for line in lines) + 2 * button_pad)
        button_height = max(BUTTON_HEIGHT * scale, len(lines) * line_height + 16 * scale)
        if row and row_width + gap + button_width > content_width:
            rows.append(row)
            row, row_width = [], 0.0
        row.append(dict(action=action, lines=lines, width=button_width,
                        height=button_height, font_id=bold_font))
        row_width += (gap if len(row) > 1 else 0) + button_width
    if row:
        rows.append(row)
    if rows and blocks:
        cursor += 18 * scale
    for row in rows:
        height = max(button['height'] for button in row)
        x = content_width - sum(button['width'] for button in row) - gap * (len(row) - 1)
        for button in row:
            button.update(x=x, top=cursor, height=height)
            buttons.append(button)
            x += button['width'] + gap
        cursor += height + gap
    if rows:
        cursor -= gap
    return dict(width=width, height=max(cursor, close_size) + 2 * pad_y,
                content_height=cursor, content_x=left, content_width=content_width,
                pad_x=pad_x, pad_y=pad_y, close_size=close_size, close_inset=close_inset,
                font_size=font_size, line_height=line_height, blocks=blocks, buttons=buttons)


def toast_right_edge(region, area, wm, scale):
    """Use native region bounds so the drawer/sidebar cannot paint over toasts.

    The drawer reserves its full region for the duration of its slide. Its
    open amount gates that reservation; no canvas geometry is reconstructed.
    """
    edge = region.x + region.width
    drawer_open = getattr(wm, "mixar_moodboard_drawer_amount", 0.0) > 0.0
    for overlay in area.regions:
        if overlay.width <= 1 or overlay.x <= region.x:
            continue
        if overlay.type == 'UI' or (overlay.type == 'TOOL_PROPS' and drawer_open):
            edge = min(edge, overlay.x)
    return edge - region.x - TOAST_CORNER_OFFSET_X * scale


def toast_lane(region, area, wm, scale):
    """Align to the native card column; never reconstruct C++ card metrics.

    The stack reserves its settled band through arrival and departure. Toasts
    grow upward from it, newest nearest the agents; an empty stack returns the
    same left edge and a resting bottom anchor.
    """
    left, bottom, right, top, ceiling = region.mixar_agent_panel_bounds()
    right = min(right, toast_right_edge(region, area, wm, scale))
    bottom = top + TOAST_MARGIN * scale if top > bottom else bottom
    return left, bottom, right, min(ceiling, region.height - TOAST_CORNER_OFFSET_Y * scale)
