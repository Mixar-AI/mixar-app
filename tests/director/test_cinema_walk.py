# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Cinema walk: `mixar.director_walk`.

Blender's own `view3d.walk` gets two rules wrong for directing. Every mouse
motion turns the camera, so reaching for a card re-aims the shot; and a left
click confirms and exits, which makes the one gesture a director reaches for
— click and drag to look — the gesture that ends the walk.

Forking upstream's walk would mean carrying gravity, jump, teleport and
view-height that a camera never uses, and re-porting it on every Blender
bump. The movement half already existed natively (the hold-to-move nudge), so
the Cinema walk is that kept alive between key presses, plus mouse-look, with
the direction math shared so a key cannot mean two things.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
WALK = (VIEW3D / "view3d_director_walk.cc").read_text(encoding="utf-8")
# The mouse-look math, split out of the walk (500-line rule).
AIM = (VIEW3D / "view3d_director_walk_aim.cc").read_text(encoding="utf-8")
MOVE = (VIEW3D / "view3d_director_camera_move.cc").read_text(encoding="utf-8")
MOVE_HH = (VIEW3D / "view3d_director_camera_move.hh").read_text(encoding="utf-8")
NUDGE = (VIEW3D / "view3d_director_nudge.cc").read_text(encoding="utf-8")
TOP = (VIEW3D / "view3d_director_cinema_top.cc").read_text(encoding="utf-8")
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEWPORT = (DIRECTOR / "core/viewport.py").read_text(encoding="utf-8")


def _block(source: str, start: str) -> str:
    body = source[source.index(start):]
    return body[: body.index("\n}\n") + 3]


def _code(source: str) -> str:
    """`source` without its comment lines."""
    return "\n".join(
        line for line in source.split("\n")
        if not line.lstrip().startswith(("*", "/*", "//"))
    )


# ---- the two rules this exists to change -----------------------------------


def test_the_camera_turns_only_while_the_left_button_is_held():
    modal = _block(WALK, "wmOperatorStatus director_walk_modal(")
    assert "data->looking = true;" in modal
    move = modal[modal.index("event->type == MOUSEMOVE") :]
    assert "if (!data->looking) {" in move
    # A still button is a still frame, however far the pointer travels.
    assert move.index("if (!data->looking) {") < move.index("walk_look(")


def test_the_left_button_never_ends_the_walk():
    modal = _block(WALK, "wmOperatorStatus director_walk_modal(")
    # LEFTMOUSE is handled as a state, not a confirm.
    assert "if (event->type == LEFTMOUSE) {" in modal
    assert "OPERATOR_FINISHED" not in _block(WALK, "if (event->type == LEFTMOUSE) {")


def test_no_key_or_button_ends_the_walk():
    """The Walk chip is the one switch. Esc and the right button used to stop
    the walk too, so the chip's lit state was one of three ways out — and
    Cinema Mode opens walking, one stray Esc from not."""
    modal = _code(_block(WALK, "wmOperatorStatus director_walk_modal("))
    assert "EVT_ESCKEY" not in modal
    assert "RIGHTMOUSE" not in modal
    # What still ends it: the chip's request, leaving the mode, losing the
    # viewport or the camera — never an input event.
    tick = _block(WALK, "wmOperatorStatus director_walk_tick(")
    assert "if (director_walk_stop_requested(C)) {" in tick
    registration = _block(WALK, "void MIXAR_OT_director_walk(")
    assert "Esc" not in registration and "right-click" not in registration


def test_standing_still_is_not_an_exit():
    """The nudge ends a grace period after the last key release, because it
    IS the key press. A walk runs until it is stopped, so a director can
    stop, look, and drive on."""
    tick = _block(WALK, "wmOperatorStatus director_walk_tick(")
    idle = tick[tick.index("if (data->held == 0) {") :]
    assert "return OPERATOR_RUNNING_MODAL;" in idle[: idle.index("}")]
    assert "RELEASE_GRACE" not in WALK
    # The nudge keeps its own rule.
    assert "NUDGE_RELEASE_GRACE_SECONDS" in NUDGE


# ---- what it keeps from Blender --------------------------------------------


def test_shift_sprints_at_blenders_own_walk_speed():
    assert "constexpr float WALK_FAST_FACTOR" in WALK
    factor = _block(WALK, "float walk_speed_factor(")
    assert "if ((event->modifier & KM_SHIFT) != 0) {\n    return WALK_FAST_FACTOR;" in factor
    move = _block(WALK, "void walk_move(")
    assert "director_walk_speed() * speed_factor" in move
    speed = _block(MOVE, "float director_walk_speed()")
    assert "U.walk_navigation.walk_speed" in speed


def test_alt_creeps_the_way_blenders_walk_does():
    """Blender's walk divides by the same factor Shift multiplies by, and
    Shift wins when both are held."""
    assert "constexpr float WALK_SLOW_FACTOR = 1.0f / WALK_FAST_FACTOR;" in WALK
    factor = _block(WALK, "float walk_speed_factor(")
    assert "if ((event->modifier & KM_ALT) != 0) {\n    return WALK_SLOW_FACTOR;" in factor
    assert factor.index("KM_SHIFT") < factor.index("KM_ALT")
    # Read off the timer tick's modifier state: the Alt press itself is never
    # claimed, so whatever else listens for it still gets it.
    modal = _block(WALK, "wmOperatorStatus director_walk_modal(")
    assert "return director_walk_tick(C, op, data, walk_speed_factor(event));" in modal
    assert "EVT_LEFTALTKEY" not in WALK and "EVT_RIGHTALTKEY" not in WALK


