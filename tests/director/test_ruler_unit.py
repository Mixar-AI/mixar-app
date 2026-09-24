# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dock's Duration chips are Frames and Duration, not Min and Sec.

Minutes-versus-seconds is a formatting detail — the ruler decides it from how
much time is on screen — and neither option could label a frame number at all,
which is the unit a director quotes to an animator.
"""

from __future__ import annotations

import re
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"

PROPERTIES = (DIRECTOR / "ui/properties/director_properties.py").read_text(encoding="utf-8")
DOCK = (VIEW3D / "view3d_director_cinema_dock.cc").read_text(encoding="utf-8")
#: The Ruler group moved out when the dock reached the module size limit.
RULER_GROUP = (VIEW3D / "view3d_director_cinema_dock_ruler.cc").read_text(encoding="utf-8")
STATE = (VIEW3D / "view3d_director_state.cc").read_text(encoding="utf-8")
# The ruler and playhead have their own translation unit (500-line rule).
DRAW = (VIEW3D / "view3d_director_timeline_ruler.cc").read_text(encoding="utf-8")
HEADER = (VIEW3D / "view3d_director.hh").read_text(encoding="utf-8")


def _items() -> list[tuple[str, str, int]]:
    body = PROPERTIES[PROPERTIES.index("ruler_unit: EnumProperty(") :]
    body = body[: body.index("\n    timeline_expanded")]
    return [
        (match.group(1), match.group(2), int(match.group(3)))
        for match in re.finditer(
            r'\(\s*"([A-Z]+)",\s*"([A-Za-z]+)",\s*"[^"]*",\s*(\d)',
            body,
            re.S,
        )
    ]


def test_the_two_units_are_frames_and_duration():
    assert _items() == [("FRAMES", "Frames", 0), ("DURATION", "Duration", 1)]
    assert '"MIN"' not in PROPERTIES
    assert '"SEC"' not in PROPERTIES


def test_the_native_index_matches_the_enum_order():
    """The C++ reads the enum by INDEX; a reorder here silently inverts it."""
    frames_index = next(index for key, _label, index in _items() if key == "FRAMES")
    assert frames_index == 0
    assert 'director_enum(&state_ptr, "ruler_unit", 1) == 0' in STATE
    assert "r_state->ruler_frames" in STATE
    assert "bool ruler_frames = false;" in HEADER
    assert "ruler_minutes" not in HEADER


def test_the_chips_paint_and_set_the_same_identifiers():
    for label, value in (("Frames", "FRAMES"), ("Duration", "DURATION")):
        assert f'{{"{label}", "{value}"}}' in RULER_GROUP.replace("\n     ", "")
    assert '"Min", "MIN"' not in DOCK
    assert '"Sec", "SEC"' not in DOCK


def test_the_chip_is_wide_enough_for_the_longer_label():
    match = re.search(r"^constexpr float CHIP_W = ([0-9.]+)f;", RULER_GROUP, re.M)
    assert match is not None
    assert float(match.group(1)) >= 64.0


def test_frames_labels_the_scenes_own_frame_number():
    """The same number Blender's timeline shows — never an offset."""
    body = DRAW[DRAW.index("void ruler_label(") :]
    body = body[: body.index("\n}\n")]
    assert "if (state.ruler_frames) {" in body
    assert 'BLI_snprintf(out, size, "%d", int(std::round(frame)));' in body


def test_the_tick_structure_is_derived_from_the_fps():
    """Both units land on whole SECONDS, which in frames means multiples of
    the fps — 1, 25, 49 at 24fps and 1, 31, 61 at 30. A frame ruler that
    stepped 10, 20, 30 was counting in tens of nothing.

    Below a second the two part company: frames steps in whole frames, which
    is the smallest thing it can mean, where time still has tenths."""
    assert "constexpr std::array<float, 4> SUB_SECOND_FRAME_STEPS" in DRAW
    assert "constexpr std::array<float, 8> SECOND_MULTIPLES" in DRAW
    assert "constexpr std::array<float, 15> SECOND_STEPS" in DRAW
    body = DRAW[DRAW.index("float major_tick_frames(") :]
    body = body[: body.index("\n}\n")]
    assert "if (state.ruler_frames) {" in body
    assert "for (const float multiple : SECOND_MULTIPLES)" in body
    assert "for (const float step : SUB_SECOND_FRAME_STEPS)" in body
    assert "for (const float seconds : SECOND_STEPS)" in body
    # Whole frames, or two neighbours round onto the same number.
    assert "std::round(fps)" in body
    assert "std::round(seconds * fps)" in body


