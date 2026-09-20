# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A drawing is one sketch, not a list of the pauses it took to draw.

The user sketched a road with cars and trees on the side and asked for a
scene like it. The ink was chopped into per-pause marks, each landed on the
ground as a "placement target", the annotated frame showed convex hulls
instead of the drawing, and the agent built a campfire at nine spots. What
is pinned here: the reading that tells a sketch from pointing, the block that
anchors every stroke in the world, the frame drawn from the raw ink, and the
controls that make the reading visible and flippable.
"""

import json
import math

import pytest

from mixar.modules.scribble_mark import constants as C
from mixar.modules.scribble_mark.core import payload as P
from mixar.modules.scribble_mark.core import sketch as S


# =============================================================================
# Ink fixtures, in region pixels on a 1920x1080 frame
# =============================================================================

W, H = 1920, 1080
VIEW = "mixar_mark_view_0001"
VIEW_DATA = {"camera": VIEW, "image_w": W, "image_h": H}


def circle(cx, cy, r, n=24):
    return [(cx + r * math.cos(2 * math.pi * i / n),
             cy + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]


def line(x0, y0, x1, y1, n=10):
    return [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1)]


def tap(x, y):
    return [(x, y), (x + 1.0, y + 1.0)]


def reading(gesture, strokes, closed=False):
    flat = [p for s in strokes for p in s]
    return {
        "gesture": gesture,
        "anchor": (sum(p[0] for p in flat) / len(flat), sum(p[1] for p in flat) / len(flat)),
        "direction": None,
        "polygon": flat if gesture == "circle" else flat[:8],
        "closed": closed,
    }


def ground_resolved(strokes, x=0.0, y=0.0):
    """What the resolver reports for ink on nothing, with stroke paths."""
    return {
        "hit": False, "point": [x, y, 0.0], "normal": [0, 0, 1], "objects": [],
        "world_bbox": {"center": [x, y, 0.0], "size": [1.0, 1.0, 0.0]},
        "sample_count": 20, "hit_count": 0, "empty_reason": "background",
        "plane": "ground", "plane_z": 0.0,
        "strokes_world": [
            {"points": [[x + i, y, 0.0] for i in range(min(8, len(s)))], "on": "ground"}
            for s in strokes
        ],
    }


def object_resolved(strokes, name="House", fraction=0.3):
    return {
        "hit": True, "point": [1.0, 2.0, 0.5], "normal": [0, 0, 1],
        "objects": [{"name": name, "coverage": 0.9, "object_fraction": fraction,
                     "partial": fraction < 0.85}],
        "world_bbox": None, "sample_count": 20, "hit_count": 18, "empty_reason": None,
        "strokes_world": [
            {"points": [[1.0 + i * 0.1, 2.0, 0.5] for i in range(min(8, len(s)))],
             "on": name}
            for s in strokes
        ],
    }


def mark(mark_id, gesture, strokes, resolved):
    return P.build_mark(mark_id, VIEW, reading(gesture, strokes, gesture == "circle"),
                        W, H, resolved, strokes=strokes)


# --- the scenarios ----------------------------------------------------------

def road_with_cars_and_trees(resolver=ground_resolved):
    """The user's own sketch: two road lines, two cars, three trees."""
    marks = []
    road = [line(100, 300, 1800, 400), line(100, 200, 1800, 300)]
    marks.append(mark(1, "strike", road, resolver(road)))
    for i, cx in enumerate((500, 1100)):
        car = [circle(cx, 350, 60), circle(cx - 40, 300, 12), circle(cx + 40, 300, 12),
               line(cx - 30, 380, cx + 30, 380), line(cx - 50, 340, cx - 20, 340)]
        marks.append(mark(2 + i, "circle", car, resolver(car, cx / 100.0)))
    for i, cx in enumerate((300, 900, 1500)):
        tree = [circle(cx, 700, 50), line(cx, 650, cx, 560)]
        marks.append(mark(4 + i, "circle", tree, resolver(tree, cx / 100.0, 5.0)))
    return marks


def three_circles_on_ground():
    return [
        mark(i, "circle", [circle(400 * i, 500, 60)], ground_resolved([circle(0, 0, 1)], i * 3.0))
        for i in (1, 2, 3)
    ]


