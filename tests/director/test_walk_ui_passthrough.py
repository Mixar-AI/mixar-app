# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A running walk owns the STAGE, and nothing else.

A modal operator's handler sits on the window and runs before any region
does, so a walk that answers RUNNING_MODAL to every event owns the whole
screen: no card highlights, no tooltip appears, and no button can be pressed
while walking — which is exactly what happened ("I am not able to click on
any button on any ui when walk navigation is on").

The look handle is a handle over the STAGE — the free part of the Cinema
viewport — and nowhere else. So are the movement KEYS: a modal handler sits
on the window, so until they were scoped, W over the outliner, the chat, a
moodboard or another workspace's 3D viewport drove the shot camera.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
WALK = (VIEW3D / "view3d_director_walk.cc").read_text(encoding="utf-8")
MOVE = (VIEW3D / "view3d_director_camera_move.cc").read_text(encoding="utf-8")
MOVE_HH = (VIEW3D / "view3d_director_camera_move.hh").read_text(encoding="utf-8")


def _block(source: str, start: str) -> str:
    body = source[source.index(start) :]
    return body[: body.index("\n}\n") + 3]


def _stage() -> str:
    return _block(MOVE, "bool director_pointer_on_stage(")


def test_a_press_outside_the_stage_belongs_to_whatever_is_under_it():
    modal = _block(WALK, "wmOperatorStatus director_walk_modal(")
    press = modal[modal.index("if (event->type == LEFTMOUSE) {") :]
    assert "if (!director_pointer_on_stage(C, event)) {" in press
    assert (
        press.index("director_pointer_on_stage") < press.index("data->looking = true;")
    ), "the stage test has to come BEFORE the walk claims the press"
    assert "return OPERATOR_PASS_THROUGH;" in press


def test_a_release_the_walk_never_claimed_passes_through_too():
    """Otherwise the button that took the press never sees the click finish."""
    modal = _block(WALK, "wmOperatorStatus director_walk_modal(")
    assert "const bool was_looking = data->looking;" in modal
    assert "return was_looking ? OPERATOR_RUNNING_MODAL : OPERATOR_PASS_THROUGH;" in modal


def test_motion_reaches_the_regions_while_the_button_is_up():
    """Swallowing MOUSEMOVE is what killed every highlight and tooltip — and
    with them the hover state a click needs."""
    modal = _block(WALK, "wmOperatorStatus director_walk_modal(")
    move = modal[modal.index("event->type == MOUSEMOVE") :]
    idle = move[move.index("if (!data->looking) {") :]
    assert "return OPERATOR_PASS_THROUGH;" in idle[: idle.index("}")]


def test_the_walk_does_not_grab_the_cursor():
    """OPTYPE_BLOCKING takes a GHOST grab for the operator's whole run; this
    walk deliberately shares the window with the cards."""
    registration = WALK[WALK.index("void MIXAR_OT_director_walk(") :]
    assert "ot->flag = OPTYPE_UNDO;" in registration
    # The comment above it says why, so the flag itself is what must be gone.
    assert "| OPTYPE_BLOCKING" not in registration


def test_the_stage_test_is_geometric_not_a_hover_state():
    """`region_active_but_get` falls back to the LAST active button, and a
    hover state only exists after a motion event has reached the region —
    neither can answer the very first press."""
    stage = _stage()
    assert "ui::region_but_find_rect_over(region, &point)" in stage
    assert "region_active_but_get" not in MOVE


def test_it_asks_the_region_box_rather_than_the_modal_context():
    """`event->xy` is window space and `winrct` is the region's box in the
    same space; which region a modal handler's context resolves to depends on
    where the pointer went."""
    stage = _stage()
    assert "BLI_rcti_isect_pt(&region->winrct, event->xy[0], event->xy[1])" in stage
    assert "region->regiontype != RGN_TYPE_WINDOW" in stage
    assert "area->spacetype != SPACE_VIEW3D" in stage


def test_painted_cinema_chrome_counts_as_ui():
    """The cards publish the very rects they lay their buttons over."""
    stage = _stage()
    assert "for (const CinemaQARecord &record : cinema_qa_records()) {" in stage
    assert "BLI_rctf_isect_pt(&record.rect, fx, fy)" in stage


def test_both_native_movers_can_ask_the_same_question():
    """It lives with the shared move math, not inside the walk, so the nudge
    can never answer it differently."""
    assert "bool director_pointer_on_stage(" in MOVE_HH
    assert "bool director_pointer_on_stage(" not in WALK


# ---- the walk acts in Cinema Mode, and nowhere else ------------------------


def _modal() -> str:
    return _block(WALK, "wmOperatorStatus director_walk_modal(")


def test_a_movement_key_pressed_off_the_stage_is_not_the_cameras():
    """The walk is a WINDOW-level modal, so without this the camera keys
    drove the shot from wherever the pointer happened to be — and W, A and E
    all mean something of their own in the editors they landed in."""
    modal = _modal()
    keys = modal[modal.index("director_move_from_key(event->type)") :]
    press = keys[keys.index("if (event->val == KM_PRESS) {") :]
    press = press[: press.index("data->held |= bit;")]
    assert "if (!director_pointer_on_stage(C, event)) {" in press
    assert "return OPERATOR_PASS_THROUGH;" in press


def test_a_key_the_walk_never_claimed_passes_its_release_on():
    """Whoever took the press has to see the release — and a key held from
    the stage keeps walking when the pointer leaves it, because the KEY is
    what moves the camera."""
    modal = _modal()
    assert "const bool was_held = (data->held & bit) != 0;" in modal
    assert "return was_held ? OPERATOR_RUNNING_MODAL : OPERATOR_PASS_THROUGH;" in modal


def test_the_walk_ends_with_the_session_it_belongs_to():
    """Leaving Cinema Mode used to leave the modal running on the window,
    invisible, with its timer and its held keys still the camera's."""
    tick = _block(WALK, "wmOperatorStatus director_walk_tick(")
    assert "view3d_director_is_directing(CTX_data_scene(C))" in tick
    assert "return director_walk_finish(C, op);" in tick


def test_the_walk_ends_with_the_viewport_it_started_in():
    """`CTX_wm_area` is the invoke-time area, re-validated against the live
    screen on every event, so a null one means that viewport is gone — a
    workspace switch, or the area closed."""
    tick = _block(WALK, "wmOperatorStatus director_walk_tick(")
    assert "CTX_wm_area(C) == nullptr" in tick
