# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Key selection on the Director timeline is Blender's own.

Click, Shift+click, B-armed box select, A / Alt+A — the gesture set the Dope
Sheet trains every Blender user in. The dock used to keep a selection of
BEAT indices in its region runtime, so only the beats could be selected and
nothing it selected showed in the Timeline. The gestures now hit-test the key
columns the draw published and hand their frames to
`mixar.director_select_keys`, which writes the keys' own select flags.
"""

from __future__ import annotations

from pathlib import Path

from mixar.modules.director.ui.operators.selection_ops import parse_indices

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
SELECT = (VIEW3D / "view3d_director_timeline_select.cc").read_text(encoding="utf-8")
RUNTIME = (VIEW3D / "view3d_director_timeline.hh").read_text(encoding="utf-8")
DRAW = (VIEW3D / "view3d_director_timeline_draw.cc").read_text(encoding="utf-8")
INTERACTION = (VIEW3D / "view3d_director_timeline_interaction.cc").read_text(encoding="utf-8")
CMAKE = (VIEW3D / "CMakeLists.txt").read_text(encoding="utf-8")
KEY_OPS = (
    ROOT / "src/scripts/mixar/modules/director/ui/operators/key_ops.py"
).read_text(encoding="utf-8")


def _block(source: str, start: str) -> str:
    body = source[source.index(start) :]
    return body[: body.index("\n}\n") + 3]


def test_indices_are_parsed_defensively():
    """Shift+D still hands beat indices to the duplicate operator, which is
    callable from anywhere — the search, a script, a macro."""
    assert parse_indices("2,0,1") == [2, 0, 1]
    assert parse_indices(" 3 , 3 , 1 ") == [3, 1]
    assert parse_indices("") == []
    assert parse_indices("a,,-1,2") == [2]


def test_the_gesture_module_is_built():
    assert "view3d_director_timeline_select.cc" in CMAKE


def test_no_selection_lives_in_the_dock():
    """The selection is the keys' own; the runtime keeps only the box."""
    assert "blender::Vector<int> selected;" not in RUNTIME
    assert "box_dragging" in RUNTIME
    assert "director_timeline_selection_sync" not in DRAW


def test_frames_travel_locale_independently():
    """Integers only: `%f` reads the C locale, and floating-point
    `std::to_chars` is missing on older macOS deployment targets."""
    body = _block(SELECT, "std::string director_timeline_frames_string(")
    assert "std::llround(double(frame) * 1000.0)" in body
    assert "std::to_string(magnitude / 1000)" in body
    assert "std::to_chars(" not in body
    assert "printf" not in body


def _frames_string(frames):
    """The C++ above, transcribed, so its output is pinned against the
    Python parser that reads it."""
    parts = []
    for frame in frames:
        milli = round(frame * 1000.0)
        magnitude = abs(milli)
        parts.append(f"{'-' if milli < 0 else ''}{magnitude // 1000}.{magnitude % 1000:03d}")
    return ",".join(parts)


def test_the_parser_reads_what_the_dock_writes():
    from mixar.modules.director.core.native_keys import parse_frames

    frames = [12.0, 3.5, -0.25, 0.004, 1048574.0]
    assert _frames_string(frames) == "12.000,3.500,-0.250,0.004,1048574.000"
    assert parse_frames(_frames_string(frames)) == sorted(frames)


def test_every_gesture_goes_through_the_select_operator():
    body = _block(SELECT, "bool select_keys(")
    assert '"mixar.director_select_keys"' in body
    assert 'RNA_enum_set_identifier(C, &op_ptr, "mode", mode);' in body
    assert "select_columns(shot.camera, parse_frames(self.frames), self.mode)" in KEY_OPS


def test_shift_click_toggles_and_never_starts_a_drag():
    """Building a selection must not retime what is already in it."""
    body = SELECT[SELECT.index("/* ---- Shift+click on a key ---- */") :]
    body = body[: body.index("/* ---- Duplicate")]
    assert "event->modifier & KM_SHIFT" in body
    assert '"TOGGLE"' in body
    assert "drag_keys" not in body


def test_a_plain_click_is_the_drags_and_selects_on_its_press():
    """The Dope Sheet's click rule: an unselected key becomes THE selection;
    a selected one keeps the selection for the drag and narrows to itself
    only if the press never moved."""
    invoke = KEY_OPS.split("def invoke(self, context, event):", 1)[1].split("def _release", 1)[0]
    assert "if column_selected(camera, self.frame):" in invoke
    assert "self._narrow_on_click = True" in invoke
    assert "select_columns(camera, [self.frame], 'SET')" in invoke
    release = KEY_OPS.split("if not self._drag.delta:", 1)[1][:200]
    assert "if self._narrow_on_click:" in release


def test_box_select_is_armed_by_b_and_can_be_disarmed():
    """B must not leave a box waiting for the next unrelated click."""
    assert "event->type == EVT_BKEY && event->val == KM_PRESS" in SELECT
    assert "runtime->box_arming && ELEM(event->type, EVT_ESCKEY, RIGHTMOUSE)" in SELECT


def test_box_select_takes_the_columns_it_meets_and_extends_with_shift():
    assert "runtime->box_extend = (event->modifier & KM_SHIFT) != 0;" in SELECT
    body = _block(SELECT, "blender::Vector<float> frames_in_box(")
    assert "BLI_rctf_isect(&box, &hit.bounds, nullptr)" in body
    assert 'runtime->box_extend ? "EXTEND" : "SET"' in SELECT


def test_select_all_and_deselect_all():
    body = SELECT[SELECT.index("/* ---- Select all / none ---- */") :]
    body = body[: body.index("/* ---- Shift+click")]
    assert "event->type == EVT_AKEY" in body
    assert '(event->modifier & KM_ALT) ? "NONE" : "ALL"' in body


def test_selecting_is_allowed_on_a_locked_take_editing_is_not():
    """Selection edits nothing; drags, deletes and duplicates do."""
    assert "!state.locked" in SELECT.split("/* ---- Duplicate ---- */", 1)[1]
    assert "if shot.state != 'DRAFT':" in KEY_OPS
    assert "shot.state == 'DRAFT'" in KEY_OPS.split("class MIXAR_OT_director_delete_keys", 1)[1]


def test_selection_is_asked_before_the_press_paths():
    handler = INTERACTION[INTERACTION.index("int timeline_ui_handler(") :]
    assert handler.index("director_timeline_selection_event(") < handler.index(
        "if (event->type == LEFTMOUSE && event->val == KM_PRESS) {"
    )


def test_every_key_editor_redraws_on_a_selection():
    """The Timeline shows what the dock selected at once."""
    assert "_KEY_EDITORS = {'VIEW_3D', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'NLA_EDITOR'}" in KEY_OPS


def test_the_rubber_band_is_drawn_over_what_it_selects():
    content = DRAW[DRAW.index("void view3d_director_timeline_draw_content(") :]
    assert content.index("draw_strip(region, state, runtime") < content.index(
        "director_timeline_box_rect(*runtime, &box)"
    )
    assert "BOX_FILL_COLOR" in DRAW and "BOX_LINE_COLOR" in DRAW
