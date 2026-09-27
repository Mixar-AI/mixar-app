# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene-card thumbnails are snapshots of the viewport, never renders.

Two Windows crash reports (4.0.3, multi-scene sessions) put the old card path
next to the faults: a timer rendered EVERY tab's scene offscreen with EEVEE
material shading whenever the host viewport was in Material or Rendered
shading, re-rendering on each edit-mode toggle, while Cycles drew the
viewport; the AMD driver's own worker thread faulted under that load. The
replacement copies the host viewport's already-drawn frame:

- the thumbnail source has no render, no depsgraph evaluation and no engine
  call left, and reads the region's own ``GPUViewport``;
- the Python tab switch snapshots the leaving tab BEFORE any window changes
  scene, so a card shows the tab as it was last seen;
- snapshots are guarded (resize dispatch, render, no GPU context, locked
  interface, island/pill drag) and fail closed: the last pixels are kept and
  repeated failures disable them for the session; ``MIXAR_SCENES_DRAWER_THUMBS=0``
  turns them off without a rebuild.

``bpy`` is a MagicMock in this suite, so these are source-level contracts.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
THUMBS = (VIEW3D / "view3d_scenes_drawer_thumbs.cc").read_text()
OPS = (VIEW3D / "view3d_scenes_drawer_ops.cc").read_text()
QA = (VIEW3D / "view3d_scenes_drawer_qa.cc").read_text()
HEADER = (ROOT / "src/source/blender/editors/include/ED_scenes_drawer.hh").read_text()
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"
TAB_OPS = (CHAT / "ui/operators/scene_tab_ops.py").read_text()
SNAPSHOT = (CHAT / "core/scene_tab_snapshot.py").read_text()
PROPS = (CHAT / "ui/properties/scene_tabs_props.py").read_text()


def test_thumbnails_never_render_a_scene():
    """No draw engine, no depsgraph evaluation, no offscreen scene render."""
    for banned in (
        "ED_view3d_draw_offscreen",
        "BKE_scene_graph_update_tagged",
        "BKE_scene_ensure_depsgraph",
        "DRW_draw",
        "DEG_OBJECT_ITER",
        "GPU_offscreen_create",
    ):
        assert banned not in THUMBS, banned
    assert "WM_draw_region_get_viewport" in THUMBS
    # Blender's colour-picker recipe: copy to a host-readable twin, read back.
    # A viewport texture sampled by a shader outside its frame is black on Metal.
    assert "GPU_texture_copy(copy, src)" in THUMBS
    assert "GPU_viewport_draw_to_screen" not in THUMBS.split("static bool snapshot_read_viewport")[1]
    assert "Mixar_window_gpu_context_push" in THUMBS
    assert "GPUOffScreen" not in HEADER.split("struct ScenesDrawerThumb")[1].split("};")[0]


def test_snapshot_guards_and_fail_closed():
    assert "Mixar_window_resize_dispatch_active()" in THUMBS
    assert "G.is_rendering" in THUMBS
    assert "GPU_context_active_get() == nullptr" in THUMBS
    assert "is_interface_locked" in THUMBS
    assert 'WM_operatortype_find("MIXAR_OT_bubble_header_drag"' in THUMBS
    assert "MIXAR_SCENES_DRAWER_THUMBS" in THUMBS
    assert "SNAPSHOT_MAX_FAILURES" in THUMBS
    # A failed read-back keeps the previous pixels: the entry is only replaced
    # after the read succeeded.
    body = THUMBS.split("bool view3d_scenes_drawer_snapshot_capture")[1]
    assert body.index("snapshot_read_viewport(viewport") < body.index("entry.pixels = std::move(pixels)")


def test_operators_registered_and_tick_refreshes_only_the_shown_tab():
    assert "WM_operatortype_append(VIEW3D_OT_scenes_drawer_snapshot)" in OPS
    assert "WM_operatortype_append(VIEW3D_OT_scenes_drawer_thumbs)" in OPS
    tick = OPS.split("static wmOperatorStatus drawer_thumbs_exec")[1].split("static void VIEW3D_OT")[0]
    assert "runtime->cards" not in tick, "the tick must not walk every card"
    assert "CTX_data_scene(C)" in tick
    assert "/*force=*/false" in tick
    force = OPS.split("static wmOperatorStatus drawer_snapshot_exec")[1].split("static void VIEW3D_OT")[0]
    assert "/*force=*/true" in force


def test_qa_exports_a_thumb_target_with_snapshot_state():
    assert '"scenes_drawer_card_thumb"' in QA
    assert 'view3d_scenes_drawer_snapshot_exists(card.scene_name) ? "snapshot" : "none"' in QA


def _calls_in_order(func: ast.FunctionDef) -> list:
    """Call names in SOURCE order (``ast.walk`` is breadth-first)."""
    calls = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            target = node.func
            name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            calls.append((node.lineno, node.col_offset, name))
    return [name for _, _, name in sorted(calls)]


def test_tab_switch_snapshots_the_leaving_tab_first():
    tree = ast.parse(TAB_OPS)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in ("switch_scene_tab", "new_scene_tab"):
        calls = _calls_in_order(funcs[name])
        assert "snapshot_shown_tab" in calls, name
        assert calls.index("snapshot_shown_tab") < calls.index("switch_all_windows"), name


def test_snapshot_helper_never_raises_and_props_share_the_override():
    assert "except Exception" in SNAPSHOT
    assert "bpy.ops.view3d.scenes_drawer_snapshot()" in SNAPSHOT
    assert "from ...core.scene_tab_snapshot import zen_view3d_override" in PROPS
    assert "def _view3d_override" not in PROPS
