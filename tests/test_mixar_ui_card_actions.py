# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Phase 4 card action recipes preserve the existing profile/dialog look."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ROOT / "src/source/blender/editors/include"
INTERFACE = ROOT / "src/source/blender/editors/interface"
GALLERY = (
    ROOT / "src/scripts/mixar/modules/common/ui/panels/ui_gallery_panel.py"
)
BUTTON = INTERFACE / "interface_mixar_card_button.cc"
PAINT = INTERFACE / "interface_mixar_card_paint.hh"


def test_card_actions_use_named_chrome_recipes():
    chrome = (INCLUDE / "UI_mixar_chrome.hh").read_text(encoding="utf-8")
    button = BUTTON.read_text(encoding="utf-8")
    paint = PAINT.read_text(encoding="utf-8")
    gallery = GALLERY.read_text(encoding="utf-8")
    assert "inline constexpr float card_action_label_scale = 1.0f;" in chrome
    assert "inline constexpr float card_accent_fill = 0.22f;" in chrome
    assert "inline constexpr float card_danger_fill = 0.12f;" in chrome
    assert "inline constexpr float card_press_wash = 0.15f;" in chrome
    assert "mixar_chrome::card_accent_fill" in button
    assert "mixar_chrome::card_danger_fill_hover" in button
    assert "mixar_card_font(mixar_chrome::card_action_label_scale, 0)" in button
    assert "0.32f" not in button
    assert "0.22f" not in button
    for name in (
        "MIXAR_CARD_BUTTON_INSET",
        "MIXAR_CARD_BUTTON_PAD",
        "MIXAR_CARD_BUTTON_ICON",
        "MIXAR_CARD_BUTTON_ICON_GAP",
    ):
        assert name in paint
    preview = gallery[gallery.index("def _draw_card_actions_preview") :]
    preview = preview[: preview.index("\ndef ", 1)]
    assert "mixar_card_button" in preview
    assert '"ACCENT"' in preview
    assert '"GHOST"' in preview
    assert "scale_y =" not in preview


def test_card_action_tokens_compile(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    source = tmp_path / "card_actions.cc"
    source.write_text(
        r'''
#include "UI_mixar_chrome.hh"
#include <cassert>
using namespace blender::ui::mixar_chrome;
int main() {
  assert(card_action_label_scale == 1.0f);
  assert(card_accent_fill == 0.22f && card_accent_fill_hover == 0.32f);
  assert(card_accent_outline == 0.55f && card_accent_outline_hover == 0.85f);
  assert(card_danger_fill == 0.12f && card_danger_fill_hover == 0.18f);
  assert(card_danger_outline == 0.35f && card_danger_outline_hover == 0.55f);
  assert(card_outline == 1.0f && card_press_wash == 0.15f);
}
'''
    )
    binary = tmp_path / "card_actions"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-I",
            str(INCLUDE),
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True)
