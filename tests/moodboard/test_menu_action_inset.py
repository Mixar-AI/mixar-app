# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Zen actions inside dropdown menus stay inside the menu's rounded outline.

The Moodboard ``+`` template menu, Shift+A Add menu and Board menu style their
rows as ``ACTION`` buttons. Painted at the full row width, a hovered row's
rounded fill met the menu border and its corners fought the menu's own. The
painter now pads the row by the menu padding and keeps its corners concentric
with the themed menu roundness; the native text pass shares the padded rect.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTERFACE = ROOT / "src/source/blender/editors/interface"
COMPONENTS = (INTERFACE / "mixar/components.cc").read_text(encoding="utf-8")
WIDGETS = (INTERFACE / "interface_widgets.cc").read_text(encoding="utf-8")
HEADER = (ROOT / "src/source/blender/editors/include/UI_mixar.hh").read_text(encoding="utf-8")


def _body(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}\n", start)]


def test_inset_applies_only_to_zen_actions_in_dropdown_menus():
    body = _body(COMPONENTS, "float mixar_menu_item_inset(const Button &button)")
    assert "MixarComponent::Action" in body
    assert "MixarTheme::Zen" in body
    assert "!block_is_menu(block)" in body
    assert "block_is_pie_menu(block)" in body
    assert "UI_MENU_PADDING" in body
    assert "float mixar_menu_item_inset(const Button &button);" in HEADER


def test_menu_action_radius_is_concentric_with_the_menu():
    body = _body(COMPONENTS, "bool mixar_component_draw(")
    assert "tui.wcol_menu_back.roundness" in body
    assert "menu_radius - menu_inset" in body
    assert "MX_R_SM * UI_SCALE_FAC" in body


def test_fill_and_native_text_share_the_padded_rect():
    start = WIDGETS.index("  else if (mixar_component) {\n    /* Menu actions")
    branch = WIDGETS[start:WIDGETS.index("native_text = mixar_component_draw", start)]
    assert "mixar_menu_item_inset(*but)" in branch
    assert "BLI_rcti_pad(rect, -menu_inset, 0);" in branch
