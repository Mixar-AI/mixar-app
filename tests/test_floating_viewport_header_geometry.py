# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Execute the native header reservation after an overlay remainder reset."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_header_reservation_survives_hidden_regions_and_respects_both_edges(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    area = (ROOT / "src/source/blender/editors/screen/area.cc").read_text()
    start = area.index("static bool region_is_hidden(")
    end = area.index("/* region should be overlapping */", start)
    # Compile the actual visibility and clipping functions, with only the DNA
    # fields/constants they use stubbed. GUI replay tests the full allocation.
    source = tmp_path / "header_geometry.cc"
    source.write_text(r'''
#include <algorithm>
#include <cassert>
#define ELEM(value, a, b) ((value) == (a) || (value) == (b))
#define RGN_ALIGN_ENUM_FROM_MASK(value) ((value) & 15)
enum { RGN_TYPE_HEADER = 1, RGN_TYPE_TOOL_HEADER = 2 };
enum { RGN_ALIGN_TOP = 1, RGN_ALIGN_BOTTOM = 2, RGN_ALIGN_HIDE_WITH_PREV = 16 };
enum { RGN_FLAG_HIDDEN = 1, RGN_FLAG_POLL_FAILED = 2, RGN_FLAG_TOO_SMALL = 4 };
struct rcti { int xmin = 0, xmax = 999, ymin = 0, ymax = 799; };
struct ARegion {
  ARegion *prev = nullptr;
  int regiontype = 0, alignment = 0, flag = 0;
  bool overlap = true;
  rcti winrct;
};
''' + area[start:end] + r'''
int main()
{
  ARegion header, tools, hidden, drawer;
  header.regiontype = RGN_TYPE_HEADER;
  header.alignment = RGN_ALIGN_TOP;
  header.winrct.ymin = 774;
  tools.prev = &header;
  tools.regiontype = RGN_TYPE_TOOL_HEADER;
  tools.alignment = RGN_ALIGN_TOP;
  tools.winrct.ymin = 748;
  tools.winrct.ymax = 773;
  hidden.prev = &tools;
  hidden.overlap = false;
  hidden.flag = RGN_FLAG_HIDDEN;
  drawer.prev = &hidden;

  rcti remaining;
  mixar_floating_headers_clip(&tools, &remaining);
  assert(remaining.ymax == 773); // Tool settings must sit below shading.
  remaining = {}; // Hidden non-overlap region resets the overlay remainder.
  mixar_floating_headers_clip(&drawer, &remaining);
  assert(remaining.ymin == 0 && remaining.ymax == 747);
  assert(remaining.xmin == 0 && remaining.xmax == 999);

  for (int flag : {RGN_FLAG_HIDDEN, RGN_FLAG_POLL_FAILED, RGN_FLAG_TOO_SMALL}) {
    tools.flag = flag;
    remaining = {};
    mixar_floating_headers_clip(&drawer, &remaining);
    assert(remaining.ymax == 773); // Unavailable tool headers reserve nothing.
  }
  tools.flag = 0;
  header.alignment = RGN_ALIGN_BOTTOM;
  header.winrct.ymin = 0;
  header.winrct.ymax = 25;
  remaining = {};
  mixar_floating_headers_clip(&drawer, &remaining);
  assert(remaining.ymin == 26 && remaining.ymax == 747);
  // Existing tighter bounds must survive both repeated clipping and headers.
  remaining.ymin = 100;
  remaining.ymax = 700;
  mixar_floating_headers_clip(&drawer, &remaining);
  assert(remaining.ymin == 100 && remaining.ymax == 700);

  tools.alignment |= RGN_ALIGN_HIDE_WITH_PREV;
  header.flag = RGN_FLAG_HIDDEN;
  remaining = {};
  mixar_floating_headers_clip(&drawer, &remaining);
  assert(remaining.ymin == 0 && remaining.ymax == 799);
}
''')
    binary = tmp_path / "header_geometry"
    subprocess.run([compiler, "-std=c++17", str(source), "-o", str(binary)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
