# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mark cap bounds MARKS, never ink.

A sketch drawn one line per pause is one mark per line, and the commit
refused every group past ``MAX_MARKS_PER_TURN``: the 33rd line vanished as it
settled, and so did every line after it, so a drawing reached the agent as
its first 32 strokes. The cap is now 128, sized with the sketch block and the
payload budget so a 128-line drawing arrives whole; past it a group JOINS the
newest mark of the live freeze (``marks.join_newest`` → ``payload.extend_mark``),
carries its own world paths into the sketch block, and comes back off one group
per undo (``payload.retract_join``), exactly as the overlay pops it.
"""

import json
import math
import pathlib

import pytest

from mixar.modules.scribble_mark import constants as C
from mixar.modules.scribble_mark.core import marks as mark_store
from mixar.modules.scribble_mark.core import payload as P


REPO = pathlib.Path(__file__).resolve().parents[2]
MODULE = REPO / "src/scripts/mixar/modules/scribble_mark"

W, H = 1920, 1080
VIEW = "mixar_mark_view_0001"


def line(x0, y0, x1, y1, n=10):
    return [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1)]


def reading(strokes):
    flat = [p for s in strokes for p in s]
    return {"gesture": "stroke", "anchor": flat[0], "direction": None,
            "polygon": flat[:8], "closed": False}


def world(strokes, x=0.0):
    return [{"points": [[x + i, 1.0, 0.0] for i in range(4)], "on": "ground"}
            for _ in strokes]


def ground(strokes, x=0.0):
    return {"hit": False, "point": [x, 1.0, 0.0], "objects": [],
            "plane": "ground", "empty_reason": "background",
            "strokes_world": world(strokes, x)}


def nth_line(i):
    """The i-th line of a drawing: short horizontal dashes down the frame."""
    y = 60 + (i % 30) * 30
    x = 100 + (i // 30) * 600
    return [line(x, y, x + 400, y + 5)]


def built(serial=1, strokes=None, resolved="ground"):
    strokes = strokes or nth_line(0)
    res = ground(strokes) if resolved == "ground" else resolved
    return P.build_mark(serial, VIEW, reading(strokes), W, H, res, strokes=strokes)


# --- a Blender-shaped mark collection -----------------------------------------

class _Item:
    def __init__(self):
        self.serial = 0
        self.state = "DRAFT"
        self.gesture = ""
        self.view_name = ""
        self.mark_json = "{}"
        self.view_json = "{}"


class _Collection(list):
    def add(self):
        item = _Item()
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


class _Scene:
    def __init__(self):
        self.mixar_marks = _Collection()
        self.mixar_mark_serial = 0


@pytest.fixture
def quiet(monkeypatch):
    """Nothing a mark owns is live here: no cameras or vertex groups to free."""
    monkeypatch.setattr(mark_store, "view_bake",
                        type("_B", (), {"release": staticmethod(lambda n: None)}))


CAP = 4


@pytest.fixture
def small_cap(quiet, monkeypatch):
    """The join mechanics at a cap of four, independent of the shipped value."""
    monkeypatch.setattr(mark_store, "MAX_MARKS_PER_TURN", CAP)


def draw(scene, lines, view=VIEW, strokes_of=nth_line, resolve=None):
    """Commit each line as its own pause, the way ``_commit`` does."""
    for i in lines:
        strokes = strokes_of(i)
        resolved = (resolve or ground)(strokes, float(i))
        if mark_store.count(scene, drafts_only=True) >= mark_store.MAX_MARKS_PER_TURN:
            assert mark_store.join_newest(scene, view, (W, H), strokes,
                                          resolved["strokes_world"]) is not None
            continue
        serial = mark_store.next_serial(scene)
        assert mark_store.add_mark(scene, serial, view, {"camera": view},
                                   reading(strokes), W, H, resolved,
                                   strokes=strokes) is not None


def stroke_total(scene):
    return sum(len(m.get("strokes") or []) for m in mark_store.draft_marks(scene))


# =============================================================================
# The drawing past the cap
# =============================================================================

class TestInkPastTheCap:
    def test_every_line_past_the_cap_arrives(self, small_cap):
        scene = _Scene()
        draw(scene, range(CAP + 5))
        assert mark_store.count(scene, drafts_only=True) == CAP
        assert stroke_total(scene) == CAP + 5, "the annotated frame draws these"

        payload = mark_store.build_context(scene)
        assert payload["intent"] == C.INTENT_SKETCH
        assert payload["sketch"]["stroke_count"] == CAP + 5
        assert len(payload["sketch"]["strokes"]) == CAP + 5
        assert len(payload["marks"]) == CAP

    def test_joined_lines_keep_their_own_world_paths(self, small_cap):
        scene = _Scene()
        draw(scene, range(CAP + 3))
        strokes = mark_store.build_context(scene)["sketch"]["strokes"]
        starts = [s["world"][0][0] for s in strokes]
        assert starts == [float(i) for i in range(CAP + 3)], (
            "a joined line anchored at another line's place builds it there"
        )

    def test_undo_takes_back_one_group_at_a_time(self, small_cap):
        scene = _Scene()
        extra = 3
        draw(scene, range(CAP + extra))
        for left in range(extra, 0, -1):
            assert mark_store.remove_last(scene) is True
            assert stroke_total(scene) == CAP + left - 1
            assert mark_store.count(scene, drafts_only=True) == CAP

        newest = mark_store.draft_marks(scene)[-1]
        assert "joined" not in newest
        assert newest == built(CAP, nth_line(CAP - 1),
                               ground(nth_line(CAP - 1), float(CAP - 1)))

        assert mark_store.remove_last(scene) is True
        assert mark_store.count(scene, drafts_only=True) == CAP - 1

    def test_only_a_mark_of_the_same_freeze_takes_the_ink(self, small_cap):
        """Strokes are normalized to the frame they were drawn on."""
        scene = _Scene()
        draw(scene, range(CAP))
        before = stroke_total(scene)
        assert mark_store.join_newest(scene, "mixar_mark_view_0002", (W, H),
                                      nth_line(99)) is None
        assert stroke_total(scene) == before

    def test_a_sent_mark_never_takes_new_ink(self, small_cap):
        scene = _Scene()
        draw(scene, range(3))
        mark_store.mark_all_sent(scene)
        assert mark_store.join_newest(scene, VIEW, (W, H), nth_line(9)) is None
        assert [json.loads(i.mark_json).get("joined") for i in scene.mixar_marks] \
            == [None, None, None]


# =============================================================================
# A 128-line drawing, at the shipped limits
# =============================================================================

def wavy(i):
    """A hand-drawn-looking line: 30 samples, enough to fill the outline."""
    x, y = 60 + (i % 16) * 110, 80 + (i // 16) * 110
    return [[(x + k * 6, y + 20 * math.sin(k / 2.5)) for k in range(30)]]


def full_paths(strokes, x):
    return [{"points": [[round(x * 0.3 + k * 0.1234, 4), round(1.2345 + 0.0123 * k, 4), 0.0]
                        for k in range(C.STROKE_WORLD_POINTS)], "on": "ground"}
            for _ in strokes]


def on_ground(strokes, x):
    return {"hit": False, "point": [x * 0.3, 1.2345, 0.0], "normal": [0, 0, 1],
            "objects": [], "sample_count": 576, "hit_count": 0,
            "empty_reason": "background", "plane": "ground", "plane_z": 0.0,
            "world_bbox": {"center": [x * 0.3, 1.2345, 0.0], "size": [1.2345, 0.5432, 0.0]},
            "strokes_world": full_paths(strokes, x)}


def on_floor(strokes, x):
    """Drawn over a floor mesh: every mark hits it and names a vertex group."""
    return {"hit": True, "point": [x * 0.3, 1.2345, 0.0123], "normal": [0.0, 0.0, 1.0],
            "objects": [{"name": "Floor", "coverage": 1.0, "object_fraction": 0.0123,
                         "partial": True, "vertex_group": f"mixar_mark_{int(x):04d}"}],
            "sample_count": 576, "hit_count": 576, "empty_reason": None,
            "world_bbox": {"center": [x * 0.3, 1.2345, 0.0], "size": [1.2345, 0.5432, 0.0]},
            "strokes_world": full_paths(strokes, x)}


class TestAHundredAndTwentyEightLines:
    def test_the_shipped_limits(self):
        assert C.MAX_MARKS_PER_TURN == 128
        assert C.SKETCH_MAX_STROKES >= C.MAX_MARKS_PER_TURN, (
            "a drawing done one line per pause keeps every line anchored"
        )

    @pytest.mark.parametrize("surface", [on_ground, on_floor])
    def test_a_128_line_drawing_arrives_whole(self, quiet, surface):
        scene = _Scene()
        draw(scene, range(128), strokes_of=wavy, resolve=surface)
        assert mark_store.count(scene, drafts_only=True) == 128
        assert "joined" not in mark_store.draft_marks(scene)[-1]

        text, notes = P.serialize(mark_store.build_context(
            scene, intent_override=C.INTENT_SKETCH))  # "Draw to build"
        assert len(text.encode("utf-8")) <= C.MARK_JSON_MAX_BYTES
        sent = json.loads(text)
        assert len(sent["marks"]) == 128, notes
        assert sent["sketch"]["stroke_count"] == 128
        assert len(sent["sketch"]["strokes"]) == 128, notes
        assert all(len(s["world"]) == C.STROKE_WORLD_POINTS
                   for s in sent["sketch"]["strokes"]), (
            f"only the mark outlines may be shed, not the paths: {notes}"
        )

    def test_line_129_joins_instead_of_vanishing(self, quiet):
        scene = _Scene()
        draw(scene, range(130), strokes_of=wavy, resolve=on_ground)
        assert mark_store.count(scene, drafts_only=True) == 128
        assert stroke_total(scene) == 130
        context = mark_store.build_context(scene, intent_override=C.INTENT_SKETCH)
        assert context["sketch"]["stroke_count"] == 130


# =============================================================================
# The pure fold
# =============================================================================

class TestExtendMark:
    def test_the_resolution_is_the_first_groups(self):
        base = built()
        joined = P.extend_mark(base, nth_line(1), W, H, world(nth_line(1), 7.0))
        for key in ("id", "view", "gesture", "closed", "region"):
            assert joined[key] == base[key]
        assert joined["resolved"]["point"] == base["resolved"]["point"]
        assert len(joined["strokes"]) == 2
        assert joined["joined"] == [1]
        assert joined["resolved"]["strokes_world"][1]["points"][0][0] == 7.0
        assert "joined" not in base, "the stored record is not mutated"

    def test_a_gap_in_the_world_paths_is_padded_to_stay_aligned(self):
        base = built(strokes=nth_line(0) + nth_line(1))
        base["resolved"]["strokes_world"] = base["resolved"]["strokes_world"][:1]
        joined = P.extend_mark(base, nth_line(2), W, H, world(nth_line(2), 5.0))
        paths = joined["resolved"]["strokes_world"]
        assert len(paths) == len(joined["strokes"]) == 3
        assert paths[1] == {"points": [], "on": None}
        assert paths[2]["points"][0][0] == 5.0

    def test_unplaced_ink_still_joins(self):
        joined = P.extend_mark(built(), nth_line(1), W, H, None)
        assert len(joined["strokes"]) == 2
        assert joined["resolved"]["strokes_world"][1] == {"points": [], "on": None}

    def test_an_unresolved_mark_does_not_gain_a_measurement(self):
        base = built(resolved=None)
        assert "resolved" not in base
        joined = P.extend_mark(base, nth_line(1), W, H, world(nth_line(1)))
        assert "resolved" not in joined, "absent means 'we did not look'"

    def test_no_ink_is_refused(self):
        with pytest.raises(ValueError):
            P.extend_mark(built(), [[]], W, H)

    def test_retract_is_the_exact_inverse(self):
        base = built()
        once = P.extend_mark(base, nth_line(1), W, H, world(nth_line(1)))
        twice = P.extend_mark(once, nth_line(2) + nth_line(3), W, H,
                              world(nth_line(2) + nth_line(3)))
        assert twice["joined"] == [1, 2]
        assert P.retract_join(twice) == once
        assert P.retract_join(once) == base
        assert P.retract_join(base) is None

    def test_the_bookkeeping_stays_off_the_wire(self):
        joined = P.extend_mark(built(), nth_line(1), W, H, world(nth_line(1)))
        payload = P.build_payload([joined], {VIEW: {}})
        wire = payload["marks"][0]
        assert "joined" not in wire and "strokes" not in wire
        assert wire["stroke_count"] == 2


# =============================================================================
# The modal
# =============================================================================

def test_the_commit_joins_at_the_cap_instead_of_refusing():
    text = (MODULE / "ui/operators/mark_draw_ops.py").read_text()
    body = text[text.index("def _commit(self"):text.index("# -- context")]
    cap = body[body.index(">= MAX_MARKS_PER_TURN"):body.index("rv3d = self._rv3d")]
    assert "resolve.strokes_world(" in cap
    assert "mark_store.join_newest(" in cap
    assert "overlay.push_settled(strokes)" in cap, (
        "the joined group settles as its own group — undo pops exactly it"
    )
    assert "mark_store.refresh_reading(" in cap, "the pill counts the new strokes"
