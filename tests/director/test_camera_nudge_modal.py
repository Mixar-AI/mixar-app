# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level contract of the native hold-to-move camera nudge.

`mixar.director_nudge_camera` is a C++ modal operator: one key press starts
it, a timer integrates every held direction at walk speed, and the whole
motion is one undo step. These pins keep the keymap contract in
`director/ui/keymap.py` and the operator in step without a build.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
NUDGE = VIEW3D / "view3d_director_nudge.cc"

DIRECTIONS = ("FORWARD", "BACK", "LEFT", "RIGHT", "UP", "DOWN")
KEY_TO_DIRECTION = {
    "W": "FORWARD",
    "S": "BACK",
    "A": "LEFT",
    "D": "RIGHT",
    "E": "UP",
    "Q": "DOWN",
}


def _source() -> str:
    return NUDGE.read_text(encoding="utf-8")


def _block(source: str, start: str) -> str:
    body = source[source.index(start):]
    return body[: body.index("\n}\n") + 3]


def test_python_nudge_operator_is_gone():
    assert not (DIRECTOR / "ui/operators/nudge_ops.py").exists()
    assert not (DIRECTOR / "core/camera_nudge.py").exists()
    for path in DIRECTOR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "class MIXAR_OT_director_nudge_camera" not in text, path
        assert "camera_nudge" not in text, path


def test_operator_is_registered_from_the_view3d_space():
    source = _source()
    assert "void view3d_director_operatortypes()" in source
    assert "WM_operatortype_append(MIXAR_OT_director_nudge_camera);" in source
    space = (VIEW3D / "space_view3d.cc").read_text(encoding="utf-8")
    assert "view3d_director_operatortypes();" in space
    cmake = (VIEW3D / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "view3d_director_nudge.cc" in cmake
    header = (VIEW3D / "view3d_director.hh").read_text(encoding="utf-8")
    assert "void view3d_director_operatortypes();" in header


def test_direction_enum_matches_the_keymap_identifiers():
    source = _source()
    keymap = (DIRECTOR / "ui/keymap.py").read_text(encoding="utf-8")
    for identifier in DIRECTIONS:
        assert f'"{identifier}"' in source
        assert f'"{identifier}")' in keymap
    assert 'RNA_def_enum(ot->srna,\n               "direction",' in source
    assert 'ot->name = "Move Camera";' in source


def test_modal_handles_every_key_with_press_and_release():
    source = _source()
    mapping = _block(source, "static int nudge_direction_from_key(")
    for key, direction in KEY_TO_DIRECTION.items():
        assert re.search(rf"case EVT_{key}KEY:\s*return NUDGE_{direction};", mapping), key
    keymap = (DIRECTOR / "ui/keymap.py").read_text(encoding="utf-8")
    for key, direction in KEY_TO_DIRECTION.items():
        assert f"('{key}', \"{direction}\")" in keymap
    modal = _block(source, "static wmOperatorStatus director_nudge_modal(")
    assert "event->val == KM_PRESS" in modal
    assert "event->val == KM_RELEASE" in modal
    assert "data->held |= bit;" in modal
    assert "data->held &= ~nudge_bit(direction);" in modal
    assert "EVT_ESCKEY, RIGHTMOUSE" in modal


def test_one_timer_at_sixty_hertz_drives_the_motion():
    source = _source()
    assert "NUDGE_TIMER_STEP = 1.0 / 60.0" in source
    assert source.count("WM_event_timer_add(") == 1
    assert "TIMER, NUDGE_TIMER_STEP" in source
    assert "WM_event_timer_remove(" in source
    assert "std::clamp(now - data->last_tick, 0.0, NUDGE_MAX_STEP_SECONDS)" in source
    assert "NUDGE_MAX_STEP_SECONDS = 0.1" in source


def test_whole_held_motion_is_one_undo_step():
    source = _source()
    assert "ot->flag = OPTYPE_UNDO;" in source
    assert "UNDO_GROUPED" not in source.replace("never UNDO_GROUPED", "")
    finish = _block(source, "static wmOperatorStatus director_nudge_finish(")
    assert "moved ? OPERATOR_FINISHED : OPERATOR_CANCELLED" in finish


def test_camera_moves_through_its_world_matrix_at_walk_speed():
    source = _source()
    assert "BKE_object_apply_mat4(camera, data->matrix.ptr(), true, true);" in source
    assert "data->matrix = camera->object_to_world();" in source
    assert "DEG_id_tag_update(&camera->id, ID_RECALC_TRANSFORM);" in source
    assert "WM_event_add_notifier(C, NC_OBJECT | ND_TRANSFORM, camera);" in source
    speed = _block(source, "static float nudge_walk_speed()")
    assert "U.walk_navigation.walk_speed" in speed
    assert "NUDGE_DEFAULT_WALK_SPEED" in speed
    assert "NUDGE_DEFAULT_WALK_SPEED = 3.0f" in source


def test_diagonals_are_normalised_and_vertical_is_world_z():
    source = _source()
    vector = _block(source, "static float3 nudge_direction_vector(")
    assert "return math::normalize(sum);" in vector
    assert "-math::normalize(matrix.z_axis())" in vector
    assert "math::normalize(matrix.x_axis())" in vector
    assert "float3 up(0.0f, 0.0f, 1.0f)" in vector


def test_foreign_events_pass_through_and_locked_takes_absorb():
    source = _source()
    modal = _block(source, "static wmOperatorStatus director_nudge_modal(")
    assert "OPERATOR_PASS_THROUGH" in modal
    assert "OPERATOR_RUNNING_MODAL | OPERATOR_PASS_THROUGH" not in modal
    invoke = _block(source, "static wmOperatorStatus director_nudge_invoke(")
    assert "This take is locked; start a new take to move the camera" in invoke
    assert invoke.count("return OPERATOR_CANCELLED;") == 2
    assert "WM_event_add_modal_handler(C, op);" in invoke
    assert "return OPERATOR_RUNNING_MODAL;" in invoke
    assert "bpy" not in source and "Python" not in source.split("namespace blender")[1]


def test_a_fresh_press_is_worth_a_tap_step():
    """A press-and-release inside one event batch never sees a timer tick;
    the press itself moves NUDGE_TAP_SECONDS' worth so a tap registers, and
    OS auto-repeat PRESSes for an already-held key add nothing."""
    text = _source()
    assert "constexpr double NUDGE_TAP_SECONDS = 0.05;" in text
    assert "nudge_apply(C, data, camera, data->held, NUDGE_TAP_SECONDS);" in text
    modal = text[text.index("static wmOperatorStatus director_nudge_modal(") :]
    assert "if ((data->held & bit) == 0) {" in modal
    assert "nudge_apply(C, data, camera, bit, NUDGE_TAP_SECONDS);" in modal
