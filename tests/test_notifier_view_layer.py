# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compile the production stats-clear block with Blender's window accessor.

A callback context must not select another window's statistics or be consulted
when it is unavailable. Infrastructure stubs deliberately reject that lookup.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_notifier_statistics_use_the_iterated_window(tmp_path):
    compiler = shutil.which('c++') or shutil.which('clang++') or shutil.which('g++')
    if compiler is None:
        pytest.skip('C++ compiler required')
    events = (ROOT / 'src/source/blender/windowmanager/intern/wm_event_system.cc').read_text()
    start = events.index('    if (clear_info_stats) {')
    block = events[start:events.index('\n    if (do_anim)', start)]
    windows = (ROOT / 'src/source/blender/windowmanager/intern/wm_window.cc').read_text()
    start = windows.index('ViewLayer *WM_window_get_active_view_layer(')
    getter = windows[start:windows.index('\n}', start) + 2]
    program = r'''
#include <cassert>
#include <cstdlib>
struct ViewLayer { int cleared = 0; };
struct Scene { ViewLayer *named, *fallback; };
struct wmWindow { Scene *scene; const char *view_layer_name = "Layer"; };
struct wmWindowManager { int notices = 0; wmWindow *target = nullptr; };
struct bContext {};
constexpr int NC_SPACE = 1, ND_SPACE_INFO = 2;
Scene *WM_window_get_active_scene(const wmWindow *win) { return win->scene; }
ViewLayer *BKE_view_layer_find(Scene *scene, const char *) {
  assert(scene); return scene->named;
}
ViewLayer *BKE_view_layer_default_view(Scene *scene) {
  assert(scene); return scene->fallback;
}
void WM_window_set_active_view_layer(wmWindow *, ViewLayer *) {}
ViewLayer *CTX_data_view_layer(bContext *) { std::abort(); }
wmWindow *CTX_wm_window(bContext *) { std::abort(); }
void ED_info_stats_clear(wmWindowManager *, ViewLayer *layer) {
  assert(layer); layer->cleared++;
}
void wm_event_add_notifier_intern(wmWindowManager *wm, wmWindow *win, int, void *) {
  wm->notices++; wm->target = win;
}
GETTER
void clear(wmWindowManager *wm, wmWindow &win, bool clear_info_stats) {
  bContext *C = nullptr;
BLOCK
}
int main() {
  wmWindowManager wm;
  wmWindow win{nullptr};
  clear(&wm, win, true); // Missing scene: no lookup/dereference, no info notifier.
  assert(wm.notices == 0);
  Scene empty{nullptr, nullptr};
  win.scene = &empty;
  clear(&wm, win, true);
  assert(wm.notices == 0);
  ViewLayer named, fallback;
  Scene scene{&named, &fallback};
  win.scene = &scene;
  clear(&wm, win, false);
  assert(named.cleared == 0 && wm.notices == 0);
  clear(&wm, win, true);
  assert(named.cleared == 1 && fallback.cleared == 0);
  assert(wm.notices == 1 && wm.target == &win);
  scene.named = nullptr;
  clear(&wm, win, true); // Deleted/renamed active layer uses the live fallback.
  assert(fallback.cleared == 1 && wm.notices == 2 && wm.target == &win);
}
'''.replace('GETTER', getter).replace('BLOCK', block)
    source = tmp_path / 'notifier.cc'
    source.write_text(program)
    binary = tmp_path / 'notifier'
    build = subprocess.run([compiler, '-std=c++17', str(source), '-o', str(binary)],
                           capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
