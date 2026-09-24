# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Timeline navigation matches Blender's own animation editors.

Panning only worked through a trackpad's `MOUSEPAN` gesture, so a mouse user
had Shift+wheel and nothing else: no middle-mouse drag, no Home.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
INTERACTION = (VIEW3D / "view3d_director_timeline_interaction.cc").read_text(encoding="utf-8")
RUNTIME = (VIEW3D / "view3d_director_timeline.hh").read_text(encoding="utf-8")


def _pan() -> str:
    body = INTERACTION[INTERACTION.index("bool handle_pan_drag(") :]
    return body[: body.index("\n}\n")]


def test_middle_mouse_drags_the_view():
    pan = _pan()
    assert "event->type == MIDDLEMOUSE" in pan
    assert "event->val == KM_PRESS" in pan
    assert "event->val == KM_RELEASE" in pan
    for field in ("panning", "pan_anchor_x", "pan_anchor_frame"):
        assert field in RUNTIME, field


def test_the_pan_is_anchored_on_a_frame_not_integrated_from_deltas():
    """A delta-integrated pan that hits the start clamp and comes back lands
    somewhere other than where it started."""
    pan = _pan()
    assert "runtime->pan_anchor_frame = frame_at_x(*runtime, event->mval[0]);" in pan
    assert "runtime->pan_anchor_frame - t * runtime->view_span_frames" in pan


def test_the_pan_owns_every_event_until_it_ends():
    """Otherwise a hover update or a click lands mid-drag."""
    handler = INTERACTION[INTERACTION.index("int timeline_ui_handler(") :]
    assert handler.index("handle_pan_drag(region, state, runtime, event)") < handler.index(
        "if (event->type == MOUSEMOVE) {"
    )


def test_an_unexpected_event_ends_the_drag():
    """A window deactivate or a key must not leave the region stuck in a pan
    the user cannot see."""
    pan = _pan()
    tail = pan[pan.index("if (!runtime->panning) {") :]
    assert (
        "if (event->type != MOUSEMOVE && event->type != INBETWEEN_MOUSEMOVE) {"
    ) in tail
    assert "runtime->panning = false;" in tail


def test_motion_and_timers_do_not_count_as_unexpected():
    """Both ended the pan, and both are the pan still happening.

    A fast drag arrives as INBETWEEN_MOUSEMOVE, which is the same motion
    under another name, and playback's redraw timer ticks straight through a
    drag — which made the middle mouse unusable while the timeline ran.
    """
    pan = _pan()
    tail = pan[pan.index("if (!runtime->panning) {") :]
    assert "if (ISTIMER(event->type)) {" in tail
    # The timer returns without touching the drag; only the catch-all below
    # ends it.
    timer = tail[tail.index("if (ISTIMER(event->type)) {") :]
    timer = timer[: timer.index("\n  }")]
    assert "runtime->panning" not in timer
    assert tail.index("ISTIMER(event->type)") < tail.index("runtime->panning = false;")


def test_the_wheel_assignment_matches_the_animation_editors():
    """Plain wheel zooms; Shift or Ctrl + wheel pans."""
    assert "event->modifier & (KM_SHIFT | KM_CTRL)" in INTERACTION


def test_home_frames_the_whole_shot():
    assert "event->type == EVT_HOMEKEY && event->val == KM_PRESS" in INTERACTION
    body = INTERACTION[INTERACTION.index("event->type == EVT_HOMEKEY") :]
    body = body[: body.index("return WM_UI_HANDLER_BREAK;")]
    # `sync_view` is the ONE place that knows what "all" means for the active
    # shot; Home hands the fit back to it rather than computing a second one.
    assert "runtime->view_initialized = false;" in body
    assert "runtime->view_user_modified = false;" in body


def test_the_trackpad_gestures_are_untouched():
    assert "ELEM(event->type, MOUSEZOOM, MOUSEPAN)" in INTERACTION
    assert "MOUSESMARTZOOM" in INTERACTION