def pointing_at_a_house():
    """Circle the roof, arrow to the door, X the chimney, tap the wall."""
    roof = [circle(900, 700, 150)]
    door = [line(400, 200, 850, 350), line(820, 380, 850, 350)]
    chimney = [line(1000, 800, 1100, 900), line(1100, 800, 1000, 900)]
    wall = [tap(700, 400)]
    return [
        mark(1, "circle", roof, object_resolved(roof, fraction=0.3)),
        mark(2, "arrow", door, object_resolved(door, fraction=0.05)),
        mark(3, "strike", chimney, object_resolved(chimney, fraction=0.03)),
        mark(4, "point", wall, object_resolved(wall, fraction=0.01)),
    ]


def move_this_over_there():
    return [
        mark(1, "circle", [circle(500, 500, 80)], object_resolved([circle(0, 0, 1)])),
        mark(2, "arrow", [line(600, 500, 1400, 500), line(1370, 470, 1400, 500)],
             ground_resolved([line(0, 0, 1, 1), line(0, 0, 1, 1)], 6.0)),
    ]


# =============================================================================
# Stroke kinds
# =============================================================================

class TestStrokeKind:
    def test_a_loop_is_closed(self):
        assert S.stroke_kind(P.to_normalized(circle(500, 500, 100), W, H)) == S.KIND_CLOSED

    def test_a_line_is_open(self):
        assert S.stroke_kind(P.to_normalized(line(100, 100, 900, 700), W, H)) == S.KIND_OPEN

    def test_a_tap_is_a_tap(self):
        assert S.stroke_kind(P.to_normalized(tap(500, 500), W, H)) == S.KIND_TAP
        assert S.stroke_kind([(0.5, 0.5)]) == S.KIND_TAP


# =============================================================================
# The reading
# =============================================================================

class TestReadIntent:
    def test_a_road_with_cars_and_trees_is_a_sketch(self):
        intent, stats = S.read_intent(road_with_cars_and_trees())
        assert intent == C.INTENT_SKETCH
        assert stats["strokes"] == 18
        assert stats["open"] >= C.SKETCH_MIN_OPEN_STROKES

    def test_the_same_drawing_over_a_floor_mesh_is_still_a_sketch(self):
        """Every stroke hits the floor with a sliver of coverage; that is ink
        ON a surface, not a selection of it."""
        def on_floor(strokes, *_a):
            return object_resolved(strokes, name="Floor", fraction=0.01)
        intent, _ = S.read_intent(road_with_cars_and_trees(on_floor))
        assert intent == C.INTENT_SKETCH

    def test_three_circles_on_empty_ground_are_placement_targets(self):
        """The layout that was fixed last time must keep working: no open
        lines means no drawing."""
        intent, stats = S.read_intent(three_circles_on_ground())
        assert intent == C.INTENT_POINT
        assert stats["open"] == 0

    def test_pointing_gestures_on_one_object_stay_pointing(self):
        intent, stats = S.read_intent(pointing_at_a_house())
        assert intent == C.INTENT_POINT
        assert stats["drawn"] == 0

    def test_move_this_over_there_stays_pointing(self):
        assert S.read_intent(move_this_over_there())[0] == C.INTENT_POINT

    def test_no_marks_is_pointing(self):
        assert S.read_intent([])[0] == C.INTENT_POINT

    def test_records_without_strokes_read_as_pointing(self):
        """A .blend from before strokes were stored has no ink to read."""
        old = [mark(1, "circle", [circle(500, 500, 80)], ground_resolved([]))]
        for m in old:
            m.pop("strokes")
        assert S.read_intent(old)[0] == C.INTENT_POINT

    def test_an_irregular_line_on_an_object_counts_as_drawn(self):
        squiggle = [line(100, 100, 500, 300, 30)]
        m = mark(1, "stroke", squiggle, object_resolved(squiggle, fraction=0.5))
        assert S.is_drawn(m, total_strokes=1)

    def test_a_doodle_on_an_object_counts_as_drawn(self):
        m = mark(1, "circle", [circle(500, 500, 60), line(1, 1, 5, 5), line(2, 2, 6, 6)],
                 object_resolved([[]] * 3, fraction=0.5))
        assert S.is_drawn(m, total_strokes=3)

    def test_a_large_loop_on_an_object_is_a_selection_even_in_a_long_session(self):
        m = mark(1, "circle", [circle(500, 500, 60)], object_resolved([[]], fraction=0.6))
        assert not S.is_drawn(m, total_strokes=20)