def test_frames_ticks_land_on_whole_frames():
    """Two neighbouring ticks rounding to the same number reads as a stutter."""
    assert "int step = std::clamp(int(std::lround(minor)), 1, major_frames);" in DRAW


def test_a_whole_frame_step_still_divides_the_major_tick():
    """The regression: a ruler whose labels were five times too sparse.

    The major test asks whether a tick lands on a multiple of `major`, so a
    whole-frame step that does not DIVIDE `major` only meets one at their
    common multiple. At 24fps with five divisions the step rounds to 5 and
    the next labelled tick after frame 0 is frame 120 — not the 24, 48, 72
    ladder the comment above the loop promises.
    """
    assert "while (step < major_frames && major_frames % step != 0) {" in DRAW

    def frame_step(major: int, divisions: int) -> int:
        """The C++ rule above, in Python."""
        step = min(max(round(major / divisions), 1), major)
        while step < major and major % step != 0:
            step += 1
        return step

    # Every ladder `major_tick_frames` can return in FRAMES mode, at both
    # division counts.
    seconds = (24, 25, 30, 48, 50, 60)
    multiples = (1, 2, 5, 10, 15, 30, 60, 120)
    ladders = {fps * multiple for fps in seconds for multiple in multiples}
    ladders |= {1, 2, 5, 10, 12}  # the sub-second frame steps
    for major in sorted(ladders):
        for divisions in (5, 10):
            step = frame_step(major, divisions)
            assert step >= 1
            assert major % step == 0, (major, divisions, step)
            # Climbing to the next divisor, never dropping below the rounded
            # value: the sub-frame rule above must survive the repair.
            assert step >= min(max(round(major / divisions), 1), major)


def test_no_tick_is_drawn_before_the_scene_starts():
    """A scene beginning on frame 1 must not grow a "0" tick to the left of
    its own first frame."""
    assert "if (frame < float(state.scene_frame_start) - 0.5f) {" in DRAW


def test_the_playhead_pill_reads_in_the_rulers_unit():
    """A pill reading "0.00" beside a timeline reading 1 is the same playhead
    disagreeing with itself."""
    body = DRAW[DRAW.index("void director_timeline_draw_playhead(") :]
    body = body[: body.index("\n}\n")]
    assert 'BLI_snprintf(label, sizeof(label), "%d", state.frame_current);' in body


def test_duration_picks_its_own_format_from_the_span():
    """`m:ss` once a minute is on screen; below that "0:03" is not what
    anyone means by three seconds."""
    body = DRAW[DRAW.index("void ruler_label(") :]
    body = body[: body.index("\n}\n")]
    assert "span_seconds >= 60.0f && major_seconds >= 1.0f" in body
    assert '"%.1fs"' in body
    assert '"%02.0fs"' in body


def test_the_group_is_titled_ruler_not_after_one_of_its_options():
    """"Duration" is one of the two chips now; a group labelled with the name
    of one of its own options reads as a statement, not a choice."""
    assert 'cinema_text_left("Ruler", x, cy, CINEMA_FONT_TITLE * u, title);' in RULER_GROUP
    assert 'cinema_text_left("Duration",' not in DOCK


# -------------------------------------------------------------------------
# The ladder is derived from the fps, and both units land on the same places.


def _ruler() -> str:
    return (VIEW3D / "view3d_director_timeline_ruler.cc").read_text(encoding="utf-8")


def _ladder(name: str) -> list[float]:
    body = _ruler().split(f"{name} = {{", 1)[1].split("};", 1)[0]
    return [float(value.rstrip("f")) for value in re.findall(r"([0-9.]+f)", body)]


def _step_fn():
    """`major_tick_frames` re-expressed in Python, from the C++ it mirrors."""
    seconds = _ladder("SECOND_STEPS")
    sub = _ladder("SUB_SECOND_FRAME_STEPS")
    multiples = _ladder("SECOND_MULTIPLES")

    def step(fps, pixels_per_frame, frames_mode, span_frames=100000.0, target=86.0):
        if frames_mode:
            second = max(1.0, round(fps))
            for multiple in multiples:
                value = second * multiple
                if value * pixels_per_frame < target:
                    continue
                if value <= span_frames:
                    return value
                break
            if second * pixels_per_frame < target:
                return second * multiples[-1]
            for value in sub:
                if value * pixels_per_frame >= target:
                    return value
            return 1.0
        for value in seconds:
            frames = max(1.0, round(value * fps))
            if frames * pixels_per_frame >= target:
                return frames
        return max(1.0, round(seconds[-1] * fps))

    return step


