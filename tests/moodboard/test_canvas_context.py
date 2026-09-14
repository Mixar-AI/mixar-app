# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Moodboard dialogs and background updates work on both canvas hosts."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from mixar.modules.moodboard.core import canvas_context


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
