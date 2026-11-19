# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins `src/source/blender/editors/sculpt_paint/mesh/sculpt.cc`, upstream's
file plus the hunks fenced by `/* MIXAR-2017 begin */ ... /* MIXAR-2017 end */`
(mixar-backend#2017). A mode switch while a stroke is held (`object.mode_set`
from a timer: the agent's `restore_turn_mode`, MCP and agent scripts) frees
`ob.runtime->sculpt_session` or replaces it with a session that has no stroke
cache, and the still-running `SCULPT_OT_brush_stroke` modal dereferenced it:

* `SculptPaintStroke` records the session's cache (`cache_`) once
  `test_start` has initialised it.
* `stroke_lost_session` reports a missing session or cache, a different cache
  or an object out of Sculpt Mode.
* `SculptPaintStroke::done` returns after `brush_exit_tex` without a session.
* `brush_stroke_modal` ends the stroke before `stroke->modal()` steps it.
* `sculpt_brush_stroke_cancel` (handler removal on file load or window close)
  skips the undo restore unless the stroke's own object is active and holds
  its session, and always ends the stroke.

`tests/test_sculpt_stroke_done.py` runs the overlay's `done()` and
`stroke_lost_session` natively. Delete a hunk once upstream handles a freed or
replaced session there."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "source/blender/editors/sculpt_paint/mesh/sculpt.cc"
OVERLAY = ROOT / "src" / RELATIVE
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_CANDIDATES = (
    ROOT / "upstream" / RELATIVE,
    ROOT.parents[1] / "upstream" / RELATIVE,
)
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
MARKED = re.compile(r"[ \t]*/\* MIXAR-2017 begin \*/\n.*?[ \t]*/\* MIXAR-2017 end \*/\n", re.S)

DONE = "void SculptPaintStroke::done(bool is_cancel, bool stroke_started)\n{\n"
MODAL = (
    "static wmOperatorStatus brush_stroke_modal(bContext *C, wmOperator *op, "
    "const wmEvent *event)\n{\n"
)
CANCEL = "static void sculpt_brush_stroke_cancel(bContext *C, wmOperator *op)\n{\n"
TEST_START = "bool SculptPaintStroke::test_start(wmOperator *op, const float mval[2])\n{\n"
STRUCT = "struct SculptPaintStroke final : public PaintStroke {\n"
HELPER = "static bool stroke_lost_session(const SculptPaintStroke &stroke)\n{\n"
HUNKS = 6


def _function(text: str, signature: str) -> str:
    start = text.index(signature)
    end = "\n};\n" if signature.startswith("struct ") else "\n}\n"
    return text[start:text.index(end, start) + len(end)]


def _strip_comments(text: str) -> str:
    return re.sub(r"[ \t]*/\*.*?\*/\n?", "", text, flags=re.S)


def _overlay_function(signature: str) -> str:
    return _strip_comments(_function(OVERLAY.read_text(encoding="utf-8"), signature))


def _unpatched(text: str) -> str:
    return MARKED.sub("", text.replace(MIXAR_SPDX, "", 1))


def _ordered(text: str, *parts: str) -> bool:
    positions = [text.find(part) for part in parts]
    return -1 not in positions and positions == sorted(positions)


def test_the_stroke_records_its_cache_right_after_initialising_it():
    assert "\n  StrokeCache *cache_ = nullptr;\n" in _overlay_function(STRUCT)
    body = _overlay_function(TEST_START)
    assert (
        "    stroke_cache_init(mval);\n    cache_ = ob.runtime->sculpt_session->cache;\n"
    ) in body
    assert body.count("cache_ =") == 1


def test_the_lost_session_check_precedes_its_users():
    text = OVERLAY.read_text(encoding="utf-8")
    assert _ordered(text, HELPER, CANCEL, MODAL)
    assert _strip_comments(text).count("stroke_lost_session(") == 3


def test_done_returns_before_dereferencing_a_freed_session():
    body = _overlay_function(DONE)
    assert _ordered(
        body,
        "if (!ob.runtime->sculpt_session) {\n    brush_exit_tex(*this->sculpt_);\n    return;\n  }",
        "SculptSession &ss = *ob.runtime->sculpt_session;",
    )


def test_modal_ends_the_stroke_before_stepping_it_on_a_lost_session():
    body = _overlay_function(MODAL)
    assert _ordered(
        body,
        "if (stroke_lost_session(*stroke)) {",
        "stroke->cancel(C);",
        "MEM_delete(stroke);",
        "op->customdata = nullptr;",
        "return OPERATOR_CANCELLED;",
        "stroke->modal(C, op, event)",
    )


def test_cancel_restores_undo_only_on_the_strokes_own_live_session():
    body = _overlay_function(CANCEL)
    assert _ordered(
        body,
        "SculptPaintStroke *stroke = static_cast<SculptPaintStroke *>(op->customdata);",
        "stroke_lost_session(*stroke) || CTX_data_active_object(C) != stroke->object",
        "stroke->cancel(C);\n    return;",
        "BLI_assert(!dyntopo::stroke_is_dyntopo(ob, brush));",
        "undo::restore_from_undo_step(depsgraph, sd, ob);\n  stroke->cancel(C);\n}\n",
    )
    assert body.count("restore_from_undo_step") == 1


def test_the_overlay_is_upstream_plus_the_marked_hunks():
    """Keep every change fenced so an upstream bump is a re-copy plus re-apply."""
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        pytest.skip("upstream submodule not checked out")
    ov = OVERLAY.read_text(encoding="utf-8")
    assert ov.count("/* MIXAR-2017 begin */") == ov.count("/* MIXAR-2017 end */") == HUNKS
    assert MIXAR_SPDX in ov
    unpatched = _unpatched(ov)
    up = upstream.read_text(encoding="utf-8")
    if unpatched != up:
        old, new = unpatched.splitlines(), up.splitlines()
        line = next(
            (i for i, pair in enumerate(zip(old, new)) if pair[0] != pair[1]),
            min(len(old), len(new)),
        )
        pytest.fail(
            "upstream sculpt.cc changed (first difference at upstream line "
            f"{line + 1}), or an overlay edit is not fenced: re-copy the upstream file, "
            "re-add the Mixar SPDX line and re-apply the MIXAR-2017 hunks",
            pytrace=False,
        )
