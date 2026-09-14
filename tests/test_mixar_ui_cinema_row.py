# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Cinema popup-row recipes live in shared chrome and keep Director bytes."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ROOT / "src/source/blender/editors/include"
INTERFACE = ROOT / "src/source/blender/editors/interface"
CINEMA_HH = (
    ROOT / "src/source/blender/editors/space_view3d/view3d_director_cinema.hh"
)
ROW = INTERFACE / "interface_mixar_cinema_row.cc"


def test_cinema_popup_rows_use_named_chrome_recipes():
    chrome = (INCLUDE / "UI_mixar_chrome.hh").read_text(encoding="utf-8")
    row = ROW.read_text(encoding="utf-8")
    header = CINEMA_HH.read_text(encoding="utf-8")
    assert "inline constexpr float cinema_row_radius = 14.0f;" in chrome
    assert "inline constexpr float cinema_row_text_pad = 12.0f;" in chrome
    assert "inline constexpr float cinema_row_text_pad_min = 4.0f;" in chrome
    assert "inline constexpr float cinema_row_segment_min_w = 28.0f;" in chrome
    assert "#define CINEMA_ROW_RADIUS 14.0f" in header
    assert "ROW_RADIUS = mixar_chrome::cinema_row_radius" in row
    assert "TEXT_PAD = mixar_chrome::cinema_row_text_pad" in row
    assert "cinema_row_inset * UI_SCALE_FAC" in row
    assert "cinema_row_icon_gap * UI_SCALE_FAC" in row


def test_cinema_row_tokens_compile(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    source = tmp_path / "cinema_row.cc"
    source.write_text(
        r'''
#include "UI_mixar_chrome.hh"
#include <cassert>
using namespace blender::ui::mixar_chrome;
int main() {
  assert(cinema_row_radius == 14.0f);
  assert(cinema_row_text_pad == 12.0f);
  assert(cinema_row_text_pad_min == 4.0f);
  assert(cinema_row_segment_min_w == 28.0f);
  assert(cinema_row_inset == 1.0f);
  assert(cinema_row_icon_gap == 6.0f);
  assert(cinema_row_top[0] == 0x58 && cinema_row_bottom[0] == 0x24);
  assert(cinema_row_caption[0] == 102 && cinema_row_caption[3] == 217);
  assert(cinema_row_slider_on[0] == 42 && cinema_row_slider_on[1] == 121);
}
'''
    )
    binary = tmp_path / "cinema_row"
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
