# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Execute the native visible-rect calculation under Zen's viewport-wide tool header.

Zen's adaptive object/light bar lives in a TOOL_HEADER that spans the whole
viewport (#1706); only its top toolbar band is chrome. Subtracting the whole
region collapsed the viewport's visible rect to zero height, which hid the
navigation gizmo (and its zoom/pan buttons) and failed every annotation
stroke's bounds check. The layout (#1715) and the visible rect must reserve the
same band.
"""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "src/source/blender/editors/screen/area.cc"


def _slice(text, start_marker, end_marker):
    start = text.index(start_marker)
    return text[start:text.index(end_marker, start)]


def test_layout_and_visible_rect_share_one_band_helper():
    area = AREA.read_text()
    helper = "mixar_zen_tool_header_band_ymin("
    assert area.count("static int " + helper) == 1
    rect_recursive = _slice(area, "static void region_rect_recursive(", "\n}\n")
    visible = _slice(area, "static void region_visible_rect_calc(", "\n}\n")
    assert helper in rect_recursive
    assert helper in visible
    assert "mixar_region_is_zen_adaptive_tool_header" in visible


def test_visible_rect_keeps_the_viewport_below_the_zen_band(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    area = AREA.read_text()
    helper = _slice(area, "static int mixar_zen_tool_header_band_ymin(", "\n}\n") + "\n}\n"
    visible = _slice(area, "static void region_visible_rect_calc(", "\n}\n") + "\n}\n"
    source = tmp_path / "visible_rect.cc"
    # Compile the actual functions with only the DNA fields, BLI helpers and
    # constants they use stubbed. The GUI replay covers the drawn gizmo.
    source.write_text(r'''
#include <algorithm>
#include <cassert>
#include <cstdlib>
#define ELEM(value, a, b) ((value) == (a) || (value) == (b))
#define RGN_ALIGN_ENUM_FROM_MASK(value) ((value) & 15)
#define BLI_assert_msg(a, msg) assert(a)
#define UI_SCALE_FAC 2.0f
enum { RGN_TYPE_WINDOW = 0, RGN_TYPE_HEADER = 1, RGN_TYPE_TOOL_HEADER = 2 };
enum { RGN_ALIGN_NONE = 0, RGN_ALIGN_TOP = 1, RGN_ALIGN_BOTTOM = 2, RGN_ALIGN_LEFT = 3,
       RGN_ALIGN_RIGHT = 4, RGN_ALIGN_FLOAT = 7 };
struct rcti { int xmin, xmax, ymin, ymax; };
struct ARegion {
  ARegion *prev = nullptr, *next = nullptr;
  int regiontype = 0, alignment = 0;
  bool overlap = true, zen = false;
  rcti winrct{0, 999, 0, 799};
};
static bool BLI_rcti_isect(const rcti *a, const rcti *b, rcti *)
{
  return a->xmin <= b->xmax && b->xmin <= a->xmax && a->ymin <= b->ymax && b->ymin <= a->ymax;
}
static void BLI_rcti_translate(rcti *r, int x, int y)
{
  r->xmin += x; r->xmax += x; r->ymin += y; r->ymax += y;
}
namespace ui {
namespace mixar_chrome { inline constexpr float zen_toolbar_height = 20.0f; }
static bool mixar_region_is_zen_adaptive_tool_header(const ARegion *region)
{
  return region->zen && region->overlap && region->regiontype == RGN_TYPE_TOOL_HEADER;
}
}  // namespace ui
''' + helper + visible + r'''
static rcti visible_of(ARegion &window)
{
  rcti rect{};
  region_visible_rect_calc(&window, &rect);
  return rect;
}

int main()
{
  // Area 1000x800. Scene toolbar header on top, rows 760..799.
  ARegion header, tool_header, window;
  header.regiontype = RGN_TYPE_HEADER;
  header.alignment = RGN_ALIGN_TOP;
  header.winrct = {0, 999, 760, 799};
  tool_header.regiontype = RGN_TYPE_TOOL_HEADER;
  tool_header.alignment = RGN_ALIGN_TOP;
  window.regiontype = RGN_TYPE_WINDOW;
  window.overlap = false;
  header.next = &tool_header;
  tool_header.prev = &header;
  tool_header.next = &window;
  window.prev = &tool_header;

  // Zen: the tool header spans the whole viewport below the toolbar.
  tool_header.zen = true;
  tool_header.winrct = {0, 999, 0, 759};
  rcti rect = visible_of(window);
  // Only the 40 px band (20 * UI_SCALE_FAC) under the toolbar is chrome.
  assert(rect.ymax == 759 - 40);
  assert(rect.ymin == 0 && rect.xmin == 0 && rect.xmax == 999);
  assert(rect.ymax - rect.ymin > 600); // Never collapses to the old zero height.

  // Engine: a stock tool-header strip is subtracted whole, as upstream does.
  tool_header.zen = false;
  tool_header.winrct = {0, 999, 734, 759};
  rect = visible_of(window);
  assert(rect.ymax == 734);

  // A Zen host shorter than its band keeps its own bounds.
  tool_header.zen = true;
  tool_header.winrct = {0, 999, 740, 759};
  rect = visible_of(window);
  assert(rect.ymax == 740);
  return 0;
}
''')
    binary = tmp_path / "visible_rect"
    subprocess.run([compiler, "-std=c++17", str(source), "-o", str(binary)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
