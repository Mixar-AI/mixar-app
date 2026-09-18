# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Notifications must remain in the viewport beside later-painted panels."""

from types import SimpleNamespace

import pytest

from mixar.modules.common.notifications.toast_layout import toast_right_edge


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
