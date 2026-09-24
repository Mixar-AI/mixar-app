# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Multi-keyframe selection on the Director timeline.

Click, Shift+click, B-armed box select, A / Alt+A — the gesture set the Dope
Sheet trains every Blender user in — plus the drag and delete that act on the
result. The gestures are native (the selection is view state, beside the hit
rects it refers to); the MOVES stay Python operators.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director.core.timeline import move_beats
from mixar.modules.director.ui.operators.selection_ops import parse_indices

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
SELECT = (VIEW3D / "view3d_director_timeline_select.cc").read_text(encoding="utf-8")
RUNTIME = (VIEW3D / "view3d_director_timeline.hh").read_text(encoding="utf-8")
DRAW = (VIEW3D / "view3d_director_timeline_draw.cc").read_text(encoding="utf-8")
INTERACTION = (VIEW3D / "view3d_director_timeline_interaction.cc").read_text(encoding="utf-8")
CMAKE = (VIEW3D / "CMakeLists.txt").read_text(encoding="utf-8")
OPS = (
    ROOT / "src/scripts/mixar/modules/director/ui/operators/selection_ops.py"
).read_text(encoding="utf-8")


# -------------------------------------------------------------------------
# The indices contract between the native gestures and the Python operators.


def test_indices_are_parsed_defensively():
    """The string comes from the native timeline, but an operator is callable
    from anywhere — the search, a script, a macro."""
    assert parse_indices("2,0,1") == [2, 0, 1]
    assert parse_indices(" 3 , 3 , 1 ") == [3, 1]
    assert parse_indices("") == []
    assert parse_indices("a,,-1,2") == [2]


# -------------------------------------------------------------------------
# Moving a selection.


class _Beat:
    def __init__(self, frame):
        self.frame = frame


def _shot(frames):
    return SimpleNamespace(state='DRAFT', beats=[_Beat(frame) for frame in frames])


def test_a_selection_moves_in_the_order_that_keeps_its_path_clear(monkeypatch):
    """`move_single_beat` clamps a beat against its neighbours, so moving a
    selection left-to-right rightwards walks each beat into the one ahead and
    the whole selection collapses."""
    import mixar.modules.director.core.timeline as timeline

    order = []

    def _move(_scene, shot, index, delta, rebuild_manifest=True):
        order.append(index)
        shot.beats[index].frame += delta
        return delta

    monkeypatch.setattr(timeline, "move_single_beat", _move)
    monkeypatch.setattr(timeline, "refresh_manifest", lambda *a, **k: None)
    shot = _shot([10, 20, 30])
    move_beats(None, shot, [0, 1, 2], +5)
    # Rightwards: the LAST beat first.
    assert order == [2, 1, 0]

    order.clear()
    move_beats(None, shot, [0, 1, 2], -5)
    # Leftwards: the first beat first.
    assert order == [0, 1, 2]


def test_the_selection_keeps_its_spacing_when_one_end_hits_a_clamp(monkeypatch):
    """A selection that stays recognisable is worth more than one beat
    squeezing the last frame it could."""
    import mixar.modules.director.core.timeline as timeline

    def _move(_scene, shot, index, delta, rebuild_manifest=True):
        # Beat 2 can only manage 2 of any rightward move.
        allowed = 2 if (index == 2 and delta > 0) else delta
        shot.beats[index].frame += allowed
        return allowed

    monkeypatch.setattr(timeline, "move_single_beat", _move)
    monkeypatch.setattr(timeline, "refresh_manifest", lambda *a, **k: None)
    shot = _shot([10, 20, 30])
    assert move_beats(None, shot, [0, 1, 2], +5) == 2
    assert [beat.frame for beat in shot.beats] == [12, 22, 32]


def test_a_clamp_found_late_does_not_double_move_the_earlier_beats(monkeypatch):
    """The whole first pass is undone before the uniform re-apply.

    Putting back only the constrained beat leaves the ones already moved at
    the requested delta — and the uniform pass then moves them a SECOND time.
    """
    import mixar.modules.director.core.timeline as timeline

    def _move(_scene, shot, index, delta, rebuild_manifest=True):
        # Beat 0 is the LAST to move on a rightward drag, and the only one
        # that cannot take the full delta.
        allowed = 2 if (index == 0 and delta > 0) else delta
        shot.beats[index].frame += allowed
        return allowed

    monkeypatch.setattr(timeline, "move_single_beat", _move)
    monkeypatch.setattr(timeline, "refresh_manifest", lambda *a, **k: None)
    shot = _shot([10, 20, 30])
    assert move_beats(None, shot, [0, 1, 2], +5) == 2
    assert [beat.frame for beat in shot.beats] == [12, 22, 32]


def test_no_indices_or_no_delta_is_a_no_op():
    shot = _shot([10, 20])
    assert move_beats(None, shot, [], 5) == 0
    assert move_beats(None, shot, [0], 0) == 0


# -------------------------------------------------------------------------
# Removing a selection.


