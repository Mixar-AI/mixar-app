# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pins for the three defects the PR #1839 review found (change record 3.11-3.13).

The live proof is ``tests/qa/sticky_ui/cases_review.py``; each case fails on a
build without its fix. These pins keep the fixes from being removed silently.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()


# 3.11 ---------------------------------------------------------------------------

def test_removing_a_scene_frees_its_render_unless_a_job_owns_it():
    cc = (ROOT / "src/source/blender/makesrna/intern/rna_main_api.cc").read_text()
    body = cc[cc.index("static void rna_Main_ID_remove("):]
    body = body[:body.index("\n}\n")]
    free = body.index("RE_FreeRender(re)")
    assert body.index("GS(id->name) == ID_SCE") < free
    assert body.index("!WM_jobs_test(wm, id, WM_JOB_TYPE_ANY)") < free     # never under a running render
    assert body.index("RE_GetSceneRender(") < free
    assert free < body.index("BKE_id_delete(bmain, id)")                   # before the Scene's address is freed


def test_private_render_scene_never_keeps_persistent_data(monkeypatch):
    from mixar.modules.space_mixie_chat.core import render_scene
    monkeypatch.setattr(render_scene, "sweep", lambda keep=None: 0)
    monkeypatch.setattr(render_scene, "_scrub", lambda copy: None)
    copy = SimpleNamespace(name="", render=SimpleNamespace(
        use_persistent_data=True, use_compositing=True, use_sequencer=True))
    source = SimpleNamespace(copy=lambda: copy)
    assert render_scene.create(source, inspection=True) is copy
    assert copy.render.use_persistent_data is False


# 3.12 ---------------------------------------------------------------------------

def test_bubble_layouts_and_screens_are_left_out_of_every_write():
    cc = (ROOT / "src/source/blender/windowmanager/intern/wm_files.cc").read_text()
    unlink = cc[cc.index("static AgentBubbleWriteStash wm_agent_bubble_windows_unlink_for_write("):]
    unlink = unlink[:unlink.index("\n}\n")]
    assert "BLI_remlink(&workspace->layouts, layout)" in unlink
    assert "BLI_remlink(&bmain->screens, screen)" in unlink
    # ...and out of the name map, or the writer's name check reports "Critical data
    # corruption" on every checkpoint taken with the island open.
    assert "BKE_main_namemap_remove_id(*bmain, screen->id)" in unlink
    assert "wm_layout_used_by_other_window(wm, layout)" in unlink     # a layout a written window shows stays
    relink = cc[cc.index("static void wm_agent_bubble_windows_relink_after_write("):]
    relink = relink[:relink.index("\n}\n")]
    assert "BLI_insertlinkafter(&bmain->screens, it->prev, it->screen)" in relink
    assert "BLI_insertlinkafter(&it->workspace->layouts, it->prev, it->layout)" in relink
    assert "rbegin()" in relink                                      # reverse order keeps each `prev` valid
    assert "BKE_main_namemap_clear(*bmain)" in relink                # the names come back with the screens
    # Every writer that drops the bubble windows also drops their layouts.
    assert cc.count("wm_agent_bubble_windows_unlink_for_write(bmain,") == 3
    assert cc.count("wm_agent_bubble_windows_relink_after_write(bmain, wm, agent_bubble_stash)") == 3


# 3.13 ---------------------------------------------------------------------------

def _toast_timer(monkeypatch, visible):
    for name in ("blf", "gpu", "gpu.state", "gpu.shader", "gpu_extras", "gpu_extras.batch"):
        sys.modules.setdefault(name, MagicMock(name=name))
    from mixar.modules.common.notifications import toast_timer, store
    calls = []
    monkeypatch.setattr(store, "get_notification_store",
                        lambda: SimpleNamespace(get_visible=lambda: visible))
    monkeypatch.setattr(toast_timer, "ensure_toast_timer_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(toast_timer, "_set_toasts_visible_flag", lambda v: calls.append(("flag", v)))
    return toast_timer, calls


def test_a_toast_that_survives_a_file_load_gets_its_timer_and_flag_back(monkeypatch):
    toast_timer, calls = _toast_timer(monkeypatch, visible=["sticky"])
    toast_timer._resume_after_load(None)
    assert calls == ["ensure"]


def test_a_load_with_no_toast_clears_the_click_gate(monkeypatch):
    toast_timer, calls = _toast_timer(monkeypatch, visible=[])
    toast_timer._resume_after_load(None)
    assert calls == [("flag", False)]


def test_the_load_handler_is_persistent_and_installed_with_the_timer():
    src = (ROOT / "src/scripts/mixar/modules/common/notifications/toast_timer.py").read_text()
    assert "@persistent\ndef _resume_after_load(" in src
    start = src[src.index("def _start_on_main()"):src.index("bpy.app.timers.register(_start_on_main")]
    assert "_install_load_handler()" in start