def test_the_direction_math_is_shared_with_the_nudge():
    """One copy, so W cannot mean one thing to the nudge and another here."""
    assert "float3 director_move_vector(" in MOVE
    assert "int director_move_from_key(" in MOVE
    for source in (WALK, NUDGE):
        assert '#include "view3d_director_camera_move.hh"' in source
        assert "director_move_vector(" in source or "director_move_bit(" in source
    # And neither file re-derives it.
    assert "EVT_WKEY" not in WALK and "EVT_WKEY" not in NUDGE
    assert "EVT_WKEY" in MOVE


def test_gravity_and_teleport_are_not_carried():
    """Named in the file comment as what is deliberately absent; the CODE
    must not grow them back."""
    code = (_code(WALK) + _code(AIM)).lower()
    for absent in ("gravity", "teleport", "jump", "view_height"):
        assert absent not in code, absent


# ---- the aiming math -------------------------------------------------------


def test_the_walk_aims_through_the_shared_math_and_commits_once():
    look = _block(WALK, "void walk_look(")
    assert "if (director_walk_aim(data->matrix, dx, dy)) {" in look
    assert "walk_commit(C, data, camera);" in look
    assert "bool director_walk_aim(float4x4 &matrix, float dx, float dy);" in MOVE_HH
    # Pure math: the aim never touches context or writes the object.
    assert "bContext" not in _code(AIM) and "BKE_object_apply_mat4" not in _code(AIM)


def test_yaw_is_about_world_z_so_the_horizon_never_tilts():
    look = _block(AIM, "bool director_walk_aim(")
    assert "const float3 world_z(0.0f, 0.0f, 1.0f);" in look
    assert "rotate_about(right, world_z, yaw)" in look
    assert "rotate_about(forward, world_z, yaw)" in look
    # Pitch rides the camera's own right axis, after the yaw moved it.
    assert look.index("rotate_about(right, world_z, yaw)") < look.index(
        "rotate_about(forward, right, pitch)"
    )


def test_the_aim_refuses_the_poles_rather_than_clamping_into_them():
    """A clamp that lands exactly on the pole leaves the basis degenerate and
    the frame rolls when the drag continues."""
    look = _block(AIM, "bool director_walk_aim(")
    assert "WALK_PITCH_LIMIT" in look
    assert "if (std::abs(dot3(pitched, world_z)) < WALK_PITCH_LIMIT) {" in look
    assert "forward = pitched;" in look


def test_a_scaled_camera_is_aimed_not_reset():
    """The aim re-bases the camera, so each axis carries its old length back."""
    look = _block(AIM, "bool director_walk_aim(")
    for axis in ("sx", "sy", "sz"):
        assert f"length3({'xyz'[('sx','sy','sz').index(axis)]}_axis)" in look
    # Through the accessors, not a flat `float *`: `float4x4::ptr()` yields
    # `float[4][4]`. See docs/blender-5.2-porting.md.
    assert "matrix.x_axis() = right * sx;" in look
    assert "matrix.y_axis() = up * sy;" in look
    assert "matrix.z_axis() = back * sz;" in look


def test_the_vector_helpers_are_spelled_out():
    """`math::cross` and `math::dot` appear nowhere else in this overlay, and
    a name that does not resolve costs a build rather than a review."""
    assert "float3 cross3(" in AIM and "float dot3(" in AIM
    for source in (WALK, AIM):
        assert "math::cross(" not in source and "math::dot(" not in source
    # The ones it does use are already proven here.
    assert "math::normalize(" in AIM and "math::length_squared(" in AIM


# ---- the session around it -------------------------------------------------


def test_python_still_owns_the_session():
    assert 'WALK_OPERATOR = "MIXAR_OT_director_walk"' in VIEWPORT
    assert "return bpy.ops.mixar.director_walk('INVOKE_DEFAULT'), target" in VIEWPORT
    camera_ops = (DIRECTOR / "ui/operators/camera_ops.py").read_text(encoding="utf-8")
    assert "modal_operators.get(operator)" in camera_ops
    assert "_walk_operator = WALK_OPERATOR" in camera_ops


def test_explore_keeps_blenders_own_walk():
    """Explore flies the VIEWPORT; the Cinema walk drives the shot camera.
    Different subjects, and free-flying a viewport is what `view3d.walk` is
    for."""
    explore = VIEWPORT[VIEWPORT.index("def invoke_explore_walk("):]
    explore = explore[: explore.index("\ndef ")]
    assert "bpy.ops.view3d.walk('INVOKE_DEFAULT')" in explore


def test_the_walk_is_one_undo_step():
    registration = _block(WALK, "void MIXAR_OT_director_walk(")
    assert "OPTYPE_UNDO" in registration
    finish = _block(WALK, "wmOperatorStatus director_walk_finish(")
    assert "return moved ? OPERATOR_FINISHED : OPERATOR_CANCELLED;" in finish


def test_the_operator_is_registered_and_built():
    assert "void MIXAR_OT_director_walk(wmOperatorType *ot);" in (
        VIEW3D / "view3d_director.hh"
    ).read_text(encoding="utf-8")
    assert "WM_operatortype_append(MIXAR_OT_director_walk);" in NUDGE
    cmake = (VIEW3D / "CMakeLists.txt").read_text(encoding="utf-8")
    for name in ("view3d_director_walk.cc", "view3d_director_walk_aim.cc",
                 "view3d_director_camera_move.cc", "view3d_director_camera_move.hh"):
        assert name in cmake, name


def test_the_strip_promises_the_left_button():
    """A hint is a promise, and "Mouse — look around" was the old walk's."""
    block = TOP.split("const Hint walking_hints[", 1)[1].split("};", 1)[0]
    assert '{"LMB"}' in block and "Hold to look" in block
    assert '"Mouse"' not in block
