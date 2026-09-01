# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure geometry + gesture reading for Scribble Marks.

These are the only parts of the mark pipeline that can be exercised outside
Blender, and they are the parts that decide what the user *meant* — so they
carry the tests. Everything here runs against real floats: nothing in
``geometry`` or ``gesture`` touches ``bpy``, which is a MagicMock in this
suite and would hand back mocks instead of numbers.
"""

import math

import pytest

from mixar.modules.scribble_mark.constants import (
    GESTURE_ARROW,
    GESTURE_CIRCLE,
    GESTURE_POINT,
    GESTURE_STRIKE,
    GESTURE_STROKE,
)
from mixar.modules.scribble_mark.core import geometry as geo
from mixar.modules.scribble_mark.core import gesture


# =============================================================================
# Helpers
# =============================================================================

def circle_points(cx, cy, r, n=48, gap_deg=0.0):
    """A hand-drawn-ish loop, optionally left open by *gap_deg*."""
    span = 360.0 - gap_deg
    return [
        (
            cx + r * math.cos(math.radians(span * i / (n - 1))),
            cy + r * math.sin(math.radians(span * i / (n - 1))),
        )
        for i in range(n)
    ]


def line_points(x0, y0, x1, y1, n=24):
    return [
        (x0 + (x1 - x0) * i / (n - 1), y0 + (y1 - y0) * i / (n - 1))
        for i in range(n)
    ]


# =============================================================================
# Geometry primitives
# =============================================================================

class TestMeasures:
    def test_bbox_and_diagonal(self):
        pts = [(0.0, 0.0), (30.0, 40.0), (10.0, 5.0)]
        assert geo.bbox(pts) == (0.0, 0.0, 30.0, 40.0)
        assert geo.bbox_diagonal(pts) == pytest.approx(50.0)

    def test_empty_inputs_never_raise(self):
        assert geo.bbox([]) is None
        assert geo.bbox_center_size([]) is None
        assert geo.centroid([]) is None
        assert geo.bbox_diagonal([]) == 0.0
        assert geo.path_length([]) == 0.0
        assert geo.polygon_area([]) == 0.0

    def test_path_length_sums_segments(self):
        assert geo.path_length([(0, 0), (3, 4), (3, 8)]) == pytest.approx(9.0)

    def test_polygon_area_of_unit_square(self):
        assert geo.polygon_area([(0, 0), (2, 0), (2, 2), (0, 2)]) == pytest.approx(4.0)

    def test_polygon_area_is_winding_independent(self):
        cw = [(0, 0), (0, 2), (2, 2), (2, 0)]
        ccw = [(0, 0), (2, 0), (2, 2), (0, 2)]
        assert geo.polygon_area(cw) == pytest.approx(geo.polygon_area(ccw))

    def test_straightness_line_versus_coil(self):
        assert geo.straightness(line_points(0, 0, 100, 0)) == pytest.approx(1.0, abs=1e-6)
        # A full loop doubles back on itself: bbox diagonal over path length
        # lands near 0.45, far below the 0.90 a strike-through needs.
        assert geo.straightness(circle_points(0, 0, 50)) < 0.5

    def test_straightness_of_a_tap_is_zero_not_one(self):
        """A stationary path must never read as a perfectly straight line —
        that is what keeps a tap from being classified as a strike."""
        assert geo.straightness([(5.0, 5.0)] * 6) == 0.0


class TestHull:
    def test_hull_drops_interior_points(self):
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        hull = geo.convex_hull(square + [(5, 5), (4, 6)])
        assert set(hull) == set((float(x), float(y)) for x, y in square)

    def test_degenerate_inputs_return_points_not_exceptions(self):
        assert geo.convex_hull([]) == []
        assert geo.convex_hull([(1, 1)]) == [(1.0, 1.0)]
        collinear = geo.convex_hull([(0, 0), (1, 1), (2, 2)])
        assert len(collinear) == 3


class TestClosedDetection:
    def test_full_loop_is_closed(self):
        assert geo.is_closed(circle_points(0, 0, 40)) is True

    def test_loop_with_a_realistic_gap_is_still_closed(self):
        """Circling something on screen routinely leaves a fifth of the
        diameter open. Reading that as an open squiggle loses the user's
        actual meaning, so the threshold is deliberately generous."""
        assert geo.is_closed(circle_points(0, 0, 40, gap_deg=45)) is True

    def test_open_arc_is_not_closed(self):
        assert geo.is_closed(circle_points(0, 0, 40, gap_deg=200)) is False

    def test_straight_line_is_not_closed(self):
        assert geo.is_closed(line_points(0, 0, 100, 0)) is False

    def test_too_few_points_is_not_closed(self):
        assert geo.is_closed([(0, 0), (1, 1)]) is False


class TestTangentAndTurn:
    def test_tangent_points_along_travel(self):
        tangent = geo.tangent_at_end(line_points(0, 0, 100, 0), 0.25)
        assert tangent == pytest.approx((1.0, 0.0), abs=1e-6)

    def test_tangent_of_a_stationary_path_is_none(self):
        assert geo.tangent_at_end([(3, 3)] * 5, 0.25) is None

    def test_turn_detected_only_in_the_tail(self):
        # Sharp turn early on: the tail is straight, so nothing is reported.
        early = line_points(0, 0, 20, 0, 6) + line_points(20, 0, 20, 60, 30)
        angle, _ = geo.max_turn_in_tail(early, 0.3)
        assert angle < 45.0

    def test_turn_detected_when_it_is_in_the_tail(self):
        late = line_points(0, 0, 100, 0, 30) + line_points(100, 0, 90, 10, 6)
        angle, index = geo.max_turn_in_tail(late, 0.3)
        assert angle > 100.0
        assert index > 0


class TestContainment:
    def test_point_in_polygon(self):
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        assert geo.point_in_polygon(5, 5, square) is True
        assert geo.point_in_polygon(15, 5, square) is False
        assert geo.point_in_polygon(-1, -1, square) is False

    def test_concave_polygon_excludes_the_notch(self):
        # A 'C' shape: the middle-right cell is outside the polygon.
        c_shape = [(0, 0), (10, 0), (10, 3), (4, 3), (4, 7), (10, 7), (10, 10), (0, 10)]
        assert geo.point_in_polygon(2, 5, c_shape) is True
        assert geo.point_in_polygon(8, 5, c_shape) is False

    def test_degenerate_polygon_contains_nothing(self):
        assert geo.point_in_polygon(0, 0, [(0, 0), (1, 1)]) is False


class TestDecimation:
    def test_keeps_both_endpoints(self):
        pts = line_points(0, 0, 100, 0, 200)
        out = geo.decimate(pts, 10)
        assert len(out) <= 10
        assert out[0] == pts[0]
        assert out[-1] == pts[-1]

    def test_short_input_passes_through(self):
        pts = [(0, 0), (1, 1), (2, 2)]
        assert geo.decimate(pts, 32) == pts

    def test_never_returns_fewer_than_two(self):
        pts = line_points(0, 0, 10, 0, 50)
        assert len(geo.decimate(pts, 0)) >= 2


class TestNormalization:
    def test_maps_region_pixels_into_unit_range(self):
        out = geo.to_normalized([(0, 0), (960, 540), (1920, 1080)], 1920, 1080)
        assert out[0] == [0.0, 0.0]
        assert out[1] == [0.5, 0.5]
        assert out[2] == [1.0, 1.0]

    def test_v_is_not_flipped(self):
        """Region coordinates are already bottom-up and the payload declares
        v bottom->top, matching the backend sculpt localizer. A flip here
        would put every edit in the wrong half of the frame."""
        out = geo.to_normalized([(0, 1080)], 1920, 1080)
        assert out[0][1] == 1.0

    def test_out_of_region_points_clamp(self):
        out = geo.to_normalized([(-50, 5000)], 1920, 1080)
        assert out[0] == [0.0, 1.0]

    def test_zero_sized_region_raises(self):
        with pytest.raises(ValueError):
            geo.to_normalized([(1, 1)], 0, 1080)

    def test_normalized_bbox_of_nothing_is_the_whole_frame(self):
        assert geo.normalized_bbox([], 1920, 1080) == [0.0, 0.0, 1.0, 1.0]

    def test_normalized_bbox_orders_min_then_max(self):
        box = geo.normalized_bbox([(480, 270), (1440, 810)], 1920, 1080)
        assert box == [0.25, 0.25, 0.75, 0.75]


# =============================================================================
# Gesture reading
# =============================================================================

class TestGestureReading:
    def test_nothing_to_read_returns_none(self):
        assert gesture.classify([]) is None
        assert gesture.classify([[], []]) is None

    def test_tap_is_a_point(self):
        result = gesture.classify([[(100.0, 100.0), (101.0, 100.5)]])
        assert result["gesture"] == GESTURE_POINT
        assert result["anchor"] == pytest.approx((100.5, 100.25))

    def test_tap_threshold_respects_ui_scale(self):
        """The tap thresholds are the only absolute pixel numbers in the
        classifier; on a HiDPI display an unscaled read would call every
        deliberate short drag a tap."""
        drag = line_points(0, 0, 20, 0, 8)
        assert gesture.classify([drag], scale=1.0)["gesture"] != GESTURE_POINT
        assert gesture.classify([drag], scale=3.0)["gesture"] == GESTURE_POINT

    def test_loop_is_a_circle_and_keeps_its_own_outline(self):
        loop = circle_points(500, 400, 120)
        result = gesture.classify([loop])
        assert result["gesture"] == GESTURE_CIRCLE
        assert result["closed"] is True
        assert result["anchor"] == pytest.approx((500.0, 400.0), abs=8.0)
        # The drawn loop, not its hull — a concave selection is information.
        assert len(result["polygon"]) == len(loop)

    def test_concave_loop_is_not_widened_to_its_hull(self):
        c_loop = [
            (0, 0), (100, 0), (100, 30), (40, 30), (40, 70),
            (100, 70), (100, 100), (0, 100), (0, 0),
        ]
        result = gesture.classify([c_loop])
        assert result["gesture"] == GESTURE_CIRCLE
        assert geo.polygon_area(result["polygon"]) < geo.polygon_area(geo.convex_hull(c_loop))

    def test_largest_loop_wins_when_several_are_drawn(self):
        small = circle_points(100, 100, 20)
        big = circle_points(600, 600, 200)
        result = gesture.classify([small, big])
        assert result["gesture"] == GESTURE_CIRCLE
        assert result["anchor"] == pytest.approx((600.0, 600.0), abs=15.0)

    def test_two_stroke_arrow_anchors_on_the_head(self):
        shaft = line_points(0, 0, 300, 0, 40)
        head = [(270, 20), (300, 0), (270, -20)]
        result = gesture.classify([shaft, head])
        assert result["gesture"] == GESTURE_ARROW
        assert result["anchor"] == pytest.approx((300.0, 0.0), abs=1.0)
        assert result["direction"] == pytest.approx((1.0, 0.0), abs=0.05)

    def test_two_stroke_arrow_pointing_the_other_way(self):
        shaft = line_points(300, 0, 0, 0, 40)
        head = [(30, 20), (0, 0), (30, -20)]
        result = gesture.classify([shaft, head])
        assert result["gesture"] == GESTURE_ARROW
        assert result["anchor"] == pytest.approx((0.0, 0.0), abs=1.0)
        assert result["direction"] == pytest.approx((-1.0, 0.0), abs=0.05)

    def test_head_far_from_the_shaft_is_not_an_arrow(self):
        shaft = line_points(0, 0, 300, 0, 40)
        stray = [(600, 400), (620, 420)]
        assert gesture.classify([shaft, stray])["gesture"] != GESTURE_ARROW

    def test_single_stroke_arrow_reads_its_doubling_back(self):
        stroke = line_points(0, 0, 200, 0, 40) + line_points(200, 0, 175, 18, 8)
        result = gesture.classify([stroke])
        assert result["gesture"] == GESTURE_ARROW
        assert result["anchor"] == pytest.approx((200.0, 0.0), abs=8.0)

    def test_a_loop_is_never_read_as_a_single_stroke_arrow(self):
        """A loop turns sharply too; the circle reading must win."""
        assert gesture.classify([circle_points(0, 0, 60)])["gesture"] == GESTURE_CIRCLE

    def test_straight_line_is_a_strike(self):
        assert gesture.classify([line_points(0, 0, 200, 60)])["gesture"] == GESTURE_STRIKE

    def test_crossed_lines_are_a_strike(self):
        result = gesture.classify([line_points(0, 0, 100, 100), line_points(0, 100, 100, 0)])
        assert result["gesture"] == GESTURE_STRIKE

    def test_open_squiggle_falls_through_to_stroke(self):
        squiggle = circle_points(0, 0, 100, n=40, gap_deg=230)
        result = gesture.classify([squiggle])
        assert result["gesture"] == GESTURE_STROKE
        assert result["closed"] is False
        assert len(result["polygon"]) >= 3

    def test_every_reading_carries_an_anchor(self):
        cases = [
            [circle_points(0, 0, 50)],
            [line_points(0, 0, 100, 0)],
            [circle_points(0, 0, 100, n=40, gap_deg=230)],
            [[(5.0, 5.0)]],
        ]
        for strokes in cases:
            result = gesture.classify(strokes)
            assert result is not None
            assert result["anchor"] is not None
