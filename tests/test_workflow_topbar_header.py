# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Execute the startup header while deferred workspace UI is registering."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.modules.workflow.ui.headers import mode_filter_header as header


@pytest.mark.parametrize("menu_registered", [False, True])
def test_engine_tabs_and_mode_switch_draw_before_and_after_menu_registration(
    monkeypatch, menu_registered
):
    types = SimpleNamespace(TOPBAR_MT_editor_menus=MagicMock())
    if menu_registered:
        types.MIXAR_MT_engine_workspaces = object()
    monkeypatch.setattr(header.bpy, "types", types)
    slider = MagicMock()
    monkeypatch.setattr(header, "_draw_mode_slider", slider)
    layout = MagicMock()
    context = SimpleNamespace(
        window=object(), screen=SimpleNamespace(show_fullscreen=False),
        workspace=SimpleNamespace(name="Layout"),
    )

    header._patched_draw_left(SimpleNamespace(layout=layout), context)

    layout.separator.assert_called_once_with()
    layout.template_ID_tabs.assert_called_once_with(
        context.window, "workspace", new="workspace.add", menu="TOPBAR_MT_workspace_menu"
    )
    slider.assert_called_once_with(layout, context)
    if menu_registered:
        layout.menu.assert_called_once_with(
            "MIXAR_MT_engine_workspaces", text="", icon="WORKSPACE"
        )
    else:
        layout.menu.assert_not_called()
