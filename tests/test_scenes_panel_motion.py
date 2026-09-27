# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute the native reorder/easing helpers without a Blender build."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_native_scene_reorder_motion(tmp_path):
    compiler = shutil.which('c++') or shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        pytest.skip('A C++ compiler is required for the native motion regression')
    source = tmp_path / 'motion.cc'
    source.write_text(r'''
#include "view3d_scenes_drawer_motion.hh"
#include <cassert>
#include <numeric>
#include <vector>
using namespace blender::view3d_scenes_drawer;

int main()
{
  // Every insertion slot preserves each card's identity and creates one gap.
  for (int count = 1; count <= 16; ++count) {
    for (int source = 0; source < count; ++source) {
      for (int slot = 0; slot <= count; ++slot) {
        std::vector<int> expected(count);
        std::iota(expected.begin(), expected.end(), 0);
        expected.erase(expected.begin() + source);
        expected.insert(expected.begin() + (slot > source ? slot - 1 : slot), source);
        for (int row = 0; row < count; ++row) {
          assert(reorder_preview_row(expected[row], source, slot) == row);
        }
      }
    }
  }
  // One tenth of a second means the same displacement at 30, 60 and 120 Hz.
  float positions[3];
  for (int rate = 0; rate < 3; ++rate) {
    const int steps = 3 << rate;
    float p = 0.0f;
    for (int i = 0; i < steps; ++i) {
      float next = follow_position(p, 1.0f, 0.1 / steps);
      assert(next >= p && next <= 1.0f);
      p = next;
    }
    positions[rate] = p;
  }
  assert(std::abs(positions[0] - positions[1]) < 1e-6f);
  assert(std::abs(positions[0] - positions[2]) < 1e-6f);
  // Reverse midway: approach the new slot immediately, without overshooting.
  float p = follow_position(0.0f, 1.0f, 0.03);
  for (int i = 0; i < 30; ++i) {
    const float next = follow_position(p, -1.0f, 1.0 / 120.0);
    assert(next <= p && next >= -1.0f);
    p = next;
  }
  assert(std::abs(p + 1.0f) < 0.001f);
  assert(follow_position(0.5f, 1.0f, 0.0) == 0.5f);
  assert(follow_position(0.5f, 1.0f, -1.0) == 0.5f);
  // The final snap is subpixel even after moving over three card pitches.
  assert(follow_position(204.0f, 0.0f, CARD_SETTLE_SECONDS) < 0.5f);
}
''')
    binary = tmp_path / 'motion'
    built = subprocess.run([compiler, '-std=c++17', '-I',
                            str(ROOT / 'src/source/blender/editors/space_view3d'),
                            str(source), '-o', str(binary)], capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    executed = subprocess.run([str(binary)], capture_output=True, text=True)
    assert executed.returncode == 0, executed.stdout + executed.stderr
