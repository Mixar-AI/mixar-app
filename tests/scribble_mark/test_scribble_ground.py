# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A mark on empty space lands on the ground, and a stopped turn keeps its marks.

Both came out of one uat7 session: three circles drawn on an empty viewport
as a layout sketch arrived as "background" with no position, the user
pressed Stop, typed "continue", and the retry carried no marks at all. The
objects were built on top of each other at the origin.
"""

import pytest

from mixar.modules.scribble_mark.constants import (
    EMPTY_BACKGROUND,
    GROUND_MAX_DISTANCE,
    PLANE_GROUND,
)
from mixar.modules.scribble_mark.core import marks as mark_store
from mixar.modules.scribble_mark.core.ground import ground_footprint, ray_plane_z


# =============================================================================
# The ray / plane intersection
# =============================================================================

class TestRayPlaneZ:
    def test_looking_straight_down_lands_under_the_eye(self):
        assert ray_plane_z((1.0, 2.0, 5.0), (0.0, 0.0, -1.0)) == (1.0, 2.0, 0.0)

    def test_an_oblique_ray_lands_ahead(self):
        x, y, z = ray_plane_z((0.0, 0.0, 5.0), (1.0, 0.0, -1.0))
        assert (round(x, 6), round(y, 6), z) == (5.0, 0.0, 0.0)

    def test_the_direction_need_not_be_normalized(self):
        assert ray_plane_z((0.0, 0.0, 5.0), (2.0, 0.0, -2.0))[0] == pytest.approx(5.0)

    def test_looking_up_is_sky(self):
        """The plane is behind the eye: nothing was pointed at."""
        assert ray_plane_z((0.0, 0.0, 5.0), (0.0, 0.0, 1.0)) is None

    def test_a_horizontal_ray_never_meets_the_ground(self):
        assert ray_plane_z((0.0, 0.0, 5.0), (1.0, 0.0, 0.0)) is None

    def test_the_horizon_is_not_a_place(self):
        """A near-horizontal ray crosses z=0 kilometres out; reporting that
        would send an object to the horizon."""
        assert ray_plane_z((0.0, 0.0, 5.0), (1.0, 0.0, -0.001)) is None
        assert GROUND_MAX_DISTANCE == 1000.0

    def test_a_custom_plane_height(self):
        assert ray_plane_z((0.0, 0.0, 5.0), (0.0, 0.0, -1.0), z=2.0) == (0.0, 0.0, 2.0)

    def test_an_eye_already_below_the_plane_looking_down_is_nothing(self):
        assert ray_plane_z((0.0, 0.0, -1.0), (0.0, 0.0, -1.0)) is None


class TestGroundFootprint:
    def test_bounds_of_the_hits(self):
        box = ground_footprint([(0.0, 0.0, 0.0), (4.0, 2.0, 0.0), (2.0, -2.0, 0.0)])
        assert box["center"] == [2.0, 0.0, 0.0]
        assert box["size"] == [4.0, 4.0, 0.0]

    def test_nones_are_skipped_and_nothing_is_none(self):
        assert ground_footprint([None, (1.0, 1.0, 0.0)])["size"] == [0.0, 0.0, 0.0]
        assert ground_footprint([]) is None
        assert ground_footprint([None]) is None


# =============================================================================
# The resolver reports a ground mark as a plane hit, never a surface hit
# =============================================================================

class TestResolverContract:
    SOURCE = "src/scripts/mixar/modules/scribble_mark/core/resolve.py"

    def _text(self):
        import pathlib

        return (pathlib.Path(__file__).resolve().parents[2] / self.SOURCE).read_text()

    def test_only_a_background_mark_is_grounded(self):
        """A mark the resolver called too small is not a layout mark."""
        text = self._text()
        body = text[text.index("if not hit:"):text.index("mark_bbox = points_bbox")]
        assert "EMPTY_BACKGROUND" in body
        assert "_ground_fallback" in body

    def test_a_ground_mark_is_not_a_hit(self):
        text = self._text()
        body = text[text.index("def _ground_fallback"):text.index("def _ground_hit")]
        assert '"hit": False' in body
        assert '"plane": PLANE_GROUND' in body
        assert '"objects": []' in body
        assert PLANE_GROUND == "ground" and EMPTY_BACKGROUND == "background"

    def test_sky_stays_background_with_no_position(self):
        text = self._text()
        body = text[text.index("def _ground_fallback"):text.index("def _ground_hit")]
        assert "if anchor_point is None:" in body
        assert "return None" in body


# =============================================================================
# Stop hands the marks back
# =============================================================================

class _Item:
    def __init__(self, serial, state="DRAFT"):
        self.serial = serial
        self.state = state
        self.mark_json = "{}"
        self.view_name = ""


class _Scene:
    def __init__(self, items):
        self.mixar_marks = items


class TestReopenAfterStop:
    def test_stop_returns_the_last_sends_marks_to_draft(self):
        items = [_Item(1), _Item(2), _Item(3, "SENT")]
        scene = _Scene(items)
        mark_store.mark_all_sent(scene)
        assert [i.state for i in items] == ["SENT", "SENT", "SENT"]

        assert mark_store.reopen_last_sent(scene) == 2
        assert [i.state for i in items] == ["DRAFT", "DRAFT", "SENT"], (
            "an earlier turn's marks stay sent"
        )

    def test_a_second_stop_reopens_nothing(self):
        scene = _Scene([_Item(1)])
        mark_store.mark_all_sent(scene)
        mark_store.reopen_last_sent(scene)
        assert mark_store.reopen_last_sent(scene) == 0

    def test_stop_before_any_send_is_a_no_op(self):
        mark_store._last_sent.clear()
        assert mark_store.reopen_last_sent(_Scene([_Item(1, "SENT")])) == 0

    def test_the_abort_operator_reopens_them(self):
        import pathlib

        path = (pathlib.Path(__file__).resolve().parents[2]
                / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/session_ops.py")
        text = path.read_text()
        abort = text[text.index("class MIXIE_CHAT_OT_abort_session"):]
        assert "reopen_last_sent" in abort
        assert abort.index("reopen_last_sent") < abort.index("_send_abort_request_async"), (
            "hand the marks back before the backend hears about the abort"
        )