# =============================================================================
# The sketch block
# =============================================================================

class TestBuildSketch:
    def test_every_stroke_travels_in_drawing_order_with_its_world_path(self):
        sketch = S.build_sketch(road_with_cars_and_trees())
        assert sketch["stroke_count"] == 18
        assert [s["mark"] for s in sketch["strokes"]][:2] == [1, 1]
        first = sketch["strokes"][0]
        assert first["kind"] == S.KIND_OPEN
        assert first["on"] == "ground"
        assert len(first["world"]) == 8
        assert len(first["bbox"]) == 4

    def test_the_extent_is_measured_in_the_world_and_in_the_frame(self):
        sketch = S.build_sketch(road_with_cars_and_trees())
        assert sketch["world_bbox"]["size"][0] > 0
        assert sketch["world_bbox"]["center"][2] == 0.0
        u0, v0, u1, v1 = sketch["bbox"]
        assert 0 <= u0 < u1 <= 1 and 0 <= v0 < v1 <= 1

    def test_surfaces_say_where_the_ink_landed(self):
        sketch = S.build_sketch(road_with_cars_and_trees())
        assert sketch["surfaces"] == {"ground": 18, "objects": {}}

        def on_floor(strokes, *_a):
            return object_resolved(strokes, name="Floor", fraction=0.01)
        sketch = S.build_sketch(road_with_cars_and_trees(on_floor))
        assert sketch["surfaces"]["objects"] == {"Floor": 18}

    def test_the_longest_strokes_survive_the_cap_in_drawing_order(self):
        marks = []
        for i in range(C.SKETCH_MAX_STROKES + 10):
            length = 10 + i * 5
            strokes = [line(0, 0, length, 0)]
            marks.append(mark(i + 1, "stroke", strokes, ground_resolved(strokes)))
        sketch = S.build_sketch(marks)
        assert sketch["stroke_count"] == C.SKETCH_MAX_STROKES + 10
        assert len(sketch["strokes"]) == C.SKETCH_MAX_STROKES
        kept = [s["mark"] for s in sketch["strokes"]]
        assert kept == sorted(kept), "drawing order is kept"
        assert kept[0] == 11, "the ten shortest were dropped"

    def test_a_stroke_without_world_samples_still_travels(self):
        m = mark(1, "stroke", [line(0, 1000, 500, 1050)], {"hit": False, "objects": [],
                                                           "empty_reason": "no_hit"})
        sketch = S.build_sketch([m])
        assert sketch["strokes"][0]["world"] == []
        assert sketch["strokes"][0]["on"] is None
        assert sketch["world_bbox"] is None


# =============================================================================
# The payload
# =============================================================================

