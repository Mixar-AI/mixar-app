# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Scenes drawer's timer and thumbnails follow the window and file they
belong to.

- The slide's redraw timer runs on the window that OWNS the drawer region.
  Ctrl+` also fires from the island composer; a timer added on the island's
  window was freed with it, and the drawer then read the freed timer's
  ``win``. A cached timer is trusted only while the window manager lists it.
- A file load (Open, Revert, File > New) empties the snapshot store and bumps
  its epoch, so a same-path reload cannot show pre-load pictures, and a
  region that survives the load drops its own copy too.
- A snapshot reads the viewport in the GPU context of the window that owns
  the host region, whatever window the context names.

``bpy`` is a MagicMock in this suite, so these are source-level contracts
against comment-stripped C++.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
DRAWER = (VIEW3D / "view3d_scenes_drawer.cc").read_text(encoding="utf-8")
THUMBS = (VIEW3D / "view3d_scenes_drawer_thumbs.cc").read_text(encoding="utf-8")
DRAWER_HH = (VIEW3D / "view3d_scenes_drawer.hh").read_text(encoding="utf-8")
ED_HH = (ROOT / "src/source/blender/editors/include/ED_scenes_drawer.hh").read_text(
    encoding="utf-8"
)


def _code(source: str) -> str:
    """`source` without comment lines or trailing `//` / `/* */` comments."""
    kept = []
    for line in source.split("\n"):
        if line.lstrip().startswith(("*", "/*", "//")):
            continue
        kept.append(line.split("//")[0].split("/*")[0])
    return "\n".join(kept)


def _block(source: str, start: str) -> str:
    body = source[source.index(start):]
    return body[: body.index("\n}\n") + 3]


# ---- CL-12: the tick timer --------------------------------------------------


def test_the_cached_timer_is_never_dereferenced():
    assert "tick_timer->win" not in _code(DRAWER)
    remove = _code(_block(DRAWER, "static void drawer_tick_timer_remove("))
    assert "WM_event_timer_remove(wm, nullptr, runtime->tick_timer);" in remove


def test_the_cached_timer_is_validated_against_the_live_list():
    ensure = _code(_block(DRAWER, "static void drawer_tick_timer_ensure("))
    assert "BLI_findindex(&wm->runtime->timers, timer) == -1" in ensure
    assert "WM_TIMER_TAGGED_FOR_REMOVAL" in ensure
    assert ensure.index("BLI_findindex") < ensure.index("WM_event_timer_add")


def test_the_timer_goes_on_the_window_that_owns_the_region():
    ensure = _code(_block(DRAWER, "static void drawer_tick_timer_ensure("))
    assert "CTX_wm_window" not in ensure
    assert "view3d_scenes_drawer_region_window(wm, region)" in ensure
    slide = _code(_block(DRAWER, "void view3d_scenes_drawer_slide_begin("))
    assert "drawer_tick_timer_ensure(wm, region, runtime);" in slide
    assert "wmWindow *view3d_scenes_drawer_region_window(" in DRAWER_HH


# ---- CL-13: file load clears the store --------------------------------------


def test_a_file_load_resets_the_snapshot_store():
    code = _code(DRAWER)
    assert "BKE_callback_add(&store, BKE_CB_EVT_LOAD_POST);" in code
    post = _code(_block(DRAWER, "static void drawer_snapshots_load_post("))
    assert "view3d_scenes_drawer_snapshot_store_reset();" in post
    register = _code(_block(DRAWER, "void view3d_scenes_drawer_region_register("))
    assert "drawer_snapshots_load_post_register();" in register
    # Registered once, with a static (not heap) store.
    once = _code(_block(DRAWER, "static void drawer_snapshots_load_post_register("))
    assert "static bCallbackFuncStore store" in once
    assert "store.alloc = false;" in once
    assert "if (store.func != nullptr) {" in once


def test_the_reset_empties_the_store_and_bumps_the_epoch():
    reset = _code(_block(THUMBS, "void view3d_scenes_drawer_snapshot_store_reset("))
    for line in ("g_store.by_scene.clear();", "g_store.bmain = nullptr;", "g_store.epoch++;"):
        assert line in reset, line
    # A Main or path change alone (global undo re-allocates Main, Save As
    # changes the path) clears the store but must not blank region copies.
    sync = _code(_block(THUMBS, "static void store_sync_main("))
    assert "g_store.by_scene.clear();" in sync
    assert "epoch" not in sync
    assert "view3d_scenes_drawer_snapshot_store_reset" not in sync


def test_a_region_copy_from_an_older_epoch_is_dropped():
    assert "uint64_t epoch = 0;" in ED_HH.split("struct ScenesDrawerThumb")[1].split("};")[0]
    draw = _code(_block(THUMBS, "void view3d_scenes_drawer_thumb_draw("))
    check = "if (t.epoch != g_store.epoch) {"
    assert check in draw
    branch = draw[draw.index(check):]
    branch = branch[: branch.index("\n  }")]
    assert "view3d_scenes_drawer_thumb_free(t);" in branch
    assert "t.epoch = g_store.epoch;" in branch
    # Before the store's picture is pulled into the region.
    assert draw.index(check) < draw.index("g_store.by_scene.find(scene_name)")


# ---- CL-15: the host window's GPU context -----------------------------------


def test_the_snapshot_pushes_the_host_regions_window():
    capture = _code(_block(THUMBS, "bool view3d_scenes_drawer_snapshot_capture("))
    assert "CTX_wm_window" not in capture
    assert "view3d_scenes_drawer_region_window(wm, host_region)" in capture
    assert "Mixar_window_gpu_context_push(wm, host_win)" in capture
    assert capture.index("host_win == nullptr") < capture.index("Mixar_window_gpu_context_push")
