# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mark payload contract — shape, budget shedding, and prose.

This is the half of the feature the backend schema has to agree with, so the
shape is pinned here rather than left to whatever the operator happened to
build. Everything under test is ``bpy``-free by design.
"""

import json
import math

import pytest

from mixar.modules.scribble_mark.constants import (
    MARK_PAYLOAD_VERSION,
    MARK_POLYGON_MAX_POINTS,
    SURFACE_VIEW3D,
)
from mixar.modules.scribble_mark.core import gesture, payload as P


VIEW = "mixar_mark_view_0001"
VIEW_DATA = {"lens_mm": 50.0, "image_w": 1920, "image_h": 1080}


def loop_reading(cx=500, cy=400, r=120, n=64):
    pts = [
        (cx + r * math.cos(math.radians(360 * i / (n - 1))),
         cy + r * math.sin(math.radians(360 * i / (n - 1))))
        for i in range(n)
    ]
    return gesture.classify([pts])


def resolved_house(partial=True, vgroup="mixar_mark_0001"):
    first = {
        "name": "House",
        "coverage": 0.91,
        "object_fraction": 0.72,
        "partial": partial,
        "world_bbox": {"center": [0, 0, 1], "size": [4, 4, 2]},
    }
    if vgroup:
        first["vertex_group"] = vgroup
    return {
        "hit": True,
        "point": [1.2, -3.4, 0.9],
        "normal": [0.0, 0.0, 1.0],
        "objects": [
            first,
            {"name": "Chimney", "coverage": 0.09, "object_fraction": 0.4,
             "partial": True},
        ],
        "world_bbox": {"center": [0, 0, 1], "size": [3, 3, 1]},
        "face_count": 118,
        "empty_reason": None,
    }


class TestMarkShape:
    def test_mark_carries_region_and_resolution(self):
        mark = P.build_mark(1, VIEW, loop_reading(), 1920, 1080, resolved_house())
        assert mark["id"] == 1
        assert mark["view"] == VIEW
        assert mark["gesture"] == "circle"
        assert mark["closed"] is True
        assert set(mark["region"]) == {"bbox", "polygon", "anchor", "direction"}
        assert mark["resolved"]["objects"][0]["name"] == "House"

    def test_polygon_is_capped_and_normalized(self):
        mark = P.build_mark(1, VIEW, loop_reading(n=400), 1920, 1080)
        polygon = mark["region"]["polygon"]
        assert len(polygon) <= MARK_POLYGON_MAX_POINTS
        assert all(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0 for u, v in polygon)

    def test_bbox_brackets_the_polygon(self):
        mark = P.build_mark(1, VIEW, loop_reading(), 1920, 1080)
        u0, v0, u1, v1 = mark["region"]["bbox"]
        for u, v in mark["region"]["polygon"]:
            assert u0 <= u <= u1
            assert v0 <= v <= v1

    def test_a_tap_gets_a_degenerate_bbox_not_an_invented_region(self):
        """A tap has no outline. Falling back to the anchor keeps the bbox
        honest instead of claiming an area the user never drew."""
        reading = gesture.classify([[(960.0, 540.0), (961.0, 540.5)]])
        mark = P.build_mark(1, VIEW, reading, 1920, 1080)
        u0, v0, u1, v1 = mark["region"]["bbox"]
        assert mark["region"]["polygon"] == []
        assert u1 - u0 < 0.01
        assert v1 - v0 < 0.01
        assert mark["region"]["anchor"] == pytest.approx([0.5, 0.5], abs=0.005)

    def test_arrow_direction_survives(self):
        shaft = [(0.0 + i * 8, 200.0) for i in range(40)]
        head = [(290.0, 220.0), (312.0, 200.0), (290.0, 180.0)]
        mark = P.build_mark(1, VIEW, gesture.classify([shaft, head]), 1920, 1080)
        assert mark["gesture"] == "arrow"
        assert mark["region"]["direction"] == pytest.approx([1.0, 0.0], abs=0.05)

    def test_no_direction_serializes_as_none(self):
        mark = P.build_mark(1, VIEW, loop_reading(), 1920, 1080)
        assert mark["region"]["direction"] is None

    def test_resolution_is_omitted_rather_than_faked_when_it_did_not_run(self):
        mark = P.build_mark(1, VIEW, loop_reading(), 1920, 1080, resolved=None)
        assert "resolved" not in mark

    def test_zero_sized_region_raises(self):
        with pytest.raises(ValueError):
            P.build_mark(1, VIEW, loop_reading(), 0, 1080)


class TestPayloadShape:
    def test_payload_is_versioned_and_surface_tagged(self):
        marks = [P.build_mark(1, VIEW, loop_reading(), 1920, 1080)]
        pl = P.build_payload(marks, {VIEW: VIEW_DATA})
        assert pl["v"] == MARK_PAYLOAD_VERSION
        assert pl["surface"] == SURFACE_VIEW3D
        assert pl["views"] == {VIEW: VIEW_DATA}

    def test_multiple_marks_are_kept_in_order(self):
        marks = [P.build_mark(i, VIEW, loop_reading(), 1920, 1080) for i in (1, 2, 3)]
        pl = P.build_payload(marks, {VIEW: VIEW_DATA})
        assert [m["id"] for m in pl["marks"]] == [1, 2, 3]

    def test_marks_from_two_freezes_carry_both_views(self):
        """Disarming and re-arming mints a new view; a turn can legitimately
        span both, and each mark must point at the frame it was drawn on."""
        second = "mixar_mark_view_0002"
        marks = [
            P.build_mark(1, VIEW, loop_reading(), 1920, 1080),
            P.build_mark(2, second, loop_reading(), 1920, 1080),
        ]
        pl = P.build_payload(marks, {VIEW: VIEW_DATA, second: VIEW_DATA})
        assert set(pl["views"]) == {VIEW, second}

    def test_unreferenced_views_are_dropped(self):
        """Arming and then drawing nothing must not ship a stray camera."""
        marks = [P.build_mark(1, VIEW, loop_reading(), 1920, 1080)]
        pl = P.build_payload(marks, {VIEW: VIEW_DATA, "mixar_mark_view_0009": VIEW_DATA})
        assert set(pl["views"]) == {VIEW}


class TestBudgetShedding:
    def _big_payload(self, count=8):
        marks = [
            P.build_mark(i, VIEW, loop_reading(n=400), 1920, 1080, resolved_house())
            for i in range(1, count + 1)
        ]
        return P.build_payload(marks, {VIEW: VIEW_DATA})

    def test_under_budget_is_untouched(self):
        pl = self._big_payload(1)
        text, notes = P.serialize(pl, 1_000_000)
        assert notes == []
        assert json.loads(text) == pl

    def test_outlines_thin_before_marks_are_dropped(self):
        pl = self._big_payload()
        full = len(P.serialize(pl, 10 ** 9)[0].encode())
        text, notes = P.serialize(pl, int(full * 0.75))
        data = json.loads(text)
        assert len(data["marks"]) == 8
        assert notes and "thinned" in notes[0]

    def test_resolution_survives_every_level_of_shedding(self):
        """Which object the user pointed at is the whole feature. A payload
        that fits but no longer says that has thrown away the only thing the
        agent could not have derived itself."""
        pl = self._big_payload()
        for cap in (4000, 1500, 600, 200):
            data = json.loads(P.serialize(pl, cap)[0])
            assert data["marks"], f"every mark dropped at cap={cap}"
            for mark in data["marks"]:
                assert mark["resolved"]["objects"][0]["name"] == "House"
                assert mark["region"]["bbox"]

    def test_oldest_marks_go_first(self):
        pl = self._big_payload()
        data = json.loads(P.serialize(pl, 900)[0])
        ids = [m["id"] for m in data["marks"]]
        assert ids == sorted(ids)
        assert ids[-1] == 8, "the newest mark must always survive"

    def test_views_are_pruned_with_the_marks_that_referenced_them(self):
        second = "mixar_mark_view_0002"
        marks = [P.build_mark(1, VIEW, loop_reading(n=400), 1920, 1080, resolved_house())]
        marks += [
            P.build_mark(i, second, loop_reading(n=400), 1920, 1080, resolved_house())
            for i in range(2, 8)
        ]
        pl = P.build_payload(marks, {VIEW: VIEW_DATA, second: VIEW_DATA})
        data = json.loads(P.serialize(pl, 900)[0])
        assert set(data["views"]) == {m["view"] for m in data["marks"]}

    def test_one_mark_over_budget_is_sent_rather_than_lost(self):
        pl = self._big_payload(1)
        text, notes = P.serialize(pl, 50)
        data = json.loads(text)
        assert len(data["marks"]) == 1
        assert any("over budget" in n for n in notes)

    def test_shedding_is_always_reported(self):
        pl = self._big_payload()
        _, notes = P.serialize(pl, 900)
        assert notes, "silent truncation reads as 'we sent everything'"


class TestProse:
    def test_no_marks_gives_no_prose(self):
        assert P.summarize(P.build_payload([], {})) == ""

    def test_names_the_object_and_its_coverage(self):
        pl = P.build_payload(
            [P.build_mark(1, VIEW, loop_reading(), 1920, 1080, resolved_house())],
            {VIEW: VIEW_DATA},
        )
        text = P.summarize(pl)
        assert "circled" in text
        assert "`House`" in text
        # object_fraction (how much of the House), never coverage (how much
        # of the mark) — an agent acts on this number.
        assert "72%" in text
        assert "91%" not in text

    def test_points_the_agent_at_the_vertex_group(self):
        pl = P.build_payload(
            [P.build_mark(1, VIEW, loop_reading(), 1920, 1080, resolved_house())],
            {VIEW: VIEW_DATA},
        )
        assert "mixar_mark_0001" in P.summarize(pl)

    def test_full_coverage_reads_as_the_whole_object(self):
        resolved = resolved_house(partial=False, vgroup=None)
        pl = P.build_payload(
            [P.build_mark(1, VIEW, loop_reading(), 1920, 1080, resolved)],
            {VIEW: VIEW_DATA},
        )
        text = P.summarize(pl)
        assert "essentially all of it" in text
        assert "vertex group" not in text

    def test_empty_space_is_stated_not_glossed_over(self):
        """An agent that knows the user pointed at nothing can say so, rather
        than picking whichever object happened to be nearby."""
        resolved = {"hit": False, "empty_reason": "no_hit", "objects": []}
        pl = P.build_payload(
            [P.build_mark(1, VIEW, loop_reading(), 1920, 1080, resolved)],
            {VIEW: VIEW_DATA},
        )
        text = P.summarize(pl)
        assert "empty space" in text
        assert "no_hit" in text

    def test_several_marks_are_numbered(self):
        marks = [
            P.build_mark(i, VIEW, loop_reading(), 1920, 1080, resolved_house())
            for i in (1, 2)
        ]
        text = P.summarize(P.build_payload(marks, {VIEW: VIEW_DATA}))
        assert "Mark 1:" in text and "Mark 2:" in text

    def test_a_single_mark_is_not_numbered(self):
        pl = P.build_payload(
            [P.build_mark(1, VIEW, loop_reading(), 1920, 1080, resolved_house())],
            {VIEW: VIEW_DATA},
        )
        assert "Mark 1:" not in P.summarize(pl)

    def test_secondary_objects_are_mentioned(self):
        pl = P.build_payload(
            [P.build_mark(1, VIEW, loop_reading(), 1920, 1080, resolved_house())],
            {VIEW: VIEW_DATA},
        )
        assert "`Chimney`" in P.summarize(pl)

    def test_unresolved_marks_still_produce_a_sentence(self):
        pl = P.build_payload(
            [P.build_mark(1, VIEW, loop_reading(), 1920, 1080)], {VIEW: VIEW_DATA}
        )
        assert P.summarize(pl).strip()
