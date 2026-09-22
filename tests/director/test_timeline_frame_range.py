# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Outside the scene's frame range the dock reads as disabled.

Nothing out there plays and nothing out there renders, and the timeline used
to say nothing about it: the ruler, its ticks and the camera strip looked
identical either side of the End frame.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
RULER = (VIEW3D / "view3d_director_timeline_ruler.cc").read_text(encoding="utf-8")
DRAW = (VIEW3D / "view3d_director_timeline_draw.cc").read_text(encoding="utf-8")
TIMELINE_HH = (VIEW3D / "view3d_director_timeline.hh").read_text(encoding="utf-8")
DIRECTOR_HH = (VIEW3D / "view3d_director.hh").read_text(encoding="utf-8")
STATE = (VIEW3D / "view3d_director_state.cc").read_text(encoding="utf-8")


def _scrim() -> str:
    body = RULER[RULER.index("void director_timeline_draw_range_scrim(") :]
    return body[: body.index("\n}\n")]


def test_the_state_carries_the_scenes_own_end():
    """`frame_start` / `frame_end` collapse onto the BEATS' span as soon as a
    shot has any, so the scene's range has to be kept separately — it is what
    the dock's Start/End fields edit."""
    assert "int scene_frame_end = 0;" in DIRECTOR_HH
    assert "r_state->scene_frame_end = scene->r.efra;" in STATE
    # And it is read before the beats overwrite frame_start/frame_end.
    assert STATE.index("r_state->scene_frame_end") < STATE.index(
        "r_state->frame_start = bounds.first->frame;"
    )


def test_it_dims_both_sides_of_the_range():
    scrim = _scrim()
    assert "const float left = frame_x(state.scene_frame_start);" in scrim
    assert "const float right = frame_x(state.scene_frame_end);" in scrim
    assert "director_timeline_draw_rect(x0, bottom, left, top, OUT_OF_RANGE_COLOR);" in scrim
    assert "director_timeline_draw_rect(right, bottom, x1, top, OUT_OF_RANGE_COLOR);" in scrim


def test_each_end_is_clamped_to_the_viewport_box():
    """The dock pans and zooms, so a range that runs off the view must not
    paint a scrim off the view with it."""
    scrim = _scrim()
    assert "return std::clamp(x, x0, x1);" in scrim


def test_a_range_that_fills_the_view_paints_nothing():
    """The common case — the scene range wider than the shot the view is fit
    to — must not put a scrim over the whole dock."""
    scrim = _scrim()
    assert "if (left > x0) {" in scrim
    assert "if (right < x1) {" in scrim


def test_the_boundary_reads_as_an_edge():
    scrim = _scrim()
    assert "RANGE_EDGE_COLOR" in scrim
    assert "const float line = std::max(1.0f, UI_SCALE_FAC);" in scrim


def test_it_is_painted_over_the_whole_stack_not_under_it():
    """One scrim dims the ruler, its labels, the strip and the keyframes
    together. Dimming each layer on its own would mean every layer added
    later having to remember to."""
    content = DRAW[DRAW.index("void view3d_director_timeline_draw_content(") :]
    content = content[: content.index("\n}\n")]
    assert "director_timeline_draw_range_scrim(" in content
    assert content.index("director_timeline_draw_ruler(") < content.index(
        "director_timeline_draw_range_scrim("
    )
    assert content.index("draw_strip(") < content.index("director_timeline_draw_range_scrim(")
    assert content.index("director_timeline_draw_playhead(") < content.index(
        "director_timeline_draw_range_scrim("
    )


def test_the_box_select_band_stays_legible_over_it():
    """A selection is a live gesture; dimming it would be dimming the thing
    the user is doing right now."""
    content = DRAW[DRAW.index("void view3d_director_timeline_draw_content(") :]
    content = content[: content.index("\n}\n")]
    assert content.index("director_timeline_draw_range_scrim(") < content.index(
        "director_timeline_box_rect(*runtime, &box)"
    )


def test_the_declaration_says_where_it_paints():
    assert "void director_timeline_draw_range_scrim(" in TIMELINE_HH


def test_the_dimmed_stretch_can_be_brought_on_screen():
    """The view clamped its start to `scene_frame_start`, so the frames
    BEFORE Start — exactly the stretch the scrim dims — could never be panned
    or zoomed to. Set Start to 50 and 1..49 was unreachable."""
    interaction = (
        VIEW3D / "view3d_director_timeline_interaction.cc"
    ).read_text(encoding="utf-8")
    floor_body = interaction[interaction.index("float view_floor(") :]
    floor_body = floor_body[: floor_body.index("\n}\n")]
    # Frame 0, or an earlier keyframe, so a beat left outside the range stays
    # reachable instead of being hidden with it.
    assert "float floor_frame = 0.0f;" in floor_body
    assert "std::min(floor_frame, float(beat.frame))" in floor_body
    assert interaction.count("std::max(view_floor(state)") == 3
    assert "std::max(float(state.scene_frame_start)," not in interaction
