# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Phase 4 dialog field/footer/grid row scales preserve existing rhythm."""

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
CARD = INTERFACE / "interface_mixar_profile_card.cc"


def test_card_rows_use_named_chrome_recipes():
    from mixar.modules.common.ui.constants import (
        CARD_ROW_ACTION,
        CARD_ROW_CTA,
        CARD_ROW_FIELD,
    )

    chrome = (INCLUDE / "UI_mixar_chrome.hh").read_text(encoding="utf-8")
    card = CARD.read_text(encoding="utf-8")
    gallery = GALLERY.read_text(encoding="utf-8")
    constants = CONSTANTS.read_text(encoding="utf-8")
    byok = BYOK.read_text(encoding="utf-8")
    assert "inline constexpr float card_row_field = 1.45f;" in chrome
    assert "inline constexpr float card_row_cta = 1.7f;" in chrome
    assert "inline constexpr float card_row_action = 1.9f;" in chrome
    assert CARD_ROW_FIELD == 1.45
    assert CARD_ROW_CTA == 1.7
    assert CARD_ROW_ACTION == 1.9
    assert "CARD_ROW_FIELD = 1.45" in constants
    assert "CARD_ROW_CTA = 1.7" in constants
    assert "CARD_ROW_ACTION = 1.9" in constants
    assert "mixar_chrome::card_row_field" not in card
    assert "mixar_chrome::card_row_cta" in card
    assert "mixar_chrome::card_row_action" in card
    assert "ROW_USAGE_BAR = 1.5f" in card
    assert "CARD_ROW_FIELD" in byok
    assert "CARD_ROW_CTA" in byok
    assert "ACTION_SCALE_Y = CARD_ROW_CTA" in byok
    preview = gallery[gallery.index("def _draw_card_rows_preview") :]
    preview = preview[: preview.index("\ndef ", 1)]
    assert "CARD_ROW_FIELD" in preview
    assert "CARD_ROW_CTA" in preview
    assert "CARD_ROW_ACTION" in preview
    assert '"Footer"' in preview
    assert '"Confirm"' in preview
    assert '"Grid"' in preview
    assert "32.0 / 44.0" not in preview


def test_card_row_tokens_compile(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    source = tmp_path / "card_rows.cc"
    source.write_text(
        r'''
#include "UI_mixar_chrome.hh"
#include <cassert>
using namespace blender::ui::mixar_chrome;
int main() {
  assert(card_row_field == 1.45f && card_row_cta == 1.7f);
  assert(card_row_action == 1.9f);
}
'''
    )
    binary = tmp_path / "card_rows"
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
