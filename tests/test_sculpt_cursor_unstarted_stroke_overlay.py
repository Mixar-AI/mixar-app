# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins `src/source/blender/editors/sculpt_paint/mesh/paint_cursor.cc`, upstream's
file plus the hunk fenced by `/* MIXAR-2005 begin */ ... /* MIXAR-2005 end */`
(mixar-backend#2005).

The sculpt stroke operator allocates the session's `StrokeCache` when the button
goes down (`brush_stroke_init`) and fills it, `brush` included, in
`stroke_cache_init` only once the stroke reaches the mesh. `PaintStroke` marks
the stroke active from the press, so a press off the mesh with a Cloth brush
using Plane falloff drew `cloth::plane_falloff_preview_draw` from the blank cache
and read `ss.cache->brush->cloth_deform_type` through a null brush (a read of
0x4FC, `offsetof(Brush, cloth_deform_type)`). `mesh_cursor_active_draw` now
returns while the cache has no brush.

Upstream fixed the same crash in Fix #161820 (d01ad6a3bdc on 5.2, in v5.2.1;
6e2c6ca4258 on main) by passing the cursor's brush to `plane_falloff_preview_draw`;
delete the overlay once the pinned `plane_falloff_preview_draw` no longer reads
`ss.cache->brush`. Replayed in the app by the QA harness (AP-2005)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REL = "source/blender/editors/sculpt_paint/mesh/paint_cursor.cc"
CLOTH_REL = "source/blender/editors/sculpt_paint/mesh/sculpt_cloth.cc"
OVERLAY = ROOT / "src" / REL
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_DIRS = (ROOT / "upstream", ROOT.parents[1] / "upstream")
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
MARKED = re.compile(r"[ \t]*/\* MIXAR-2005 begin \*/\n.*?[ \t]*/\* MIXAR-2005 end \*/\n\n?", re.S)
GUARD = "  if (!ss.cache->brush) {\n    return;\n  }\n"


def _upstream_dir() -> Path:
    found = next((d for d in UPSTREAM_DIRS if (d / REL).exists()), None)
    if found is None:
        pytest.skip("upstream submodule not checked out")
    return found


def _function(text: str, signature: str) -> str:
    start = text.find(signature)
    if start < 0:
        pytest.fail(
            f"{signature} not found: upstream changed the stroke start or the cursor draw, "
            "check whether the MIXAR-2005 hunk is still needed",
            pytrace=False)
    return text[start:text.index("\n}\n", start) + 3]


def _pin_carries_fix() -> bool:
    """Upstream Fix #161820 (d01ad6a3bdc on 5.2, 6e2c6ca4258 on main) hands the cursor's
    brush to `plane_falloff_preview_draw`, which then no longer reads the cache's."""
    cloth = (_upstream_dir() / CLOTH_REL).read_text(encoding="utf-8")
    preview = _function(cloth, "void plane_falloff_preview_draw(const uint gpuattr,")
    return "ss.cache->brush->" not in preview


def _skip_once_the_pin_carries_fix() -> None:
    if _pin_carries_fix():
        pytest.skip("the pin carries the upstream fix: see "
                    "test_the_pinned_upstream_lacks_the_fix_the_guard_stands_in_for")


def test_the_pinned_upstream_lacks_the_fix_the_guard_stands_in_for():
    if _pin_carries_fix():
        pytest.fail(
            "upstream now carries Fix #161820 (d01ad6a3bdc on 5.2, 6e2c6ca4258 on main: "
            "plane_falloff_preview_draw takes the cursor's brush): delete the paint_cursor.cc "
            "overlay, this test, the \"Sculpt cursor before the stroke starts\" section of "
            "docs/modules/crash-handling.md and the overlay's CLAUDE.md entry",
            pytrace=False)


def test_the_overlay_is_upstream_plus_the_marked_hunk():
    _skip_once_the_pin_carries_fix()
    upstream = (_upstream_dir() / REL).read_text(encoding="utf-8")
    overlay = OVERLAY.read_text(encoding="utf-8")
    assert overlay.count("/* MIXAR-2005 begin */") == 1
    assert MARKED.sub("", overlay.replace(MIXAR_SPDX, "", 1)) == upstream, (
        "paint_cursor.cc drifted from upstream: re-copy the upstream file and re-apply the "
        "MIXAR-2005 hunk")


def test_the_active_cursor_returns_before_reading_an_unfilled_cache():
    body = _function(OVERLAY.read_text(encoding="utf-8"),
                     "void mesh_cursor_active_draw(PaintCursorContext &pcontext)")
    guard = body.index(GUARD)
    assert body.index("if (!ss.cache) {") < guard
    # Before the first-step check (a blank cache reads `first_time == false`), any GPU
    # state change, and every preview helper that reads the cache.
    for later in ("stroke_is_first_brush_step_of_symmetry_pass(*ss.cache)", "wmViewport(",
                  "GPU_matrix_push", "cloth::plane_falloff_preview_draw(",
                  "multiplane_scrape_preview_draw(", "ss.cache->location"):
        assert guard < body.index(later), later


def test_upstream_still_allocates_the_cache_before_filling_its_brush():
    """The guard's premise. When this fails upstream changed the stroke start: check whether
    the hunk is still needed."""
    _skip_once_the_pin_carries_fix()
    up = _upstream_dir()
    sculpt = (up / "source/blender/editors/sculpt_paint/mesh/sculpt.cc").read_text(encoding="utf-8")
    init = _function(sculpt, "static void brush_stroke_init(bContext *C, const wmOperator *op)")
    assert "ss.cache = MEM_new<StrokeCache>(__func__);" in init, (
        "brush_stroke_init no longer allocates the StrokeCache")
    fill = _function(sculpt, "void SculptPaintStroke::stroke_cache_init(const float mval[2])")
    assert "cache->brush = brush;" in fill, "stroke_cache_init no longer sets cache->brush"
    start = _function(sculpt, "bool SculptPaintStroke::test_start(wmOperator *op, const float mval[2])")
    assert start.index("over_mesh(") < start.index("stroke_cache_init(mval);"), (
        "test_start no longer waits for over_mesh before stroke_cache_init")
    intern = (up / "source/blender/editors/sculpt_paint/mesh/sculpt_intern.hh").read_text(
        encoding="utf-8")
    assert "  const Brush *brush = nullptr;" in intern, "the cache's brush no longer starts null"
    stroke = (up / "source/blender/editors/sculpt_paint/paint_stroke.cc").read_text(encoding="utf-8")
    # v5.2.1 changed the third parameter to `const wmEvent *event`.
    ctor = _function(stroke, "PaintStroke::PaintStroke(")
    assert "paint_runtime->stroke_active = true;" in ctor, (
        "the PaintStroke constructor no longer marks the stroke active")
