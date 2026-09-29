# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Engine workspace tabs overflow into a dropdown instead of hiding the "+".

Native layout (`interface_mixar_topbar_tabs.cc`) fits the tabs into the lane
left of the centred Zen/Engine switch, keeps the New Workspace "+" and the
overflow dropdown right after the last visible tab, and hands the hidden
workspaces to the dropdown's Python draw as context pointers.
"""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

from mixar.modules.workflow.ui.headers import mode_filter_header as header
from mixar.modules.workflow.ui.menus import engine_workspaces

ROOT = Path(__file__).resolve().parents[1]
INTERFACE = ROOT / "src/source/blender/editors/interface"
TABS = (INTERFACE / "interface_mixar_topbar_tabs.cc").read_text(encoding="utf-8")


def _fit_body():
    body = TABS[TABS.index("void mixar_topbar_fit_workspace_tabs("):]
    return body[:body.index("\n}\n")]


def test_header_draws_the_overflow_dropdown_after_the_tabs(monkeypatch):
    types = SimpleNamespace(
        TOPBAR_MT_editor_menus=MagicMock(),
        MIXAR_MT_engine_workspaces=object(),
        MIXAR_MT_workspace_overflow=object(),
    )
    monkeypatch.setattr(header.bpy, "types", types)
    monkeypatch.setattr(header, "_draw_mode_slider", MagicMock())
    layout = MagicMock()
    context = SimpleNamespace(
        window=object(), screen=SimpleNamespace(show_fullscreen=False),
        workspace=SimpleNamespace(name="Layout"),
    )

    header._patched_draw_left(SimpleNamespace(layout=layout), context)

    names = [c[0] for c in layout.method_calls]
    assert names.index("template_ID_tabs") < names.index("menu", names.index("template_ID_tabs"))
    assert layout.menu.call_args_list[-1] == call(
        "MIXAR_MT_workspace_overflow", text="", icon="DOWNARROW_HLT"
    )


def test_zen_draws_no_tab_strip_or_dropdown(monkeypatch):
    types = SimpleNamespace(
        TOPBAR_MT_editor_menus=MagicMock(), MIXAR_MT_workspace_overflow=object(),
    )
    monkeypatch.setattr(header.bpy, "types", types)
    monkeypatch.setattr(header, "_draw_mode_slider", MagicMock())
    layout = MagicMock()
    context = SimpleNamespace(
        window=object(), screen=SimpleNamespace(show_fullscreen=False),
        workspace=SimpleNamespace(name=header.BASIC_WORKSPACE_NAME),
    )

    header._patched_draw_left(SimpleNamespace(layout=layout), context)

    layout.template_ID_tabs.assert_not_called()
    layout.menu.assert_not_called()


def test_overflow_workspaces_reads_the_native_context_in_tab_order():
    first, second = object(), object()
    prefix = engine_workspaces.OVERFLOW_CONTEXT_PREFIX
    context = SimpleNamespace(**{f"{prefix}0": first, f"{prefix}1": second})

    assert engine_workspaces.overflow_workspaces(context) == [first, second]
    assert engine_workspaces.overflow_workspaces(SimpleNamespace()) == []


def test_python_and_native_share_the_menu_and_context_names():
    assert 'OVERFLOW_MENU_IDNAME = "MIXAR_MT_workspace_overflow"' in TABS
    prefix = engine_workspaces.OVERFLOW_CONTEXT_PREFIX
    assert f'OVERFLOW_CONTEXT_PREFIX = "{prefix}"' in TABS
    assert "button_context_ptr_set(block, overflow, name, &ptr)" in _fit_body()
    menus = (ROOT / "src/scripts/mixar/modules/workflow/ui/menus/engine_workspaces.py").read_text()
    assert "class MIXAR_MT_workspace_overflow(bpy.types.Menu)" in menus
    assert re.search(r"classes = \(.*MIXAR_MT_workspace_overflow.*\)", menus)


def test_plus_and_dropdown_follow_the_last_visible_tab():
    body = _fit_body()
    # Tabs are laid out first, then "+", then the dropdown — never past the lane.
    place_tab = body.index("place_x(tab, x)")
    place_add = body.index("place_x(*add, x)")
    place_overflow = body.index("place_x(*overflow, x)")
    assert place_tab < place_add < place_overflow
    # The budget reserves both before choosing which tabs stay.
    assert "span - add_width - (overflow ? gap + overflow_width : 0.0f)" in body
    # The dropdown only shows while some tab is hidden.
    assert "if (!overflows) {\n    overflow->flag |= UI_HIDDEN;" in body


def test_padding_gives_way_before_any_tab_hides():
    body = _fit_body()
    assert "TAB_PADDING_TRIM_PX * UI_SCALE_FAC" in body
    assert body.index("TAB_PADDING_TRIM_PX") < body.index("visible_tabs(")


def test_active_workspace_keeps_its_tab():
    fit = TABS[TABS.index("Vector<bool> visible_tabs("):TABS.index("}  // namespace")]
    assert "CTX_wm_workspace(C)" in _fit_body()
    # Trailing tabs give way until the active one fits in their place.
    assert "while (count > 0 && used + active_cost > budget)" in fit
    assert "visible[active] = true;" in fit


def test_new_source_is_built():
    cmake = (INTERFACE / "CMakeLists.txt").read_text()
    assert "  interface_mixar_topbar_tabs.cc\n" in cmake


def test_plus_is_never_counted_as_a_workspace_tab():
    # template_ID_tabs builds "+" as a Tab button (use_tab_but), so the
    # New Workspace test must win before the Tab test or "+" overflows away.
    body = _fit_body()
    assert body.index("is_new_workspace_button(but)") < body.index("ButtonType::Tab")
    assert "but.type == ButtonType::Tab && but.custom_data" in body


def test_dropdown_offers_new_workspace():
    menus = (ROOT / "src/scripts/mixar/modules/workflow/ui/menus/engine_workspaces.py").read_text()
    overflow = menus[menus.index("class MIXAR_MT_workspace_overflow"):]
    assert 'operator("workspace.add", text="New Workspace", icon=\'ADD\')' in overflow