class TestPayloadIntent:
    def test_a_sketch_payload_carries_the_block_and_says_it_was_read(self):
        pl = P.build_payload(road_with_cars_and_trees(), {VIEW: VIEW_DATA})
        assert pl["intent"] == C.INTENT_SKETCH
        assert pl["intent_source"] == "auto"
        assert pl["sketch"]["stroke_count"] == 18

    def test_a_pointing_payload_has_no_sketch_block(self):
        pl = P.build_payload(pointing_at_a_house(), {VIEW: VIEW_DATA})
        assert pl["intent"] == C.INTENT_POINT
        assert "sketch" not in pl

    def test_the_user_can_overrule_the_reading_either_way(self):
        pl = P.build_payload(three_circles_on_ground(), {VIEW: VIEW_DATA},
                             intent_override=C.INTENT_SKETCH)
        assert pl["intent"] == C.INTENT_SKETCH and pl["intent_source"] == "user"
        assert "sketch" in pl

        pl = P.build_payload(road_with_cars_and_trees(), {VIEW: VIEW_DATA},
                             intent_override=C.INTENT_POINT)
        assert pl["intent"] == C.INTENT_POINT and pl["intent_source"] == "user"
        assert "sketch" not in pl

    def test_an_unknown_override_falls_back_to_the_reading(self):
        pl = P.build_payload(pointing_at_a_house(), {VIEW: VIEW_DATA},
                             intent_override="banana")
        assert pl["intent"] == C.INTENT_POINT and pl["intent_source"] == "auto"

    def test_raw_strokes_stay_off_the_wire_but_their_count_travels(self):
        """The sketch block and the annotated frame carry the ink; per-mark
        copies would carry it three times over."""
        pl = P.build_payload(road_with_cars_and_trees(), {VIEW: VIEW_DATA})
        for m in pl["marks"]:
            assert "strokes" not in m
            assert "strokes_world" not in m["resolved"]
        assert pl["marks"][1]["stroke_count"] == 5

    def test_the_stored_mark_keeps_its_strokes(self):
        """build_payload must not mutate the records it was handed — the
        annotated frame is drawn from them afterwards."""
        marks = road_with_cars_and_trees()
        P.build_payload(marks, {VIEW: VIEW_DATA})
        assert len(marks[1]["strokes"]) == 5
        assert marks[1]["resolved"]["strokes_world"]

    def test_stored_strokes_are_normalized_and_bounded(self):
        m = mark(1, "stroke", [line(0, 0, 1920, 1080, 400)], ground_resolved([[]]))
        assert len(m["strokes"][0]) <= C.MARK_STROKE_MAX_POINTS
        assert all(0 <= u <= 1 and 0 <= v <= 1 for u, v in m["strokes"][0])

    def test_a_sketch_is_summarized_as_one_drawing(self):
        text = P.summarize(P.build_payload(road_with_cars_and_trees(), {VIEW: VIEW_DATA}))
        assert "DREW A SKETCH" in text
        assert "18 strokes" in text
        assert "not one object per mark" in text
        assert "placement target" not in text
        assert "Mark 1:" not in text

    def test_a_sketch_that_crosses_an_object_says_so(self):
        marks = road_with_cars_and_trees()
        marks[0] = mark(1, "strike", [line(0, 0, 100, 100)] * 2, object_resolved([[]] * 2))
        text = P.summarize(P.build_payload(marks, {VIEW: VIEW_DATA}))
        assert "`House`" in text


class TestSketchBudget:
    def test_a_sketch_sheds_outlines_before_anything_else(self):
        pl = P.build_payload(road_with_cars_and_trees(), {VIEW: VIEW_DATA})
        full = len(P.serialize(pl, max_bytes=10 ** 7)[0])
        text, notes = P.serialize(pl, max_bytes=full - 1)
        shrunk = json.loads(text)
        assert all(m["region"]["polygon"] == [] for m in shrunk["marks"])
        assert shrunk["sketch"]["stroke_count"] == 18
        assert any("outlines dropped" in n for n in notes)

    def test_then_thins_the_stroke_paths_and_keeps_the_marks(self):
        pl = P.build_payload(road_with_cars_and_trees(), {VIEW: VIEW_DATA})
        text, notes = P.serialize(pl, max_bytes=6000)
        shrunk = json.loads(text)
        assert len(shrunk["marks"]) == 6
        assert all(len(s["world"]) <= 4 for s in shrunk["sketch"]["strokes"])
        assert any("thinned" in n for n in notes)

    def test_resolution_survives_a_sketch_over_budget(self):
        pl = P.build_payload(road_with_cars_and_trees(), {VIEW: VIEW_DATA})
        text, _ = P.serialize(pl, max_bytes=2500)
        shrunk = json.loads(text)
        assert shrunk["marks"][-1]["resolved"]["plane"] == "ground"
        assert shrunk["intent"] == C.INTENT_SKETCH


# =============================================================================
# Blender-facing halves, as source-level contracts
# =============================================================================

MODULE = "src/scripts/mixar/modules/scribble_mark"


def source(rel):
    import pathlib
    return pathlib.Path(rel).read_text()


class TestAnnotatedFrame:
    def test_the_frame_is_drawn_from_the_raw_ink(self):
        """A hull of a sketched car is a blob; the agent was shown blobs."""
        text = source(f"{MODULE}/core/annotate.py")
        body = text[text.index("def _mark_polylines"):]
        assert body.index('mark.get("strokes")') < body.index('region.get("polygon")')

    def test_records_without_strokes_still_draw_their_outline(self):
        text = source(f"{MODULE}/core/annotate.py")
        assert 'region.get("polygon")' in text

    def test_the_frame_is_drawn_from_the_stored_records_not_the_wire_copy(self):
        text = source(f"{MODULE}/core/chat_bridge.py")
        body = text[text.index("def _attach_frames"):]
        assert 'mark_store.draft_marks(scene) or marks' in body


