# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Moodboard dialogs and background updates work on both canvas hosts."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from mixar.modules.moodboard.core import canvas_context


def test_clear_is_offered_for_every_board_collection():
    empty = NS(scene=NS())
    assert canvas_context.has_moodboard_content(empty) is False
    for name in canvas_context.MOODBOARD_CONTENT_COLLECTIONS:
        assert name.startswith("mixie_moodboard_")
        scene = NS(**{name: [object()]})
        assert canvas_context.has_moodboard_content(NS(scene=scene)) is True


@pytest.mark.parametrize(
    "space,workspace,region,amount,expected",
    [
        ("MIXIE", "Layout", "WINDOW", 0, True),
        ("VIEW_3D", "Zen Mode", "TOOL_PROPS", 1, True),
        ("VIEW_3D", "Zen Mode", "TEMP", 1, True),
        ("VIEW_3D", "Zen Mode", "TOOL_PROPS", 0.5, False),
        ("VIEW_3D", "Zen Mode", "WINDOW", 1, False),
        ("VIEW_3D", "Layout", "TOOL_PROPS", 1, False),
    ],
)
def test_menu_context_matches_the_visible_canvas(space, workspace, region, amount, expected):
    context = NS(
        space_data=NS(type=space), workspace=NS(name=workspace), region=NS(type=region),
        window_manager=NS(mixar_moodboard_drawer_amount=amount),
    )
    assert canvas_context.is_moodboard_context(context) is expected


def test_find_canvas_region_prefers_the_open_drawer():
    drawer = NS(type="TOOL_PROPS", width=340, view2d=object())
    mixie_window = NS(type="WINDOW", width=800, view2d=object())
    view = NS(type="VIEW_3D", regions=[drawer])
    editor = NS(type="MIXIE", regions=[mixie_window])
    wm = NS(
        mixar_moodboard_drawer_amount=1.0,
        windows=[NS(screen=NS(areas=[view, editor]))],
    )
    context = NS(
        region=None,
        space_data=None,
        window_manager=wm,
    )
    assert canvas_context.find_moodboard_canvas_region(context) is drawer


@pytest.mark.parametrize("amount,expected_drawer_redraws", [(0, 0), (0.5, 1), (1, 1)])
def test_updates_redraw_only_the_drawer_not_the_3d_scene(monkeypatch, amount, expected_drawer_redraws):
    viewport = NS(type="WINDOW", tag_redraw=Mock())
    drawer = NS(type="TOOL_PROPS", tag_redraw=Mock())
    view = NS(type="VIEW_3D", regions=[viewport, drawer], tag_redraw=Mock())
    editor = NS(type="MIXIE", tag_redraw=Mock())
    window = NS(workspace=NS(name="Zen Mode"), screen=NS(areas=[view, editor]))
    monkeypatch.setattr(canvas_context, "bpy", NS(context=NS(window_manager=NS(
        windows=[window], mixar_moodboard_drawer_amount=amount,
    ))))
    canvas_context.redraw_moodboard_canvases()
    assert drawer.tag_redraw.call_count == expected_drawer_redraws
    viewport.tag_redraw.assert_not_called()
    view.tag_redraw.assert_not_called()
    editor.tag_redraw.assert_called_once()
