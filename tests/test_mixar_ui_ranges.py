# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compile the production range helper and check scrolling/paging boundaries."""
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
