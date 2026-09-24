# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Popup-launched mask tools must use the canvas, never the 3D View2D."""

from contextlib import contextmanager
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from mixar.modules.moodboard.core import mask_tool_context


def _context(area_type, amount=1):
    region = NS(type='TOOL_PROPS' if area_type == 'VIEW_3D' else 'WINDOW',
                x=640, y=80, width=340)
    context = NS(area=NS(type=area_type, regions=[region]),
                 workspace=NS(name='Zen Mode'), region=NS(type='TEMP'),
                 window_manager=NS(mixar_moodboard_drawer_amount=amount))

    @contextmanager
    def override(**kwargs):
        original = context.region
        context.region = kwargs['region']
        try:
            yield
        finally:
            context.region = original

    context.temp_override = override
    return context, region


@pytest.mark.parametrize('host', ['MIXIE', 'VIEW_3D'])
def test_popup_events_use_window_coords_in_the_owning_canvas(monkeypatch, host):
    context, region = _context(host)

    def image_coords(ctx, event, index):
        assert ctx.region is region
        assert index == 2
        return event.mouse_region_x, event.mouse_region_y

    monkeypatch.setattr(mask_tool_context, '_image_coords', image_coords)
    event = NS(mouse_x=730, mouse_y=200, mouse_region_x=-99, mouse_region_y=-99)
    assert mask_tool_context.mouse_to_image_coords(context, event, 2) == (90, 120)
    assert context.region.type == 'TEMP'


@pytest.mark.parametrize('host,amount', [('VIEW_3D', 0), ('VIEW_3D', .5), ('IMAGE_EDITOR', 1)])
def test_inactive_host_never_uses_another_visible_board(monkeypatch, host, amount):
    context, _ = _context(host, amount)
    image_coords = Mock()
    monkeypatch.setattr(mask_tool_context, '_image_coords', image_coords)
    assert mask_tool_context.mouse_to_image_coords(context, NS(), 0) is None
    image_coords.assert_not_called()
