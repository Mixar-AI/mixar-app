# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Frame geometry and the membership rule.

Exercised against plain tuples and objects rather than the ``bpy`` mock: this
is rectangle arithmetic and a MagicMock would accept every assignment and
assert nothing (the same reason ``node_layout`` is split this way).
"""

from mixar.modules.moodboard.constants import (
    FRAME_MIN_HEIGHT,
    FRAME_MIN_WIDTH,
    FRAME_PALETTE,
    FRAME_PALETTE_SIZE,
)
from mixar.modules.moodboard.core import frame_geometry as fg


class _Item:
    def __init__(self, frame_id=""):
        self.frame_id = frame_id


# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #


def test_the_palette_is_cycled_so_neighbours_never_share_a_colour():
    """Deterministic cycling, not a random pick.

    A random choice repeats the previous frame's colour about one time in
    eight and cannot be reproduced in a test; cycling guarantees the next
    PALETTE_SIZE frames are all different.
    """
    indices = [fg.next_palette_index(n) for n in range(FRAME_PALETTE_SIZE)]
    assert sorted(indices) == list(range(FRAME_PALETTE_SIZE))
    # And it wraps rather than running off the end.
    assert fg.next_palette_index(FRAME_PALETTE_SIZE) == 0
    assert fg.next_palette_index(FRAME_PALETTE_SIZE + 3) == 3


def test_palette_lookup_wraps_instead_of_raising():
    """A .blend written against a longer palette still resolves to a colour."""
    assert fg.palette_color(FRAME_PALETTE_SIZE) == FRAME_PALETTE[0][1]
    assert fg.palette_color(-1) == FRAME_PALETTE[-1][1]


def test_every_palette_entry_is_a_named_pastel_triple():
    for name, rgb in FRAME_PALETTE:
        assert name and isinstance(name, str)
        assert len(rgb) == 3
        # Pastel: light and unsaturated. On the board's pure-black canvas a
        # dark or fully saturated colour could not carry a translucent wash.
        assert min(rgb) > 0.5, name
        assert max(rgb) - min(rgb) < 0.45, name


# --------------------------------------------------------------------------- #
# Membership
# --------------------------------------------------------------------------- #


def test_membership_is_the_centre_point_not_any_overlap():
    """An item belongs to the frame its CENTRE is in.

    Centre, not "overlaps", so an item straddling a frame's edge has one
    unambiguous answer the user can predict by looking at it.
    """
    frames = [("f1", (0.0, 0.0, 100.0, 100.0))]
    # Centre at (95, 50): inside.
    inside = [(_Item(), (90.0, 40.0, 100.0, 60.0))]
    assert fg.resolve_membership(frames, inside) == [(inside[0][0], "f1")]
    # Centre at (105, 50): outside, even though the rect overlaps the frame.
    outside = [(_Item(), (95.0, 40.0, 115.0, 60.0))]
    assert fg.resolve_membership(frames, outside) == []


def test_the_smallest_containing_frame_wins():
    """Overlapping frames resolve deterministically, innermost first -- the
    same tie-break the C++ hit-test uses, so clicking and containment can
    never disagree about which frame an area belongs to."""
    frames = [
        ("outer", (0.0, 0.0, 200.0, 200.0)),
        ("inner", (50.0, 50.0, 100.0, 100.0)),
    ]
    assert fg.frame_for_point(frames, 75.0, 75.0) == "inner"
    assert fg.frame_for_point(frames, 150.0, 150.0) == "outer"
    assert fg.frame_for_point(frames, 500.0, 500.0) == ""


def test_resolve_membership_reports_only_changes():
    """So a caller can skip writing RNA -- and therefore skip pushing an undo
    step -- when a drag did not cross a frame boundary."""
    frames = [("f1", (0.0, 0.0, 100.0, 100.0))]
    already = _Item(frame_id="f1")
    assert fg.resolve_membership(frames, [(already, (40.0, 40.0, 60.0, 60.0))]) == []
    # Leaving a frame is a change too, back to no frame at all.
    left = _Item(frame_id="f1")
    assert fg.resolve_membership(frames, [(left, (400.0, 400.0, 420.0, 420.0))]) == [
        (left, "")
    ]


def test_a_member_dragged_past_the_edge_stays_a_member():
    """A frame is a container the user put things in, so nudging a picture a
    little past the edge must NOT orphan it -- the frame stretches instead
    (the caller then grows it). An item only leaves by being dragged fully
    clear of the frame."""
    frames = [("f1", (0.0, 0.0, 100.0, 100.0))]
    member = _Item(frame_id="f1")
    # Centre at (105, 50): outside the rect, but the item still overlaps it.
    assert fg.resolve_membership(frames, [(member, (95.0, 40.0, 115.0, 60.0))]) == []
    # Dragged fully clear: now it really has left.
    assert fg.resolve_membership(frames, [(member, (140.0, 40.0, 160.0, 60.0))]) == [
        (member, "")
    ]


def test_landing_inside_another_frame_beats_stickiness():
    """Stickiness must never override a deliberate move. An item whose centre
    lands in a different frame joins that frame even while it still overlaps
    the one it came from."""
    frames = [
        ("f1", (0.0, 0.0, 100.0, 100.0)),
        ("f2", (100.0, 0.0, 200.0, 100.0)),
    ]
    member = _Item(frame_id="f1")
    # Centre at (110, 50): inside f2, still overlapping f1.
    assert fg.resolve_membership(frames, [(member, (90.0, 40.0, 130.0, 60.0))]) == [
        (member, "f2")
    ]


def test_overlap_does_not_count_touching_edges():
    """An item resting exactly against a frame's edge is beside it, not in it,
    so it must not be held by stickiness."""
    assert fg.rects_overlap((0.0, 0.0, 10.0, 10.0), (5.0, 5.0, 15.0, 15.0))
    assert not fg.rects_overlap((0.0, 0.0, 10.0, 10.0), (10.0, 0.0, 20.0, 10.0))
    assert not fg.rects_overlap((0.0, 0.0, 10.0, 10.0), (20.0, 20.0, 30.0, 30.0))


def test_grow_is_grow_only_and_idempotent():
    """Which is what makes it safe to run after every item drag: a frame the
    user sized larger than its contents keeps that size, and a second call
    moves nothing."""
    rect = (0.0, 0.0, 100.0, 100.0)
    # Contained already, with room to spare: nothing to do.
    assert fg.grow_rect_to_contain(rect, [(30.0, 30.0, 50.0, 50.0)], padding=5.0) is None
    # Sticking out on the right: only that edge moves, by the overhang + pad.
    grown = fg.grow_rect_to_contain(rect, [(90.0, 30.0, 130.0, 50.0)], padding=5.0)
    assert grown == (0.0, 0.0, 135.0, 100.0)
    # Running it again on the result is a no-op.
    assert fg.grow_rect_to_contain(grown, [(90.0, 30.0, 130.0, 50.0)], padding=5.0) is None
    # And an empty frame is never resized to nothing.
    assert fg.grow_rect_to_contain(rect, [], padding=5.0) is None


def test_an_id_less_frame_never_claims_anything():
    """A frame without an id cannot be referred to by a member, so it must not
    silently swallow one."""
    assert fg.frame_for_point([("", (0.0, 0.0, 100.0, 100.0))], 50.0, 50.0) == ""


# --------------------------------------------------------------------------- #
# Rects
# --------------------------------------------------------------------------- #


def test_bounds_pad_on_every_side():
    rects = [(0.0, 0.0, 10.0, 10.0), (20.0, 30.0, 40.0, 50.0)]
    assert fg.bounds_of(rects, padding=5.0) == (-5.0, -5.0, 45.0, 55.0)
    assert fg.bounds_of([], padding=5.0) is None


def test_clamp_size_holds_the_floors():
    assert fg.clamp_size(1.0, 1.0) == (FRAME_MIN_WIDTH, FRAME_MIN_HEIGHT)
    assert fg.clamp_size(1000.0, 900.0) == (1000.0, 900.0)


def test_auto_names_skip_the_numbers_already_taken():
    """Ctrl+G names the frame itself and drops into an inline rename; the
    generated name only has to be unambiguous, never asked for."""
    assert fg.unique_frame_name([]) == "Frame 1"
    assert fg.unique_frame_name(["Frame 1", "Frame 2"]) == "Frame 3"
    assert fg.unique_frame_name(["Frame 2"]) == "Frame 1"