def test_removal_goes_highest_index_first():
    """`beats.remove(i)` shifts everything after i."""
    tree = ast.parse(OPS)
    execute = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "execute"
    )
    source = ast.unparse(execute)
    assert "reverse=True" in source


# -------------------------------------------------------------------------
# The native gestures.


def test_the_gesture_module_is_built():
    assert "view3d_director_timeline_select.cc" in CMAKE


def test_the_selection_is_view_state_in_the_region_runtime():
    assert "blender::Vector<int> selected;" in RUNTIME
    assert "box_dragging" in RUNTIME


def test_a_selection_is_dropped_when_an_index_stops_meaning_anything():
    """A shot switch or a beat added or removed renumbers everything."""
    body = SELECT[SELECT.index("void director_timeline_selection_sync(") :]
    body = body[: body.index("\n}\n")]
    assert "runtime->shot_identity != shot_identity || runtime->content_count != beat_count" in body
    assert "runtime->selected.clear();" in body
    # Called BEFORE the identity and count are overwritten.
    sync = DRAW[DRAW.index("void sync_view(") :]
    sync = sync[: sync.index("\n}\n")]
    assert sync.index("director_timeline_selection_sync(") < sync.index(
        "runtime->shot_identity = state.shot_identity;"
    )


def test_shift_click_extends_and_never_starts_a_drag():
    """Building a selection must not retime what is already in it."""
    body = SELECT[SELECT.index("/* ---- Click and Shift+click on a handle ---- */") :]
    shift = body[: body.index("if (!director_timeline_is_selected")]
    assert "event->modifier & KM_SHIFT" in shift
    assert "select_toggle(runtime, hovered_beat);" in shift
    assert "drag_beats" not in shift


def test_a_plain_click_on_an_unselected_handle_replaces_the_selection():
    body = SELECT[SELECT.index("/* ---- Click and Shift+click on a handle ---- */") :]
    assert "if (!director_timeline_is_selected(*runtime, hovered_beat)) {" in body
    assert "select_only(runtime, hovered_beat);" in body


def test_only_a_multi_selection_takes_the_multi_drag():
    """A single handle keeps the existing single-beat drag, which also jumps
    the playhead on invoke."""
    body = SELECT[SELECT.index("/* ---- Click and Shift+click on a handle ---- */") :]
    assert "runtime->selected.size() > 1" in body
    assert '"mixar.director_drag_beats"' in body


def test_delete_falls_back_to_the_single_keyframe_rule():
    body = SELECT[SELECT.index("/* ---- Delete a multi-selection ---- */") :]
    assert "runtime->selected.size() > 1" in body
    assert '"mixar.director_remove_beats"' in body
    assert "A multi-selection is handled above; this is the single-keyframe rule." in INTERACTION


def test_box_select_is_armed_by_b_and_can_be_disarmed():
    """B must not leave a box waiting for the next unrelated click."""
    assert "event->type == EVT_BKEY && event->val == KM_PRESS" in SELECT
    assert "runtime->box_arming && ELEM(event->type, EVT_ESCKEY, RIGHTMOUSE)" in SELECT


def test_box_select_extends_with_shift():
    assert "runtime->box_extend = (event->modifier & KM_SHIFT) != 0;" in SELECT
    body = SELECT[SELECT.index("void select_in_box(") :]
    body = body[: body.index("\n}\n")]
    assert "if (!out->box_extend) {" in body
    assert "BLI_rctf_isect(&box, &hit.bounds, nullptr)" in body


def test_select_all_and_deselect_all():
    body = SELECT[SELECT.index("/* ---- Select all / none ---- */") :]
    body = body[: body.index("/* ---- Click")]
    assert "event->type == EVT_AKEY" in body
    assert "event->modifier & KM_ALT" in body
    assert "runtime->selected.clear();" in body
    assert "select_all(runtime, beat_count);" in body


def test_a_locked_take_cannot_be_box_selected_dragged_or_deleted():
    assert "event->val == KM_PRESS && !state.locked" in SELECT
    assert "!state.locked && runtime->selected.size() > 1" in SELECT


def test_selection_is_asked_before_the_single_handle_paths():
    handler = INTERACTION[INTERACTION.index("int timeline_ui_handler(") :]
    assert handler.index("director_timeline_selection_event(") < handler.index(
        "if (event->type == LEFTMOUSE && event->val == KM_PRESS) {"
    )


def test_a_selected_handle_is_ringed_not_merely_lit():
    """The active keyframe and a hover are already lit, so a selection of one
    would otherwise be invisible."""
    assert "const bool selected = director_timeline_is_selected(*runtime, beat.index);" in DRAW
    assert "SELECTED_OUTLINE_COLOR" in DRAW


def test_the_rubber_band_is_drawn_over_what_it_selects():
    content = DRAW[DRAW.index("void view3d_director_timeline_draw_content(") :]
    assert content.index("draw_strip(region, state, runtime") < content.index(
        "director_timeline_box_rect(*runtime, &box)"
    )
    assert "BOX_FILL_COLOR" in DRAW and "BOX_LINE_COLOR" in DRAW