class TestResolverStrokes:
    def test_every_stroke_is_sampled_into_world_space(self):
        text = source(f"{MODULE}/core/resolve.py")
        assert "def _strokes_world" in text
        body = text[text.index("def _strokes_world"):]
        assert "STROKE_WORLD_POINTS" in body
        assert "_ground_hit" in body, "a stroke on nothing lands on the ground"

    def test_the_paths_ride_on_every_kind_of_result(self):
        text = source(f"{MODULE}/core/resolve.py")
        body = text[text.index("def resolve_mark"):text.index("def _object_fractions")]
        assert body.count("_with_strokes(") == 3


class TestVisibleReading:
    """The reading is a mode, and a mode the user cannot see or flip is the
    failure ink tools hit first (arXiv:2607.21468)."""

    def test_the_hint_names_both_readings_and_the_flip(self):
        assert "Tab" in C.MARK_HINT_MARKED and "sketch" in C.MARK_HINT_MARKED
        assert "Tab" in C.MARK_HINT_SKETCH and "Sketch" in C.MARK_HINT_SKETCH
        assert "Esc" in C.MARK_HINT_SKETCH and "Backspace" in C.MARK_HINT_SKETCH

    def test_the_pill_reads_the_cached_reading_not_the_records(self):
        text = source(f"{MODULE}/core/overlay.py")
        body = text[text.index("def _hint_text"):text.index("def _draw_hint")]
        assert "_reading" in body
        assert "json" not in body and "mark_json" not in body

    def test_tab_flips_the_reading_inside_the_freeze(self):
        text = source(f"{MODULE}/ui/operators/mark_draw_ops.py")
        assert '"TAB"' in text
        assert "_flip_reading" in text

    def test_the_reading_is_refreshed_wherever_the_drafts_change(self):
        modal = source(f"{MODULE}/ui/operators/mark_draw_ops.py")
        commit = modal[modal.index("def _commit("):modal.index("def _refreeze_if_resized")]
        assert "refresh_reading" in commit
        undo = modal[modal.index("def _undo_last"):modal.index("def _flip_reading")]
        assert "refresh_reading" in undo
        arm = source(f"{MODULE}/ui/operators/mark_arm_ops.py")
        assert "refresh_reading" in arm

    def test_the_override_is_drawn_beside_the_count_on_both_headers(self):
        for rel in ("src/scripts/mixar/modules/space_mixie_chat/ui/header.py",
                    "src/scripts/mixar/modules/agent_bubble/ui/header.py"):
            assert '"mixar_mark_intent"' in source(rel), rel

    def test_the_override_is_session_only_and_reset_when_the_ink_goes(self):
        props = source(f"{MODULE}/ui/properties/mark_props.py")
        block = props[props.index("mixar_mark_intent = EnumProperty"):]
        assert "SKIP_SAVE" in block[:block.index("update=")]
        assert 'wm.mixar_mark_intent = "AUTO"' in source(f"{MODULE}/core/chat_bridge.py")
        assert 'wm.mixar_mark_intent = "AUTO"' in source(f"{MODULE}/ui/operators/mark_arm_ops.py")
        assert 'wm.mixar_mark_intent = "AUTO"' in source(f"{MODULE}/ui/mark_lifecycle.py")

    def test_the_send_honours_the_override_and_the_budget(self):
        text = source(f"{MODULE}/core/chat_bridge.py")
        body = text[text.index("def prepare_for_send"):text.index("def finish_send")]
        assert "intent_override=mark_store.intent_override(wm)" in body
        assert "payload_mod.serialize(context)" in body


class TestCaps:
    def test_a_drawing_fits_under_the_mark_cap(self):
        """Eight was the cap that refused the second half of the sketch."""
        assert C.MAX_MARKS_PER_TURN >= 24

    def test_a_full_stroke_group_commits_instead_of_dropping_ink(self):
        text = source(f"{MODULE}/ui/operators/mark_draw_ops.py")
        body = text[text.index("def _begin_stroke"):text.index("def _extend_stroke")]
        assert "self._commit(context, region)" in body
        assert "return" not in body.split("MAX_STROKES_PER_MARK")[1].split("\n")[0]
