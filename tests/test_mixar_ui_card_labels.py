# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Phase 4 card label recipes preserve the existing profile/dialog look."""

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
CONSTANTS = ROOT / "src/scripts/mixar/modules/common/ui/constants.py"
BYOK = (
    ROOT / "src/scripts/mixar/modules/byok/ui/operators/byok_dialog_ui.py"
)
DRAW = INTERFACE / "interface_mixar_profile_card_draw.cc"
CARD = INTERFACE / "interface_mixar_profile_card.cc"
PAINT = INTERFACE / "interface_mixar_card_paint.hh"


def test_card_labels_use_named_chrome_recipes():
    from mixar.modules.common.ui.constants import CARD_ROW_DIVIDER, CARD_ROW_HEADING

    chrome = (INCLUDE / "UI_mixar_chrome.hh").read_text(encoding="utf-8")
    draw = DRAW.read_text(encoding="utf-8")
    card = CARD.read_text(encoding="utf-8")
    paint = PAINT.read_text(encoding="utf-8")
    gallery = GALLERY.read_text(encoding="utf-8")
    constants = CONSTANTS.read_text(encoding="utf-8")
    byok = BYOK.read_text(encoding="utf-8")
    assert "inline constexpr float card_heading_scale = 1.45f;" in chrome
    assert "inline constexpr int card_heading_weight = 700;" in chrome
    assert "inline constexpr float card_pill_radius = 0.35f;" in chrome
    assert "inline constexpr float card_row_heading = 1.6f;" in chrome
    assert "inline constexpr float card_row_divider = 0.6f;" in chrome
    assert CARD_ROW_HEADING == 1.6
    assert CARD_ROW_DIVIDER == 0.6
    assert 'CARD_ROW_HEADING = 1.6' in constants
    assert "mixar_chrome::card_heading_scale" in draw
    assert "mixar_chrome::card_heading_weight" in draw
    assert "mixar_chrome::card_pill_radius" in draw
    assert "1.45f" not in draw
    assert "0.35f" not in draw
    assert "mixar_chrome::card_row_heading" in card
    assert "mixar_chrome::card_row_divider" in card
    assert "MIXAR_CARD_PILL_SCALE" in paint
    assert "MIXAR_CARD_PILL_PAD" in paint
    assert "MIXAR_CARD_PILL_HEIGHT" in paint
    assert "CARD_ROW_HEADING" in byok
    assert "CARD_ROW_DIVIDER" in byok
    preview = gallery[gallery.index("def _draw_card_labels_preview") :]
    preview = preview[: preview.index("\ndef ", 1)]
    assert 'kind="HEADING"' in preview
    assert 'kind="PILL"' in preview
    assert 'kind="DIVIDER"' in preview
    assert "scale_y =" not in preview


def test_card_label_tokens_compile(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    source = tmp_path / "card_labels.cc"
    source.write_text(
        r'''
#include "UI_mixar_chrome.hh"
#include <cassert>
using namespace blender::ui::mixar_chrome;
int main() {
  assert(card_heading_scale == 1.45f && card_heading_weight == 700);
  assert(card_pill_radius == 0.35f);
  assert(card_row_heading == 1.6f && card_row_divider == 0.6f);
}
'''
    )
    binary = tmp_path / "card_labels"
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
