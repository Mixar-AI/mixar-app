# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execute the production motion evaluator outside Blender at arbitrary cadences."""

from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_motion_continuity_and_settlement(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++")
    assert compiler, "C++ compiler required for the production motion evaluator"
    source = tmp_path / "motion.cc"
    source.write_text(r'''
#include "UI_mixar_motion.hh"
#include "../interface/mixar/motion_storage.hh"
#include <cassert>
#include <cmath>
using namespace blender::ui;
int main() {
  MixarMotionValue first;
  assert(first.sample(1, 10, .2) == 1); // Open surfaces do not flash from off.
  assert(!first.active(10));
  MixarMotionValue a, b;
  a.settle(0); b.settle(0);
  a.sample(1, 0, .2); b.sample(1, 0, .2);
  for (int i=1; i<8; ++i) a.sample(1, i * .01, .2);
  const float at_80ms = a.sample(1, .08, .2);
  assert(at_80ms > 0 && at_80ms < 1);
  assert(std::abs(at_80ms-b.sample(1, .08, .2)) < 1e-6); // Frame independence.
  const float before = a.at(.09);
  assert(a.sample(0, .09, .14) == before); // Reversal starts at exact pose.
  float last = before;
  for (int i=1; i<=14; ++i) {
    const float v = a.sample(0, .09+i*.01, .14);
    assert(v >= 0 && v <= last); // No overshoot or direction bounce.
    last = v;
  }
  assert(a.sample(0, 1, .14) == 0 && !a.active(1));
  assert(b.sample(1, 50, .2) == 1); // Suspended/slow app lands immediately.
  b.sample(0, 50, .14);
  b.settle(0); // Disabled state cancels motion immediately.
  assert(b.sample(0, 50.01, .14) == 0 && !b.active(50.01));
  b.sample(1, 51, 0);
  assert(b.value == 1 && !b.active(51));
  MixarMotionStorage original;
  original.ensure();
  (*original).hover.settle(1);
  MixarMotionStorage copied(original);
  (*copied).hover.settle(0);
  assert((*original).hover.value == 1); // Native temporary copies never share paint state.
  MixarMotionStorage moved(std::move(original));
  assert(!original && (*moved).hover.value == 1);
}
''')
    binary = tmp_path / "motion"
    subprocess.run([compiler, "-std=c++17", "-I",
                    str(ROOT / "src/source/blender/editors/include"), str(source),
                    "-o", str(binary)], check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_motion_ownership_and_idle_timer_contract():
    source = (ROOT / "src/source/blender/editors/interface/mixar/motion.cc").read_text()
    interface = (ROOT / "src/source/blender/editors/interface/interface.cc").read_text()
    assert "MixarMotionRebuild motion(*block)" in interface
    assert "motion.apply(*block)" in interface
    assert "motion.operator_identity = button.optype" in source
    assert "states_[i] = std::move(previous[i]->mixar_motion)" in source
    assert "mixar_button_motion_update(but, region)" in interface
    assert "pending.empty() ? -1.0" in source
    assert "screen->regionbase" in source and "window.global_areas.areabase" in source
    assert "pending = std::move(live)" in source
    assert "timer_free" in source and "pending.clear()" in source
    assert "WM_main_add_notifier" not in source


def test_qa_capture_preserves_hover_and_avoids_stale_frontbuffer():
    source = (ROOT / "src/source/blender/makesrna/intern/rna_wm_mixar.cc").read_text()
    capture = source[source.index("static bool rna_Window_mixar_qa_capture_frame"):]
    capture = capture[:capture.index("#else /* RNA_RUNTIME */")]
    assert "G_FLAG_EVENT_SIMULATE" in capture
    assert "WM_window_pixels_read_from_offscreen" in capture
    assert "WM_redraw_windows(C)" not in capture
    assert "IMB_freeImBuf(buffer)" in capture
