# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sampling and ranking: turning raycast hits into "what did they point at".

The raycast needs a depsgraph and lives in ``resolve``; everything here is
arithmetic and is tested against real numbers.
"""

import pytest

from mixar.modules.scribble_mark.constants import PARTIAL_COVERAGE_MAX
from mixar.modules.scribble_mark.core import coverage as C


SQUARE = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


class TestGridSamples:
    def test_samples_land_inside_the_polygon(self):
        samples = C.grid_samples(SQUARE, grid=8)
        assert len(samples) == 64
        assert all(0 < x < 100 and 0 < y < 100 for x, y in samples)

    def test_concave_polygon_skips_its_notch(self):
        c_shape = [(0, 0), (100, 0), (100, 30), (40, 30),
                   (40, 70), (100, 70), (100, 100), (0, 100)]
        samples = C.grid_samples(c_shape, grid=10)
        assert samples
        # Nothing in the bite taken out of the right-hand middle.
        assert not [s for s in samples if s[0] > 45 and 32 < s[1] < 68]

    def test_a_thin_sliver_is_still_sampled_along_its_length(self):
        """A strike-through is thin but not degenerate; the lattice adapts to
        its bbox, so it samples across what was actually struck through."""
        sliver = [(0.0, 50.0), (100.0, 50.2), (100.0, 50.4), (0.0, 50.1)]
        samples = C.grid_samples(sliver, grid=4, anchor=(50.0, 50.2))
        assert len(samples) > 1
        assert min(s[0] for s in samples) < 25
        assert max(s[0] for s in samples) > 75

    def test_a_zero_area_shape_falls_back_to_the_anchor(self):
        """A perfectly straight two-point mark encloses nothing, so no
        lattice cell can be inside it. One honest sample beats reporting that
        the user pointed at nothing."""
        flat = [(0.0, 50.0), (50.0, 50.0), (100.0, 50.0)]
        assert C.grid_samples(flat, grid=4, anchor=(50.0, 50.0)) == [(50.0, 50.0)]

    def test_no_polygon_uses_the_anchor(self):
        assert C.grid_samples([], grid=8, anchor=(5.0, 6.0)) == [(5.0, 6.0)]

    def test_no_polygon_and_no_anchor_is_empty_not_an_error(self):
        assert C.grid_samples([], grid=8) == []

    def test_degenerate_polygon_still_samples_its_bbox(self):
        """Fewer than 3 points cannot be a containment test, so the bbox
        lattice is used directly rather than returning nothing."""
        assert len(C.grid_samples([(0, 0), (10, 10)], grid=4)) == 16


class TestTally:
    def test_counts_hits_and_misses(self):
        counts, hits, misses = C.tally_hits(["A", "A", "B", None, None, "A"])
        assert counts == {"A": 3, "B": 1}
        assert hits == 4
        assert misses == 2

    def test_all_misses(self):
        counts, hits, misses = C.tally_hits([None, None])
        assert counts == {} and hits == 0 and misses == 2

    def test_empty(self):
        assert C.tally_hits([]) == ({}, 0, 0)


class TestRanking:
    def test_most_covered_object_leads(self):
        ranked = C.rank_objects({"House": 30, "Tree": 5}, 35)
        assert [o["name"] for o in ranked] == ["House", "Tree"]
        assert ranked[0]["coverage"] == pytest.approx(30 / 35, abs=1e-4)

    def test_slivers_at_the_edge_of_the_loop_are_dropped(self):
        ranked = C.rank_objects({"House": 99, "Fence": 1}, 100)
        assert [o["name"] for o in ranked] == ["House"]

    def test_object_list_is_capped(self):
        counts = {f"Obj{i}": 10 for i in range(20)}
        assert len(C.rank_objects(counts, 200)) <= 6

    def test_ordering_is_stable_across_runs(self):
        """An agent re-reading marks between turns must not see the dominant
        object swap, so equal coverage breaks on name."""
        counts = {"Beta": 10, "Alpha": 10, "Gamma": 10}
        first = [o["name"] for o in C.rank_objects(counts, 30)]
        assert first == sorted(first)

    def test_no_hits_gives_no_objects(self):
        assert C.rank_objects({}, 0) == []

    def test_object_fraction_drives_partial(self):
        ranked = C.rank_objects({"House": 10}, 10, {"House": 0.4})
        assert ranked[0]["object_fraction"] == pytest.approx(0.4)
        assert ranked[0]["partial"] is True

    def test_a_fully_enclosed_object_is_not_partial(self):
        ranked = C.rank_objects({"House": 10}, 10, {"House": 1.0})
        assert ranked[0]["partial"] is False

    def test_unmeasurable_object_fraction_reads_as_partial_not_whole(self):
        """"We could not measure it" must never reach the agent as "the user
        selected all of it" — that is the difference between editing a roof
        and editing a house."""
        ranked = C.rank_objects({"House": 10}, 10, {})
        assert ranked[0]["object_fraction"] is None
        assert ranked[0]["partial"] is True

    def test_the_partial_threshold_is_the_documented_one(self):
        just_under = C.rank_objects({"H": 1}, 1, {"H": PARTIAL_COVERAGE_MAX - 0.01})
        just_over = C.rank_objects({"H": 1}, 1, {"H": PARTIAL_COVERAGE_MAX + 0.01})
        assert just_under[0]["partial"] is True
        assert just_over[0]["partial"] is False

    def test_coverage_and_object_fraction_are_independent(self):
        """A scribble over one wall: nearly all of the MARK is the house
        (coverage high), but only a little of the HOUSE is marked
        (object_fraction low). Conflating them is a real bug."""
        ranked = C.rank_objects({"House": 95, "Sky": 5}, 100, {"House": 0.12})
        assert ranked[0]["coverage"] == pytest.approx(0.95)
        assert ranked[0]["object_fraction"] == pytest.approx(0.12)
        assert ranked[0]["partial"] is True


class TestStatus:
    def test_geometry_under_the_mark_is_a_hit(self):
        assert C.resolve_status(40, 24, 64) == (True, None)

    def test_all_misses_is_background(self):
        assert C.resolve_status(0, 64, 64) == (False, "background")

    def test_no_samples_is_too_small(self):
        assert C.resolve_status(0, 0, 0) == (False, "too_small")

    def test_a_single_stray_hit_is_not_treated_as_an_answer(self):
        """Pinning an edit to whichever one ray happened to land is exactly
        the guessing this feature removes."""
        assert C.resolve_status(1, 8, 9) == (False, "too_small")

    def test_a_small_but_solid_sample_is_a_hit(self):
        assert C.resolve_status(3, 1, 4) == (True, None)


class TestScreenOverlap:
    def test_fully_enclosed_object(self):
        assert C.rect_overlap_fraction((10, 10, 20, 20), (0, 0, 100, 100)) == 1.0

    def test_half_enclosed_object(self):
        assert C.rect_overlap_fraction((0, 0, 100, 100), (0, 0, 50, 100)) == pytest.approx(0.5)

    def test_disjoint_is_zero(self):
        assert C.rect_overlap_fraction((0, 0, 10, 10), (50, 50, 60, 60)) == 0.0

    def test_edge_on_object_is_in_or_out_not_nan(self):
        """An object seen exactly edge-on projects to zero area; dividing by
        it would produce NaN and poison every comparison downstream."""
        assert C.rect_overlap_fraction((5, 5, 5, 5), (0, 0, 10, 10)) == 1.0
        assert C.rect_overlap_fraction((50, 50, 50, 50), (0, 0, 10, 10)) == 0.0

    def test_never_exceeds_one(self):
        assert C.rect_overlap_fraction((10, 10, 20, 20), (-1000, -1000, 1000, 1000)) == 1.0

    def test_screen_bbox_drops_unprojectable_corners(self):
        """A corner behind the camera has no projection. Clamping it would
        drag the box across the frame and make the object look enormous."""
        assert C.screen_bbox([(0, 0), None, (10, 10), None]) == (0, 0, 10, 10)

    def test_screen_bbox_of_nothing_is_none(self):
        assert C.screen_bbox([None, None]) is None
        assert C.screen_bbox([]) is None
