# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Capture and simplification — the two things that decide how faithfully a
drawn line survives the trip from the tablet to the agent.

Both halves are pure Python by design (``core/stroke_capture.py``,
``core/simplify.py``), which is what lets them be measured here
instead of only by drawing on a real tablet.
"""

import math

import pytest

from mixar.modules.scribble_mark.core.geometry import decimate
from mixar.modules.scribble_mark.core.simplify import sample_shape, simplify_shape
from mixar.modules.scribble_mark.core.stroke_capture import (
    StrokeBuffer,
    stroke_points,
)


def buffer(max_strokes=4, max_points=8):
    return StrokeBuffer(max_strokes, max_points)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


class TestSampleDecimation:
    """Samples are decimated by DISTANCE, measured radially."""

    def test_a_sample_closer_than_the_threshold_is_dropped(self):
        ink = buffer()
        ink.begin((0.0, 0.0))
        assert ink.extend((1.0, 0.0), 2.0) is False
        assert ink.strokes == [[(0.0, 0.0)]]

    def test_a_sample_past_the_threshold_is_kept(self):
        ink = buffer()
        ink.begin((0.0, 0.0))
        assert ink.extend((3.0, 0.0), 2.0) is True
        assert ink.strokes[0][-1] == (3.0, 0.0)

    @pytest.mark.parametrize("dx,dy", [(2.0, 0.0), (0.0, 2.0), (1.5, 1.5), (-1.5, 1.5)])
    def test_the_threshold_is_the_same_in_every_direction(self, dx, dy):
        """A per-axis box test accepted a 2 px step along an axis and rejected
        a 2.8 px step across the diagonal, so the same hand speed left a
        different density of ink depending on which way the stroke ran."""
        threshold = 2.0
        expected = math.hypot(dx, dy) >= threshold
        ink = buffer()
        ink.begin((0.0, 0.0))
        assert ink.extend((dx, dy), threshold) is expected

    def test_extending_with_the_pen_up_adds_nothing(self):
        ink = buffer()
        assert ink.extend((5.0, 5.0), 2.0) is False
        assert ink.empty


class TestFullStroke:
    """A full stroke is HALVED, never truncated: losing the end of a long
    line is silent, and nothing on screen says the ink stopped being kept."""

    def test_the_whole_path_survives_the_cap(self):
        ink = buffer(max_points=8)
        ink.begin((0.0, 0.0))
        for i in range(1, 40):
            ink.extend((float(i * 10), 0.0), 2.0)
        stroke = ink.strokes[0]
        assert len(stroke) <= 8
        # The END of the line is still there — that is the whole point.
        assert stroke[-1] == (390.0, 0.0)
        assert stroke[0] == (0.0, 0.0)

    def test_the_buffer_never_grows_past_the_cap(self):
        ink = buffer(max_points=6)
        ink.begin((0.0, 0.0))
        for i in range(1, 200):
            ink.extend((float(i * 10), 0.0), 2.0)
        assert len(ink.strokes[0]) <= 6

    def test_halving_keeps_the_list_the_caller_is_drawing(self):
        """The overlay holds the point list by reference; rebinding it would
        leave the ink on screen frozen at the moment the stroke filled up."""
        ink = buffer(max_points=4)
        ink.begin((0.0, 0.0))
        held = ink.strokes[0]
        for i in range(1, 20):
            ink.extend((float(i * 10), 0.0), 2.0)
        assert ink.strokes[0] is held


class TestGrouping:
    def test_full_reports_when_another_stroke_would_not_fit(self):
        ink = buffer(max_strokes=2)
        ink.begin((0.0, 0.0))
        ink.end(1.0)
        assert not ink.full
        ink.begin((1.0, 1.0))
        ink.end(2.0)
        assert ink.full

    def test_idle_is_measured_from_the_last_pen_up(self):
        ink = buffer()
        ink.begin((0.0, 0.0))
        ink.end(10.0)
        assert ink.idle_for(10.5) == pytest.approx(0.5)

    def test_a_release_with_nothing_live_still_restarts_the_clock(self):
        """A pen that lifts outside the region never delivers its release
        here; the recovery release must not be a no-op."""
        ink = buffer()
        ink.end(7.0)
        assert not ink.drawing
        assert ink.idle_for(7.25) == pytest.approx(0.25)

    def test_take_hands_the_group_over_and_starts_an_empty_one(self):
        ink = buffer()
        ink.begin((0.0, 0.0))
        ink.extend((10.0, 0.0), 2.0)
        ink.end(1.0)
        taken = ink.take()
        assert taken == [[(0.0, 0.0), (10.0, 0.0)]]
        assert ink.empty and not ink.drawing
        assert ink.strokes is not taken

    def test_clear_drops_the_half_drawn_gesture(self):
        ink = buffer()
        ink.begin((0.0, 0.0))
        ink.clear()
        assert ink.empty and not ink.drawing

    def test_stroke_points_counts_every_sample(self):
        assert stroke_points([[(0, 0), (1, 1)], [(2, 2)]]) == 3


# ---------------------------------------------------------------------------
# Simplification
# ---------------------------------------------------------------------------


def _polyline_error(selected, points):
    """Worst distance from an original point to the simplified polyline."""
    worst = 0.0
    for point in points:
        best = float("inf")
        for a, b in zip(selected, selected[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            span = dx * dx + dy * dy
            if span <= 0.0:
                distance = math.hypot(point[0] - a[0], point[1] - a[1])
            else:
                t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / span
                t = max(0.0, min(1.0, t))
                distance = math.hypot(point[0] - (a[0] + t * dx),
                                      point[1] - (a[1] + t * dy))
            best = min(best, distance)
        worst = max(worst, best)
    return worst


def drawn_outline():
    """A hand-drawn profile: a long slow roofline, then two sharp corners.

    The shape of the thing is entirely in the corners; the roofline is where
    a slow hand piled up samples that say nothing a straight chord does not.
    """
    points = [(i * 1.0, 100.0) for i in range(60)]
    points += [(59.0 + i * 0.5, 100.0 - i * 10.0) for i in range(1, 11)]
    points += [(64.0 - i * 6.0, -i * 0.3) for i in range(1, 11)]
    return points


class TestSimplifyShape:
    def test_it_keeps_the_corners_uniform_decimation_loses(self):
        points = drawn_outline()
        uniform = decimate(points, 8)
        shaped = simplify_shape(points, 8)
        assert len(shaped) <= 8
        assert _polyline_error(shaped, points) < _polyline_error(uniform, points)

    def test_both_ends_always_survive(self):
        points = drawn_outline()
        shaped = simplify_shape(points, 5)
        assert shaped[0] == points[0]
        assert shaped[-1] == points[-1]

    def test_a_stroke_inside_the_budget_is_returned_whole(self):
        points = drawn_outline()[:5]
        assert simplify_shape(points, 8) == points

    def test_it_never_exceeds_the_budget(self):
        points = drawn_outline()
        for budget in (2, 3, 8, 16, 48):
            assert len(simplify_shape(points, budget)) <= budget

    def test_a_budget_below_two_still_yields_a_segment(self):
        assert len(simplify_shape(drawn_outline(), 1)) == 2

    def test_a_still_pen_does_not_divide_by_zero(self):
        assert len(simplify_shape([(0.0, 0.0)] * 10, 4)) == 2

    def test_an_empty_stroke_is_empty(self):
        assert simplify_shape([], 8) == []

    def test_it_is_deterministic(self):
        points = drawn_outline()
        assert simplify_shape(points, 12) == simplify_shape(points, 12)

    def test_it_carries_points_of_any_dimension(self):
        points = [(float(i), float(i % 3), float(i) * 0.5) for i in range(40)]
        shaped = simplify_shape(points, 6)
        assert all(len(p) == 3 for p in shaped)

    def test_deviation_is_measured_in_every_dimension(self):
        """The payload shedder runs this over WORLD paths. A stroke drawn on
        an axis-aligned wall varies in x and z while y barely moves; an
        x/y-only metric reads that as a straight line and hands back the two
        endpoints, throwing the whole shape away."""
        wall = [[float(i), 3.0, float(i % 4)] for i in range(12)]
        shaped = simplify_shape(wall, 4)
        assert len(shaped) == 4
        # The z extremes are the shape here, and they have to survive.
        kept_z = {point[2] for point in shaped}
        assert max(kept_z) - min(kept_z) >= 3.0

    def test_a_genuinely_straight_run_is_still_two_points(self):
        """Stopping early is the point when the samples already say
        everything: a straight line is two points, and a shed that keeps
        more is wire budget spent on nothing."""
        straight = [(float(i) * 10.0, 5.0) for i in range(40)]
        assert len(simplify_shape(straight, 16)) == 2


class TestSampleShape:
    """Choosing where to spend a measurement the samples do not yet carry."""

    def test_a_straight_screen_stroke_still_spends_its_whole_ray_budget(self):
        """A road drawn STRAIGHT across a hillside is two points of screen
        shape and a dozen of terrain. The ground is not in the samples, so
        an unspent budget is a terrain profile thrown away — this is why the
        ray path cannot use simplify_shape."""
        straight = [(float(i) * 10.0, 100.0) for i in range(40)]
        assert len(sample_shape(straight, 16)) == 16

    def test_the_fill_is_evenly_spaced_and_in_order(self):
        straight = [(float(i) * 10.0, 100.0) for i in range(40)]
        picked = sample_shape(straight, 5)
        assert picked == sorted(picked)
        assert picked[0] == straight[0] and picked[-1] == straight[-1]
        gaps = [b[0] - a[0] for a, b in zip(picked, picked[1:])]
        assert max(gaps) - min(gaps) <= 20.0

    def test_a_stroke_that_bends_still_spends_its_budget_on_the_bends(self):
        points = drawn_outline()
        shaped = set(map(tuple, simplify_shape(points, 8)))
        sampled = set(map(tuple, sample_shape(points, 8)))
        assert shaped <= sampled
        assert len(sampled) == 8

    def test_it_never_exceeds_the_budget_or_invents_points(self):
        points = drawn_outline()
        for budget in (2, 3, 8, 16, 48):
            picked = sample_shape(points, budget)
            assert len(picked) == budget
            assert all(p in points for p in picked)

    def test_a_stroke_inside_the_budget_is_returned_whole(self):
        points = drawn_outline()[:5]
        assert sample_shape(points, 8) == points

    def test_duplicate_samples_cannot_overrun_the_budget(self):
        """A still pen makes every candidate identical; the fill must not
        loop past the end of the stroke looking for a fresh index."""
        still = [(0.0, 0.0)] * 30
        assert len(sample_shape(still, 8)) == 8


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class TestSketchBudget:
    """A drawing-sized turn has to fit the prompt budget without losing the
    drawing. The world paths are the first thing thinned, and never the
    resolution."""

    @staticmethod
    def sketch_payload(marks=32, strokes_per_mark=2):
        import math

        from mixar.modules.scribble_mark.constants import (
            STROKE_WORLD_POINTS, WORLD_DECIMALS,
        )

        out = []
        for index in range(marks):
            world = []
            for _ in range(strokes_per_mark):
                world.append({
                    "points": [
                        [round(index + math.sin(i), WORLD_DECIMALS),
                         round(i * 0.37, WORLD_DECIMALS),
                         round(math.cos(i) * 2.0, WORLD_DECIMALS)]
                        for i in range(STROKE_WORLD_POINTS)
                    ],
                    "on": "ground",
                })
            out.append({
                "id": index,
                "view": "MixarMarkView",
                "gesture": "stroke",
                "closed": False,
                "region": {
                    "bbox": [0.1, 0.1, 0.9, 0.9],
                    "polygon": [[0.01 * i, 0.01 * i] for i in range(32)],
                    "anchor": [0.5, 0.5],
                    "direction": None,
                },
                "strokes": [
                    [[0.001 * i, 0.002 * i] for i in range(48)]
                    for _ in range(strokes_per_mark)
                ],
                "resolved": {
                    "hit": {"object": f"Object_{index}", "coverage": 0.8},
                    "point": [1.0, 2.0, 3.0],
                    "strokes_world": world,
                },
            })
        return out

    def test_a_full_drawing_serializes_within_the_budget(self):
        import json

        from mixar.modules.scribble_mark.constants import MARK_JSON_MAX_BYTES
        from mixar.modules.scribble_mark.core.payload import build_payload, serialize

        payload = build_payload(
            self.sketch_payload(),
            {"MixarMarkView": {"frame": "f", "width": 1920, "height": 1080}},
        )
        text, notes = serialize(payload)
        assert len(text.encode("utf-8")) <= MARK_JSON_MAX_BYTES, notes
        body = json.loads(text)
        # Resolution is never shed: it is the one thing the agent could not
        # have worked out from the frame itself.
        assert all(m.get("resolved") for m in body["marks"])
        assert len(body["marks"]) == 32

    def test_the_world_paths_stay_within_the_backend_schema_cap(self):
        """modules/agent/schemas/marks_sketch.MAX_SKETCH_WORLD_POINTS is 16."""
        import json

        from mixar.modules.scribble_mark.core.payload import build_payload, serialize

        payload = build_payload(
            self.sketch_payload(),
            {"MixarMarkView": {"frame": "f", "width": 1920, "height": 1080}},
            intent_override="sketch",
        )
        body = json.loads(serialize(payload)[0])
        for stroke in (body.get("sketch") or {}).get("strokes") or []:
            assert len(stroke.get("world") or []) <= 16
