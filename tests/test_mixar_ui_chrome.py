# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Phase 4 chrome tokens preserve the existing topbar recipe."""

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


def test_topbar_and_cinema_use_shared_chrome_scales():
    chrome = (INCLUDE / "UI_mixar_chrome.hh").read_text(encoding="utf-8")
    topbar = (INTERFACE / "interface_mixar_topbar.cc").read_text(encoding="utf-8")
    cinema = (INTERFACE / "interface_mixar_cinema_row.cc").read_text(encoding="utf-8")
    profile = (INTERFACE / "interface_mixar_profile_card_draw.cc").read_text(
        encoding="utf-8"
    )
    gallery = GALLERY.read_text(encoding="utf-8")
    assert "inline constexpr float label_scale = 0.95f;" in chrome
    assert "inline constexpr float caption_scale = 0.90f;" in chrome
    assert "mixar_chrome::slider_track" in topbar
    assert "mixar_card_font(label_scale, 0)" in topbar
    assert "mixar_card_font(mixar_chrome::label_scale, 0)" in cinema
    assert "mixar_card_font(mixar_chrome::caption_scale, 0)" in cinema
    assert "mixar_card_font(mixar_chrome::caption_scale, 0)" in profile
    preview = gallery[gallery.index("def _draw_chrome_preview") :]
    preview = preview[: preview.index("\ndef ", 1)]
    assert '"CINEMA_PILL"' in preview
    assert '"MODE_SLIDER_LEFT"' in preview
    assert "scale_y =" not in preview
    assert "_chrome_host" in preview


def test_chrome_tokens_match_the_ui_svg_recipe(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    source = tmp_path / "chrome.cc"
    source.write_text(
        r'''
#include "UI_mixar_chrome.hh"
#include <cassert>
using namespace blender::ui::mixar_chrome;
int main() {
  assert(label_scale == 0.95f);
  assert(caption_scale == 0.90f);
  assert(slider_thumb_inset == 2.0f);
  assert(viewport_pill_dim == 0.49f);
  assert(slider_track[0] == 0x1D && slider_track[1] == 0x1D);
  assert(cinema_pill_fill[0] == 0x0E && cinema_pill_border[0] == 0x3F);
  assert(cinema_pill_fill_on_a[0] == 0x20 && cinema_pill_fill_on_a[1] == 0x58);
  assert(viewport_pill_fill[0] == 0x05 && profile_fill[0] == 0x1B);
}
'''
    )
    binary = tmp_path / "chrome"
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
