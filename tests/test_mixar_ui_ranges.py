# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compile production geometry helpers and check composer/list boundaries."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_native_visible_ranges(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required for the native layout contract")
    source = tmp_path / "ranges.cc"
    source.write_text(r'''
#include "UI_mixar_layout.hh"
#include <cassert>
#include <climits>
using namespace blender::ui;
int main() {
  for (float scale : {0.5f, 1.0f, 2.0f}) {
    MixarFlow f;
    f.x = f.x0 = 10*scale; f.x_max = 110*scale;
    f.y_top = 100*scale; f.y_floor = 0;
    f.row_height = 20*scale; f.row_pitch = 30*scale; f.gap = 5*scale;
    MixarFlowRect r;
    assert(f.place(30*scale, r));
    assert(r.xmin == 10*scale && r.xmax == 40*scale);
    assert(f.place(200*scale, r)); // Oversized content is bounded on a new row.
    assert(r.xmin == 10*scale && r.xmax == 110*scale && r.ymax == 70*scale);
    assert(f.place(100*scale, r));
    const float x = f.x, top = f.y_top;
    assert(!f.place(100*scale, r)); // No final partial row; no position mutation.
    assert(f.x == x && f.y_top == top);
    assert(!f.place(1*scale, r));
  }

  for (float scale : {0.5f, 1.0f, 1.5f, 2.0f}) {
    const MixarComposerMetrics metrics{44*scale, 16*scale, 8*scale, 40*scale};
    for (int bottom : {-20, 0, 17}) {
      for (int height = -10; height <= 500; ++height) {
        const float top = bottom + height*scale;
        const auto r = mixar_composer_layout(bottom, top, metrics);
        assert(r.action_bottom >= bottom);
        assert(r.action_bottom <= r.action_top);
        assert(r.action_top <= r.field_bottom);
        assert(r.field_bottom <= r.field_top);
        assert(r.field_top == std::max(float(bottom), top));
        assert(r.action_top-r.action_bottom <= metrics.action_height);
        assert(r.editable == (height*scale >= metrics.minimum_height()));
        if (r.editable) {
          assert(r.field_bottom-r.action_top >= metrics.gap);
          assert(r.field_top-r.field_bottom >= metrics.minimum_field_height);
        } else {
          assert(r.field_bottom == r.field_top); // No invisible input over actions.
        }
      }
    }
  }

  for (int total = 0; total < 100; ++total) {
    for (int capacity = 0; capacity < 15; ++capacity) {
      for (int offset = -2; offset < 110; ++offset) {
        const auto r = mixar_list_range(total, capacity, offset);
        assert(r.first >= 0 && r.end() <= total);
        assert(r.size == std::min(total, capacity));
        if (capacity && total) {
          assert(r.first == std::min(std::max(0, offset), std::max(0, total-capacity)));
        }
      }
      int visited = 0;
      for (int page = 0; page < mixar_page_count(total, capacity); ++page) {
        const auto r = mixar_page_range(total, capacity, page);
        assert(r.first == visited); // Pages never overlap or skip items.
        assert(r.size <= capacity && r.end() <= total);
        visited += r.size;
      }
      assert(visited == (capacity ? total : 0));
    }
  }
  assert(mixar_list_range(90, 3, 999).first == 87);
  assert(mixar_list_range(2, 3, 87).first == 0); // Queue shrank while scrolled.
  assert(mixar_list_range(90, 8, 87).first == 82); // Larger viewport.
  assert(mixar_page_range(90, 8, 999).size == 2); // Partial final page.
  assert(mixar_page_count(INT_MAX, INT_MAX) == 1);
  assert(mixar_page_range(INT_MAX, 2, INT_MAX).end() == INT_MAX);
  assert(mixar_list_range(-1, 3, 1).size == 0);
  assert(mixar_page_range(3, -1, 2).size == 0);
}
''')
    binary = tmp_path / "ranges"
    subprocess.run([compiler, "-std=c++17", "-I", str(ROOT / "src/source/blender/editors/include"),
                    str(source), "-o", str(binary)], check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)
