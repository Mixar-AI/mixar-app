# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The timeline divides its region the way the Dope Sheet does.

A press anywhere used to scrub, which left no gesture for selecting keyframes
— and meant reaching for a keyframe and missing it moved the playhead instead.
The playhead is dragged from the RULER ROW; the body is for selecting.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
INTERACTION = (VIEW3D / "view3d_director_timeline_interaction.cc").read_text(encoding="utf-8")
SELECT = (VIEW3D / "view3d_director_timeline_select.cc").read_text(encoding="utf-8")
DRAW = (VIEW3D / "view3d_director_timeline_draw.cc").read_text(encoding="utf-8")
RUNTIME = (VIEW3D / "view3d_director_timeline.hh").read_text(encoding="utf-8")


def _press_branch() -> str:
    body = INTERACTION[INTERACTION.index("if (event->type == LEFTMOUSE && event->val == KM_PRESS) {") :]
    return body[: body.index("return WM_UI_HANDLER_CONTINUE;")]


def test_the_scrub_band_is_published_by_the_painter():
    """The band is the ruler row — under the strip, down to the dock floor."""
    assert "rctf ruler_bounds = {};" in RUNTIME
    assert "runtime->ruler_bounds = {runtime->viewport_bounds.xmin," in DRAW
    assert "strip_y - 2.0f * u};" in DRAW


def test_scrubbing_is_scoped_to_that_band():
    branch = _press_branch()
    assert "point_inside(runtime->ruler_bounds, event) &&" in branch
    assert "begin_scrub(C, event, region, runtime)" in branch
    # The old catch-all.
    assert "point_inside(runtime->viewport_bounds, event) &&\n             begin_scrub" not in INTERACTION


def test_a_press_in_the_body_starts_a_box_select():
    branch = _press_branch()
    assert "director_timeline_box_begin(runtime, event);" in branch
    # Order: keys, the tick itself, the strip, the ruler row, the body.
    assert branch.index("if (key != nullptr)") < branch.index("director_timeline_playhead_grab")
    assert branch.index("director_timeline_playhead_grab") < branch.index("runtime->strip_bounds")
    assert branch.index("runtime->strip_bounds") < branch.index("runtime->ruler_bounds")
    assert branch.index("runtime->ruler_bounds") < branch.index("director_timeline_box_begin")


# -------------------------------------------------------------------------
# The tick is a handle.


RULER = (VIEW3D / "view3d_director_timeline_ruler.cc").read_text(encoding="utf-8")


def test_grabbing_the_tick_scrubs_from_anywhere_in_the_dock():
    """Restricting the scrub to the ruler row gave the body back to box
    select, but it also made the playhead itself un-grabbable — and a
    playhead is a handle in every editor that has one."""
    branch = _press_branch()
    assert "director_timeline_playhead_grab(" in branch
    assert "begin_scrub(C, event, region, runtime)" in branch
    # Keyframes still win where the line crosses them: they are the
    # precision target, the playhead is 10 px wide.
    assert branch.index("if (key != nullptr)") < branch.index("director_timeline_playhead_grab")
    # And a grab within a few pixels of the line is never a strip retime.
    assert branch.index("director_timeline_playhead_grab") < branch.index("begin_strip_drag")


def test_the_grab_rects_are_the_ones_the_playhead_drew():
    """Never a second copy of the same arithmetic — the surface's rule."""
    assert "rctf playhead_line = {1.0f, -1.0f, 1.0f, -1.0f};" in RUNTIME
    assert "rctf playhead_pill = {1.0f, -1.0f, 1.0f, -1.0f};" in RUNTIME
    draw = RULER[RULER.index("void director_timeline_draw_playhead(") :]
    draw = draw[: draw.index("\n}\n")]
    assert "runtime->playhead_line = {x - grab, x + grab, bottom, pill_y};" in draw
    assert "runtime->playhead_pill = pill;" in draw
    grab = RULER[RULER.index("bool director_timeline_playhead_grab(") :]
    grab = grab[: grab.index("\n}\n")]
    assert "runtime.playhead_line" in grab and "runtime.playhead_pill" in grab
    # The pill counts too: it is the visible handle, and it sits in a band
    # of its own above the strip.
    assert "BLI_rctf_isect_pt(&runtime.playhead_pill, x, y)" in grab


def test_an_offscreen_playhead_is_not_grabbable():
    """A zeroed rctf contains the origin, so the empty rect has to be an
    inverted one — otherwise a press at the dock's bottom-left corner would
    grab a playhead that is not on screen."""
    draw = RULER[RULER.index("void director_timeline_draw_playhead(") :]
    draw = draw[: draw.index("\n}\n")]
    reset = draw[: draw.index("const float width =")]
    assert "runtime->playhead_line = {1.0f, -1.0f, 1.0f, -1.0f};" in reset
    assert "runtime->playhead_pill = {1.0f, -1.0f, 1.0f, -1.0f};" in reset
    # And the reset happens BEFORE the early return for an off-screen head.
    assert draw.index("playhead_line = {1.0f") < draw.index("return;")


def test_the_line_is_padded_because_a_hairline_cannot_be_caught():
    assert "constexpr float PLAYHEAD_GRAB_PAD = 5.0f;" in RULER
    assert "const float grab = PLAYHEAD_GRAB_PAD * UI_SCALE_FAC;" in RULER


def test_the_box_start_is_shared_with_the_b_key_path():
    """One place decides what starting a box means, so the two entry points
    cannot disagree about extend or the anchor."""
    assert "void director_timeline_box_begin(DirectorTimelineRuntime *runtime" in SELECT
    arm = SELECT[SELECT.index("if (runtime->box_arming && event->type == LEFTMOUSE") :]
    arm = arm[: arm.index("return true;")]
    assert "director_timeline_box_begin(runtime, event);" in arm


def test_a_click_that_never_dragged_clears_the_selection():
    """As it does in every Blender editor; Shift+click keeps what is there."""
    body = SELECT[SELECT.index("if (released_here || released_elsewhere) {") :]
    body = body[: body.index("ED_region_tag_redraw(region);")]
    assert "const bool dragged =" in body
    assert "else if (!runtime->box_extend) {" in body
    assert 'select_keys(C, {}, "NONE");' in body


def test_a_box_let_go_outside_the_region_still_closes():
    """A region handler is only offered events while the pointer is over its
    own region, so a drag released over the viewport never delivered its
    button-up here — and the rubber band stayed glued to the cursor until
    the next unrelated click."""
    body = SELECT[SELECT.index("if (runtime->box_dragging) {") :]
    assert "event->prev_type == LEFTMOUSE" in body
    assert "event->prev_val == KM_RELEASE" in body
    # A release heard about second hand closes the box but does not swallow
    # the event that carried the news.
    assert "return released_here;" in body
    # And it must not be mistaken for the drag continuing.
    assert "if (event->type == MOUSEMOVE && !released_elsewhere) {" in body
