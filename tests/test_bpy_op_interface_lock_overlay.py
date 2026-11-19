# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins `src/source/blender/python/intern/bpy_operator_function.cc`: upstream's
file plus one hunk fenced by `/* MIXAR-2058 begin */ ... /* MIXAR-2058 end */`.

Every `bpy.ops` call updates the view-layer depsgraph before and after the
operator. A render or bake locks the interface, and the main loop then skips
its own depsgraph update (`wm_event_do_depsgraph`) because the job thread owns
the data, but timers keep running: a timer calling `bpy.ops` evaluated the
graph the render thread was tagging and crashed in `deg_graph_flush_updates`
(mixar-backend#2058). The hunk makes `bpy_op_view_layer_update` skip the update
while the interface is locked, the same rule the main loop follows."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REL = "source/blender/python/intern/bpy_operator_function.cc"
OVERLAY = ROOT / "src" / REL
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_CANDIDATES = (ROOT / "upstream" / REL, ROOT.parents[1] / "upstream" / REL)
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
MARKED = re.compile(r"[ \t]*/\* MIXAR-2058 begin \*/\n.*?[ \t]*/\* MIXAR-2058 end \*/\n\n", re.S)
GUARD = "  if (CTX_wm_manager(C) && CTX_wm_interface_locked(C)) {\n    return;\n  }\n"


def _function(text: str, name: str) -> str:
    start = text.index(f" {name}(bContext *C)\n{{")
    start = text.rindex("\n", 0, start) + 1
    return text[start:text.index("\n}\n", start) + 3]


def test_view_layer_update_returns_first_while_the_interface_is_locked():
    body = _function(OVERLAY.read_text(encoding="utf-8"), "bpy_op_view_layer_update")
    guard = body.find(GUARD)
    assert guard != -1
    for call in ("BKE_main_view_layers_synced_ensure", "BKE_scene_ensure_depsgraph",
                 "BKE_scene_graph_update_tagged", "DEG_make_active"):
        assert guard < body.index(call), call


def test_the_overlay_is_upstream_plus_the_marked_hunk():
    """Keep the change fenced so an upstream bump is a re-copy plus re-apply."""
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        pytest.skip("upstream submodule not checked out")
    up = upstream.read_text(encoding="utf-8")
    if "interface_locked" in _function(up, "bpy_op_view_layer_update"):
        pytest.fail("upstream now skips the update while locked: delete the overlay")
    ov = OVERLAY.read_text(encoding="utf-8")
    assert ov.count("/* MIXAR-2058 begin */") == ov.count("/* MIXAR-2058 end */") == 1
    assert MIXAR_SPDX in ov
    unpatched = MARKED.sub("", ov.replace(MIXAR_SPDX, "", 1))
    if unpatched != up:
        pytest.fail(
            "upstream bpy_operator_function.cc changed, or an overlay edit is not fenced: "
            "re-copy the upstream file and re-apply the MIXAR-2058 hunk",
            pytrace=False,
        )
