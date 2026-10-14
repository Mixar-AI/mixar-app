# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Engine-mode switch stall: display shader pre-warm and Dock progress throttle.

The first switch to Engine Mode compiled the solid-shading display shader on
the main thread inside the switch (0.34 s), and every job progress update
redrew the macOS Dock icon (2.5 s of a 30 s sample during a preview render).
"""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
V3D = ROOT / "src/source/blender/editors/space_view3d"


def test_prewarm_is_wired_and_one_shot():
    cc = (V3D / "view3d_display_prewarm.cc").read_text()
    assert '"mixar_prewarm_display_shaders"' in cc
    assert "IDP_int_or_bool_set(prop, 0);" in cc            # cleared before compiling
    assert cc.count("prewarm_variant(") >= 4                 # three variants + definition
    assert "IMB_colormanagement_finish_glsl_draw()" in cc
    assert "view3d_display_shader_prewarm(C);" in (V3D / "view3d_director_overlay.cc").read_text()
    assert "view3d_display_prewarm.cc" in (V3D / "CMakeLists.txt").read_text()


def test_python_sets_the_flag_after_startup(monkeypatch):
    from mixar.bootstrap import workflow_module as W
    assert W._PREWARM_WM_PROP == "mixar_prewarm_display_shaders"
    store = {}
    wm = MagicMock()
    wm.__setitem__ = lambda self, k, v: store.__setitem__(k, v)
    redraw = MagicMock()
    monkeypatch.setattr(W, "bpy", SimpleNamespace(
        data=SimpleNamespace(window_managers=[wm]),
        ops=SimpleNamespace(mixar=SimpleNamespace(agent_halo_redraw=redraw))))
    assert W._prewarm_display_shaders() is None
    assert store == {"mixar_prewarm_display_shaders": 1} and redraw.called
    source = (ROOT / "src/scripts/mixar/bootstrap/workflow_module.py").read_text()
    assert re.search(r"timers\.register\(_prewarm_display_shaders, first_interval=_PREWARM_DELAY_S\)", source)


def test_ghost_dock_icon_is_cached_and_throttled():
    mm = (ROOT / "src/intern/ghost/intern/GHOST_WindowCocoa.mm").read_text()
    assert "static NSImage *mixar_dock_icon_base()" in mm
    body = mm[mm.index("GHOST_WindowCocoa::setProgressBar("):mm.index("GHOST_WindowCocoa::endProgressBar(")]
    assert "mixar_dock_icon_base() drawAtPoint" in body
    assert "fabsf(progress - last_progress) < 0.02f" in body and "(now - last_time) < 0.25" in body
    assert 'imageNamed:@"NSApplicationIcon"' not in body     # only the cached render is drawn per update
    end = mm[mm.index("GHOST_WindowCocoa::endProgressBar("):]
    assert "setApplicationIconImage:mixar_dock_icon_base()" in end


def test_dock_progress_is_throttled_per_window():
    """wm_jobs forwards progress to every window; Mixar always has three. A single
    shared "last window" slot alternated between them and never skipped anything
    (PR #1839 review finding 6), so the throttle state is looked up per window."""
    cc = (ROOT / "src/source/blender/windowmanager/intern/wm_window.cc").read_text()
    body = cc[cc.index("void WM_progress_set("):cc.index("void WM_progress_clear(")]
    assert "wm_progress_throttle_slot(win->runtime->ghostwin)" in body
    assert "std::fabs(progress - last.value) < 0.01f && (now - last.time) < 0.1" in body
    assert "g_progress_last_win" not in cc
    slot = cc[cc.index("static ProgressThrottle &wm_progress_throttle_slot("):cc.index("void WM_progress_set(")]
    assert "slot.ghostwin == ghostwin" in slot
    clear = cc[cc.index("void WM_progress_clear("):].split("/** \\} */")[0]
    assert "slot.ghostwin == win->runtime->ghostwin" in clear and "slot = ProgressThrottle{}" in clear