def test_a_frame_ruler_steps_in_whole_seconds():
    """10, 20, 30 was counting in tens of nothing. A director reads seconds."""
    step = _step_fn()
    assert step(24.0, 6.0, frames_mode=True) == 24.0
    assert step(30.0, 6.0, frames_mode=True) == 30.0
    assert step(25.0, 6.0, frames_mode=True) == 25.0


def test_the_ladder_follows_the_fps():
    step = _step_fn()
    for fps in (24.0, 25.0, 30.0, 48.0, 60.0):
        assert step(fps, 200.0 / fps, frames_mode=True) % 1 == 0
        # One second of screen time, whatever the rate.
        assert step(fps, 86.0 / fps + 0.01, frames_mode=True) == round(fps)


def test_the_frame_marks_are_exact_multiples_of_the_rate():
    """Which is the whole point: "jumps of 24 if 24fps is chosen"."""
    step = _step_fn()
    for fps in (24.0, 25.0, 30.0, 48.0, 60.0):
        for pixels in (4.0, 12.0, 25.0):
            value = step(fps, pixels, frames_mode=True, span_frames=2000.0)
            assert value % round(fps) == 0


def test_a_smaller_mark_is_never_offered_just_because_it_fits():
    """The reported bug: at an ordinary zoom a ten-frame step cleared the
    label spacing, so the ruler stopped there and never reached the rate."""
    step = _step_fn()
    for pixels in (6.0, 12.0, 25.0, 40.0):
        # A whole second is on screen, so a whole second is the mark.
        assert step(24.0, pixels, frames_mode=True, span_frames=200.0) == 24.0


def test_only_zooming_inside_a_second_falls_back_to_frames():
    """Marking seconds there would leave no labelled tick on screen at all."""
    step = _step_fn()
    # Twenty frames across the dock: a second does not fit, so the marks are
    # the widest frame step that still clears the labels.
    assert step(24.0, 30.0, frames_mode=True, span_frames=20.0) == 5.0
    # Right in: every frame.
    assert step(24.0, 100.0, frames_mode=True, span_frames=12.0) == 1.0
    # ... where a duration ruler still has tenths of a second to offer.
    assert step(24.0, 100.0, frames_mode=False) == round(0.1 * 24)


def test_zoomed_out_the_marks_are_whole_seconds_apart():
    step = _step_fn()
    for pixels in (0.5, 1.0, 2.0):
        assert step(24.0, pixels, frames_mode=True) % 24 == 0


def test_a_fractional_fps_never_puts_two_ticks_on_one_frame():
    """23.976 frames would round two neighbours onto the same number."""
    step = _step_fn()
    value = step(23.976, 6.0, frames_mode=True)
    assert value == round(value)
    assert value >= 1.0


# -------------------------------------------------------------------------
# Anchoring.


def test_each_unit_is_anchored_where_its_own_numbers_start():
    """DURATION measures elapsed time from the scene's start, so it anchors
    there — anchored on frame zero, the tick one second into a scene starting
    at frame 1 sat at frame 24, 0.96s, while its label said 01s and the
    playhead pill parked on it read 0.96.

    FRAMES labels the absolute frame number, so it anchors on zero and its
    marks ARE the multiples of the rate: 24, 48, 72."""
    source = _ruler()
    assert (
        "const float origin = state.ruler_frames ? 0.0f : float(state.scene_frame_start);"
        in source
    )
    assert (
        "const float first_tick = origin + std::ceil((view_start - origin) / minor) * minor;"
        in source
    )
    # The major/minor test measures from the same origin, or a tick lands
    # major-aligned by accident and labels itself wrong.
    assert "std::round((frame - origin) / major)" in source


def test_a_tick_label_is_exactly_its_own_step():
    """The arithmetic the anchoring guarantees: N steps from the origin is
    N * step seconds, never N * step minus a frame."""
    fps, start, step_frames = 25.0, 1, 25.0
    for index in range(1, 6):
        frame = start + index * step_frames
        seconds = (frame - start) / fps
        assert seconds == pytest.approx(float(index))
