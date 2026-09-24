# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Notifications must remain in the viewport beside later-painted panels."""

from types import SimpleNamespace

import pytest

from mixar.modules.common.notifications.toast_layout import toast_right_edge
from mixar.modules.common.notifications import toast_layout
from mixar.modules.common.notifications.store import NotificationAction


@pytest.mark.parametrize('scale', [1.0, 1.25, 2.0])
def test_drawer_and_sidebar_bound_toast_placement(scale):
    viewport = SimpleNamespace(x=120, width=2400)
    drawer = SimpleNamespace(type='TOOL_PROPS', x=1840, width=680)
    sidebar = SimpleNamespace(type='UI', x=2200, width=320)
    area = SimpleNamespace(regions=[drawer, sidebar])
    wm = SimpleNamespace(mixar_moodboard_drawer_amount=1.0)
    assert toast_right_edge(viewport, area, wm, scale) == 1840-120-28*scale
    wm.mixar_moodboard_drawer_amount = 0.0
    assert toast_right_edge(viewport, area, wm, scale) == 2200-120-28*scale
    sidebar.width = 1
    assert toast_right_edge(viewport, area, wm, scale) == 2400-28*scale


def test_partial_drawer_reserves_its_region_and_left_panels_are_ignored():
    viewport = SimpleNamespace(x=0, width=2400)
    area = SimpleNamespace(regions=[SimpleNamespace(type='TOOL_PROPS', x=1720, width=680),
                                   SimpleNamespace(type='UI', x=0, width=300)])
    wm = SimpleNamespace(mixar_moodboard_drawer_amount=0.25)
    assert toast_right_edge(viewport, area, wm, 1.0) == 1692


@pytest.mark.parametrize('scale', [.5, 1.0, 1.5])
@pytest.mark.parametrize('stack_top', [14, 102, 186])
def test_notifications_follow_native_stack_and_grow_into_free_space(scale, stack_top):
    viewport = SimpleNamespace(x=120, width=1000, height=700,
                                mixar_agent_panel_bounds=lambda: (24, 14, 344, stack_top, 700))
    area = SimpleNamespace(regions=[])
    wm = SimpleNamespace(mixar_moodboard_drawer_amount=0.0)
    left, bottom, right, top = toast_layout.toast_lane(viewport, area, wm, scale)
    assert (left, right) == (24, 344)
    assert bottom == (14 if stack_top == 14 else stack_top + 16 * scale)
    assert top == 700 - 28 * scale


def test_notification_lane_clamps_to_drawer_without_moving_left_edge():
    viewport = SimpleNamespace(x=100, width=500, height=450,
                                mixar_agent_panel_bounds=lambda: (24, 14, 344, 186, 450))
    area = SimpleNamespace(regions=[SimpleNamespace(type='TOOL_PROPS', x=400, width=200)])
    wm = SimpleNamespace(mixar_moodboard_drawer_amount=1.0)
    assert toast_layout.toast_lane(viewport, area, wm, 1.0) == (24, 202, 272, 422)


def test_long_notification_stays_below_native_toolbar():
    viewport = SimpleNamespace(x=0, width=1000, height=700,
                                mixar_agent_panel_bounds=lambda: (24, 14, 344, 186, 400))
    area = SimpleNamespace(regions=[])
    wm = SimpleNamespace(mixar_moodboard_drawer_amount=0.0)
    assert toast_layout.toast_lane(viewport, area, wm, 1.0) == (24, 202, 344, 400)


def test_wrapping_preserves_paragraphs_and_breaks_unspaced_urls():
    text = 'A short line\n\nhttps://example.test/' + 'identifier' * 18
    measure = lambda value: len(value) * 12
    lines = toast_layout._wrap_text(text, 24, 132, measure)
    assert lines[:3] == ['A short', 'line', '']
    assert ''.join(''.join(lines).split()) == ''.join(text.split())
    assert all(measure(line) <= 132 for line in lines)


@pytest.mark.parametrize('width', [220, 360, 600, 750])
@pytest.mark.parametrize('font_size', [24, 30, 37.5])
def test_every_label_wraps_inside_its_actual_content_budget(width, font_size):
    measure = lambda value: len(value) * font_size * .5
    item = SimpleNamespace(
        title='A notification title that must wrap before the close button',
        body='First paragraph\n\nSecond paragraph with ' + 'a' * 60,
        action_url='https://example.test/' + 'path' * 40, dismissible=True,
        actions=[NotificationAction('Review generation settings', 'qa.review'),
                 NotificationAction('Continue with selected settings', 'qa.continue', 'primary')])
    layout = toast_layout.layout_toast(item, width, 1.0, font_size, measure)
    assert layout['font_size'] == font_size
    assert layout['content_x'] + layout['content_width'] <= width-layout['close_inset']-layout['close_size']
    for block in layout['blocks']:
        assert all(measure(line) <= layout['content_width'] for line in block['lines'])
    for button in layout['buttons']:
        assert button['x'] >= 0
        assert button['x'] + button['width'] <= layout['content_width'] + 1e-6
        assert all(measure(line) <= button['width'] for line in button['lines'])
    first, second = layout['buttons']
    assert second['top'] >= first['top'] + first['height'] or second['x'] >= first['x'] + first['width']


def test_font_follows_native_widget_preferences_without_rounding(monkeypatch):
    prefs = SimpleNamespace(ui_styles=[SimpleNamespace(widget=SimpleNamespace(points=15))],
                            system=SimpleNamespace(ui_scale=2.5))
    monkeypatch.setattr(toast_layout.bpy, 'context', SimpleNamespace(preferences=prefs))
    assert toast_layout.body_font_size() == 37.5


def test_bold_headings_and_buttons_wrap_using_their_wider_glyphs():
    regular = lambda value: len(value) * 8
    bold = lambda value: len(value) * 14
    item = SimpleNamespace(title='Review generation options', body='Review generation options',
                           action_url=None, dismissible=True,
                           actions=[NotificationAction('Continue with selected settings', 'qa.continue')])
    layout = toast_layout.layout_toast(item, 400, 1.0, 24, regular, bold)
    title, body = layout['blocks']
    assert len(title['lines']) > len(body['lines'])
    assert all(bold(line) <= layout['content_width'] for line in title['lines'])
    assert body['top'] - title['height'] == 20
    button = layout['buttons'][0]
    assert all(bold(line) + 2 * toast_layout.BUTTON_PADDING_X <= button['width'] + 1e-6
               for line in button['lines'])


def test_scroll_is_bounded_and_only_consumed_inside_overflowing_cards():
    from mixar.modules.common.notifications import toast_renderer as renderer
    ptr = 43210
    renderer.toast_layouts_by_region[ptr] = [dict(id='qa-scroll', rect=(10, 20, 200, 300), max_scroll=100)]
    try:
        assert not renderer.scroll_toast(ptr, 0, 0, 50)
        assert renderer.scroll_toast(ptr, 30, 40, 500)
        assert renderer.toast_scroll_offsets[(ptr, 'qa-scroll')] == 100
        assert renderer.scroll_toast(ptr, 30, 40, -500)
        assert renderer.toast_scroll_offsets[(ptr, 'qa-scroll')] == 0
        renderer.toast_layouts_by_region[ptr][0]['max_scroll'] = 0
        assert not renderer.scroll_toast(ptr, 30, 40, 20)
    finally:
        renderer.toast_layouts_by_region.pop(ptr)
        renderer.toast_scroll_offsets.pop((ptr, 'qa-scroll'), None)
