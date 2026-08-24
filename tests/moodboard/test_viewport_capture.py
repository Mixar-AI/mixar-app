# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Viewport capture selects only the new moodboard still."""

from types import SimpleNamespace

from mixar.modules.moodboard.core.viewport_capture import (
    find_view3d_context,
    select_only_moodboard_item,
)


def test_select_only_moodboard_item_deselects_siblings():
    keep = SimpleNamespace(selected=False)
    drop = SimpleNamespace(selected=True)
    scene = SimpleNamespace(mixie_moodboard_images=[drop, keep])
    select_only_moodboard_item(scene, keep)
    assert keep.selected is True
    assert drop.selected is False


def test_find_view3d_context_prefers_current_area():
    region = SimpleNamespace(type="WINDOW")
    space = SimpleNamespace()
    area = SimpleNamespace(
        type="VIEW_3D",
        regions=[region],
        spaces=SimpleNamespace(active=space),
        width=100,
        height=100,
    )
    window = SimpleNamespace()
    context = SimpleNamespace(
        area=area,
        window=window,
        window_manager=SimpleNamespace(windows=()),
    )
    found = find_view3d_context(context)
    assert found == (window, area, region, space)


def test_find_view3d_context_returns_none_without_viewport():
    context = SimpleNamespace(
        area=SimpleNamespace(type="VIEW_2D", regions=[]),
        window=None,
        window_manager=SimpleNamespace(windows=()),
    )
    assert find_view3d_context(context) is None
