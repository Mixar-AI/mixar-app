# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compact is the chrome host; UI.svg and card_row sizes stay."""

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
SETTINGS = (
    ROOT
    / "src/scripts/mixar/modules/agent_bubble/ui/operators/pane_settings_ops.py"
)
CARD = INTERFACE / "interface_mixar_profile_card.cc"
TOKENS = INCLUDE / "UI_mixar_tokens.hh"


def test_chrome_hosts_use_compact_without_resizing_controls():
    from mixar.modules.common.ui.constants import (
        CARD_ROW_ACTION,
        DENSITY_COMPACT_HEIGHT,
        DENSITY_COMPACT_SCALE,
        DENSITY_DEFAULT_HEIGHT,
    )

    chrome = (INCLUDE / "UI_mixar_chrome.hh").read_text(encoding="utf-8")
    tokens = TOKENS.read_text(encoding="utf-8")
    card = CARD.read_text(encoding="utf-8")
    gallery = GALLERY.read_text(encoding="utf-8")
    settings = SETTINGS.read_text(encoding="utf-8")
    assert "inline constexpr MixarDensity density = MixarDensity::Compact;" in chrome
    assert "inline constexpr float card_row_action = 1.9f;" in chrome
    assert CARD_ROW_ACTION == 1.9
    assert DENSITY_DEFAULT_HEIGHT == 44.0
    assert DENSITY_COMPACT_HEIGHT == 32.0
    assert DENSITY_COMPACT_SCALE == pytest.approx(32.0 / 44.0)
    assert "compact_density" in tokens
    assert "mixar_density_unscaled(MixarDensity::Default)" in tokens
    assert "scope.density = mixar_chrome::density" in card
    assert "ROW_ACTION = mixar_chrome::card_row_action" in card
    assert 'density="COMPACT"' in gallery
    assert "DENSITY_COMPACT_SCALE" in gallery
    assert 'density=\'COMPACT\'' in settings
    assert "surface.scale_y" not in settings
    preview = gallery[gallery.index("def _draw_chrome_preview") :]
    preview = preview[: preview.index("\ndef ", 1)]
    assert "scale_y =" not in preview
    assert "DENSITY_COMPACT_SCALE" not in preview


def test_chrome_density_tokens_compile(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    source = tmp_path / "chrome_density.cc"
    source.write_text(
        r'''
#include "UI_mixar_chrome.hh"
#include "UI_mixar_density.hh"
#include <cassert>
using namespace blender::ui;
int main() {
  assert(mixar_chrome::density == MixarDensity::Compact);
  assert(mixar_density_unscaled(mixar_chrome::density).control_height == 32.0f);
  assert(mixar_density_unscaled(MixarDensity::Default).control_height == 44.0f);
  assert(mixar_density_scale(mixar_chrome::density) == 32.0f / 44.0f);
  assert(mixar_chrome::card_row_action == 1.9f);
}
'''
    )
    binary = tmp_path / "chrome_density"
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
