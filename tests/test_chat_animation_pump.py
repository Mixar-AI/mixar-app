# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run the production C++ pump with a deterministic clock and WM timer API."""

from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
EDITORS = ROOT / "src/source/blender/editors"


def test_chat_pump_expires_without_another_draw_and_rearms(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++")
    assert compiler
    (tmp_path / "BKE_context.hh").write_text(r'''
#pragma once
namespace blender {
struct wmWindowManager {};
struct wmWindow {};
struct bContext { wmWindowManager *manager; wmWindow *window; };
inline wmWindowManager *CTX_wm_manager(const bContext *c) { return c->manager; }
inline wmWindow *CTX_wm_window(const bContext *c) { return c->window; }
}
''')
    (tmp_path / "BLI_time.h").write_text(r'''
#pragma once
namespace blender {
extern double test_time;
inline double BLI_time_now_seconds() { return test_time; }
}
''')
    (tmp_path / "WM_types.hh").write_text(r'''
#pragma once
namespace blender {
constexpr int NC_SPACE = 1 << 16;
constexpr int ND_SPACE_MIXIE_CHAT_TICK = 123;
struct wmTimer {};
}
''')
    (tmp_path / "WM_api.hh").write_text(r'''
#pragma once
#include "BKE_context.hh"
#include "WM_types.hh"
namespace blender {
wmTimer *WM_event_timer_add_notifier(wmWindowManager *, wmWindow *, int, double);
void WM_event_timer_remove(wmWindowManager *, wmWindow *, wmTimer *);
}
''')
    source = tmp_path / "pump.cc"
    source.write_text(r'''
#include <cassert>
#include <cmath>
#include "BKE_context.hh"
#include "ED_agent_bubble_motion.hh"
#include "WM_api.hh"
#include "mixie_chat_anim_pump.hh"
namespace blender {
double test_time = 10;
wmTimer test_timer;
wmWindowManager manager;
wmWindow window;
int starts = 0, stops = 0;
bool live = false;
wmTimer *WM_event_timer_add_notifier(wmWindowManager *wm, wmWindow *win,
                                    int notifier, double interval) {
  assert(wm == &manager && win == &window && !live);
  assert(notifier == (NC_SPACE | ND_SPACE_MIXIE_CHAT_TICK));
  assert(std::abs(interval - 1.0 / 30.0) < 1e-9);
  starts++;
  live = true;
  return &test_timer;
}
void WM_event_timer_remove(wmWindowManager *wm, wmWindow *, wmTimer *timer) {
  assert(wm == &manager && timer == &test_timer && live);
  stops++;
  live = false;
}
}
using namespace blender;
int main() {
  const bContext context{&manager, &window};
  const bContext no_window{&manager, nullptr};
  const bContext no_manager{nullptr, &window};
  mixie_chat_anim_pump_request(&context, false);
  mixie_chat_anim_pump_request(&no_window, true);
  mixie_chat_anim_pump_request(&no_manager, true);
  assert(starts == 0 && !ED_agent_chat_animation_stats().scheduled);

  mixie_chat_anim_pump_request(&context, true);
  assert(starts == 1 && live && ED_agent_chat_animation_stats().scheduled);
  for (int frame = 1; frame <= 30; frame++) {
    test_time = 10 + frame / 30.0;
    mixie_chat_anim_pump_tick();
    assert(live);
    mixie_chat_anim_pump_request(&context, true);
  }
  assert(starts == 1 && ED_agent_chat_animation_stats().ticks == 30);

  // A collapse or non-chat tab stops paints entirely: no request(false).
  test_time = 11.25;
  mixie_chat_anim_pump_tick();
  assert(live);
  test_time = 11.51;
  mixie_chat_anim_pump_tick();
  assert(!live && stops == 1 && !ED_agent_chat_animation_stats().scheduled);
  const auto stopped_ticks = ED_agent_chat_animation_stats().ticks;
  mixie_chat_anim_pump_tick(); // Already-queued notification after removal.
  mixie_chat_anim_pump_shutdown(&manager);
  assert(stops == 1 && ED_agent_chat_animation_stats().ticks == stopped_ticks);

  // Restoring a still-streaming transcript starts a fresh timer normally.
  mixie_chat_anim_pump_request(&context, true);
  assert(live && starts == 2);
  test_time = 11.60;
  mixie_chat_anim_pump_request(&context, false);
  assert(live); // An inactive painter cannot cancel another live animation.
  test_time = 12.02;
  mixie_chat_anim_pump_request(&context, false);
  assert(!live && stops == 2);

  // Window/region exit releases the timer before the native owner is freed.
  mixie_chat_anim_pump_request(&context, true);
  mixie_chat_anim_pump_shutdown(&manager);
  assert(!live && starts == 3 && stops == 3);
}
''')
    binary = tmp_path / "pump"
    subprocess.run(
        [compiler, "-std=c++17", "-I", str(tmp_path),
         "-I", str(EDITORS / "include"),
         "-I", str(EDITORS / "space_mixie_chat"),
         str(EDITORS / "space_mixie_chat/mixie_chat_anim_pump.cc"),
         str(source), "-o", str(binary)],
        check=True, capture_output=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True)
