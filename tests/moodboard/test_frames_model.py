# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Creating, deleting and migrating canvas frames.

Driven with plain stand-ins rather than the ``bpy`` mock: every one of these
rules is about which items end up pointing at which frame, and a MagicMock
collection would accept every write and assert nothing.
"""

import pytest

from mixar.modules.moodboard.constants import (
    FRAME_DEFAULT_HEIGHT,
    FRAME_DEFAULT_WIDTH,
    FRAME_SELECTION_PADDING,
)
from mixar.modules.moodboard.core import frames as frame_core


class _Image:
    """Stand-in for a bpy Image: only its pixel size is ever read."""

    def __init__(self, width=100, height=100):
        self.size = (width, height)


class _Frame:
    def __init__(self):
        self.frame_id = ""
        self.name = "Frame"
        self.position_x = 0.0
        self.position_y = 0.0
        self.width = FRAME_DEFAULT_WIDTH
        self.height = FRAME_DEFAULT_HEIGHT
        self.palette_index = 0
        self.use_custom_color = False
        self.custom_color = (0.0, 0.0, 0.0)
        self.selected = False
        self.locked = False
        self.collapsed = False


class _Collection(list):
    """A bpy collection property: ``add()``, ``remove(index)``, ``clear()``."""

    def __init__(self, factory):
        super().__init__()
        self._factory = factory

    def add(self):
        item = self._factory()
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


class _Media:
    def __init__(self, x=0.0, y=0.0, scale=1.0, image=None, selected=False,
                 embedded_node_id="", frame_id="", group_index=-1):
        self.position_x = x
        self.position_y = y
        self.scale = scale
        self.image = image if image is not None else _Image()
        self.selected = selected
        self.embedded_node_id = embedded_node_id
        self.frame_id = frame_id
        self.group_index = group_index


class _Card:
    """A text box or an inference/asset card: carries its own size."""

    def __init__(self, x=0.0, y=0.0, w=200.0, h=200.0, selected=False, frame_id=""):
        self.position_x = x
        self.position_y = y
        self.width = w
        self.height = h
        self.selected = selected
        self.frame_id = frame_id


class _Scene:
    def __init__(self, media=(), textboxes=(), action_nodes=(), asset_nodes=()):
        self.mixie_moodboard_frames = _Collection(_Frame)
        self.mixie_moodboard_images = list(media)
        self.mixie_moodboard_textboxes = list(textboxes)
        self.mixie_moodboard_action_nodes = list(action_nodes)
        self.mixie_moodboard_asset_nodes = list(asset_nodes)


# --------------------------------------------------------------------------- #
# Creating
# --------------------------------------------------------------------------- #


def test_a_frame_from_a_selection_wraps_it_and_adopts_it():
    media = _Media(x=0.0, y=0.0, selected=True)  # 700x700 at scale 1
    scene = _Scene(media=[media])

    frame = frame_core.create_frame(scene, from_items=[media])

    assert frame.frame_id, "a frame without an id cannot be referred to"
    assert media.frame_id == frame.frame_id
    # Padded on every side, so members are not flush against the border.
    assert frame.position_x == pytest.approx(-FRAME_SELECTION_PADDING)
    assert frame.position_y == pytest.approx(-FRAME_SELECTION_PADDING)
    assert frame.width == pytest.approx(700.0 + 2 * FRAME_SELECTION_PADDING)


def test_a_frame_can_be_created_empty():
    """The whole point of a frame having its own rect: make the container
    first, drop into it afterwards. A bounding box of members could not."""
    scene = _Scene()
    frame = frame_core.create_frame(scene, position=(500.0, 400.0))
    assert frame is not None
    assert frame.width == FRAME_DEFAULT_WIDTH
    assert frame.height == FRAME_DEFAULT_HEIGHT
    # Centred on the point, so it appears where the user asked for it.
    assert frame_core.frame_center(frame) == pytest.approx((500.0, 400.0))


def test_frames_cycle_the_palette_as_they_are_created():
    scene = _Scene()
    indices = [frame_core.create_frame(scene).palette_index for _ in range(3)]
    assert indices == [0, 1, 2]


def test_auto_names_are_unique():
    scene = _Scene()
    names = [frame_core.create_frame(scene).name for _ in range(3)]
    assert names == ["Frame 1", "Frame 2", "Frame 3"]


def test_node_owned_media_is_never_framed():
    """Generated media drawn INSIDE a card has no independent position on the
    canvas, so it can neither be framed nor resolved into one -- the owning
    card is the thing that belongs to a frame."""
    owned = _Media(selected=True, embedded_node_id="node-1")
    scene = _Scene(media=[owned])
    frame = frame_core.create_frame(scene, from_items=[owned], position=(0.0, 0.0))
    assert owned.frame_id == ""
    # Nothing framable, so it fell back to an empty default-sized frame.
    assert frame.width == FRAME_DEFAULT_WIDTH


# --------------------------------------------------------------------------- #
# Membership across every kind
# --------------------------------------------------------------------------- #


def test_a_frame_holds_every_canvas_kind_not_just_pictures():
    """The single biggest gap in the grouping this replaces: its membership
    was an index on the image collection, so a note or a card could never be
    part of a group."""
    picture = _Media(x=100.0, y=100.0, scale=0.2)  # 140x140
    note = _Card(x=300.0, y=100.0, w=100.0, h=100.0)
    card = _Card(x=100.0, y=300.0, w=100.0, h=100.0)
    asset = _Card(x=300.0, y=300.0, w=100.0, h=100.0)
    scene = _Scene(
        media=[picture], textboxes=[note], action_nodes=[card], asset_nodes=[asset]
    )
    frame = frame_core.create_frame(scene, position=(250.0, 250.0))
    frame.position_x, frame.position_y = 0.0, 0.0
    frame.width, frame.height = 600.0, 600.0

    assert frame_core.resolve_membership(scene) == 4
    assert {picture.frame_id, note.frame_id, card.frame_id, asset.frame_id} == {
        frame.frame_id
    }
    assert len(frame_core.frame_members(scene, frame.frame_id)) == 4


def test_add_selection_to_frame_grows_it_to_fit():
    """An explicit override has to survive the next membership pass: if the
    frame did not grow, the adopted item's centre would still be outside it
    and the very next resolve would hand it straight back."""
    inside = _Media(x=0.0, y=0.0, scale=0.1, frame_id="")
    scene = _Scene(media=[inside])
    frame = frame_core.create_frame(scene, position=(0.0, 0.0))
    frame.position_x, frame.position_y = 2000.0, 2000.0
    frame.width, frame.height = 300.0, 300.0
    inside.selected = True

    assert frame_core.add_selection_to_frame(scene, frame.frame_id) == 1
    assert inside.frame_id == frame.frame_id
    # And the resolve that follows leaves it alone.
    assert frame_core.resolve_membership(scene) == 0


def test_dragging_a_member_out_stretches_the_frame_instead_of_orphaning_it():
    """The reported bug: moving an inference card towards the edge of its frame
    left the card outside and un-parented. A frame is a container -- it follows
    what it holds."""
    member = _Media(x=0.0, y=0.0, scale=0.5)  # 350x350
    scene = _Scene(media=[member])
    frame = frame_core.create_frame(scene, from_items=[member])
    right_before = frame.position_x + frame.width

    # Dragged well past the right edge, but still overlapping the frame.
    member.position_x = right_before - 50.0
    assert frame_core.resolve_membership(scene, [member])
    assert member.frame_id == frame.frame_id, "member was orphaned"
    grown_right = frame.position_x + frame.width
    assert grown_right >= member.position_x + 350.0 + FRAME_SELECTION_PADDING


def test_growing_a_frame_never_shrinks_it_and_settles_after_one_pass():
    """Grow-only is what makes this safe to run after EVERY item drag: a frame
    the user deliberately sized larger keeps its size, and a second resolve
    moves nothing."""
    member = _Media(x=0.0, y=0.0, scale=0.5)
    scene = _Scene(media=[member])
    frame = frame_core.create_frame(scene, from_items=[member])
    frame.width, frame.height = 4000.0, 4000.0

    frame_core.resolve_membership(scene, [member])
    assert (frame.width, frame.height) == (4000.0, 4000.0), "user's size was lost"

    # Now push the member out and let the frame grow once; the pass after it
    # must be a no-op, or every drag would keep nudging the rect.
    member.position_x = 3990.0
    frame_core.resolve_membership(scene, [member])
    settled = (frame.position_x, frame.position_y, frame.width, frame.height)
    frame_core.resolve_membership(scene, [member])
    assert (frame.position_x, frame.position_y, frame.width, frame.height) == settled


def test_a_member_dragged_fully_clear_still_leaves():
    """Stickiness is not a trap: there has to be a way out, and it is dragging
    the item off the frame entirely."""
    member = _Media(x=0.0, y=0.0, scale=0.5)
    scene = _Scene(media=[member])
    frame = frame_core.create_frame(scene, from_items=[member])

    member.position_x = frame.position_x + frame.width + 500.0
    assert frame_core.resolve_membership(scene, [member])
    assert member.frame_id == ""


def test_fit_to_contents_is_the_way_to_reshape_a_frame():
    """A frame has no manual resize, so "Fit to Contents" is what shrinks one
    -- and because it wraps exactly its members plus padding, the grow pass
    that follows every drag finds nothing left to do and cannot undo it."""
    member = _Media(x=0.0, y=0.0, scale=0.5)
    scene = _Scene(media=[member])
    frame = frame_core.create_frame(scene, from_items=[member])
    frame.width, frame.height = 5000.0, 5000.0

    assert frame_core.fit_frame_to_members(scene, frame.frame_id)
    fitted = (frame.position_x, frame.position_y, frame.width, frame.height)
    assert frame.width < 5000.0

    frame_core.resolve_membership(scene, [member])
    assert (frame.position_x, frame.position_y, frame.width, frame.height) == fitted


def test_a_collapsed_frame_is_never_grown():
    """A collapsed frame IS its title bar -- nothing below it draws, so
    stretching a rect nobody can see would silently change where it lands when
    the user reopens it."""
    member = _Media(x=0.0, y=0.0, scale=0.5)
    scene = _Scene(media=[member])
    frame = frame_core.create_frame(scene, from_items=[member])
    frame.collapsed = True
    before = (frame.position_x, frame.position_y, frame.width, frame.height)

    member.position_x = frame.position_x + frame.width - 50.0
    frame_core.resolve_membership(scene, [member])
    assert (frame.position_x, frame.position_y, frame.width, frame.height) == before


def test_fit_to_contents_shrinks_as_well_as_grows():
    member = _Media(x=0.0, y=0.0, scale=0.5)  # 350x350, clear of the floors
    scene = _Scene(media=[member])
    frame = frame_core.create_frame(scene, position=(0.0, 0.0))
    member.frame_id = frame.frame_id
    frame.width, frame.height = 5000.0, 5000.0

    assert frame_core.fit_frame_to_members(scene, frame.frame_id) is True
    assert frame.width == pytest.approx(350.0 + 2 * FRAME_SELECTION_PADDING)


def test_fitting_never_takes_a_frame_below_the_floors():
    """A frame smaller than its own name plus its action row is unusable, so a
    tiny member floors the fit rather than producing one."""
    from mixar.modules.moodboard.constants import FRAME_MIN_HEIGHT, FRAME_MIN_WIDTH

    member = _Media(x=0.0, y=0.0, scale=0.02)  # 14x14
    scene = _Scene(media=[member])
    frame = frame_core.create_frame(scene, position=(0.0, 0.0))
    member.frame_id = frame.frame_id

    assert frame_core.fit_frame_to_members(scene, frame.frame_id) is True
    assert frame.width == FRAME_MIN_WIDTH
    assert frame.height == FRAME_MIN_HEIGHT


def test_fitting_an_empty_frame_is_refused_rather_than_collapsing_it():
    scene = _Scene()
    frame = frame_core.create_frame(scene, position=(0.0, 0.0))
    assert frame_core.fit_frame_to_members(scene, frame.frame_id) is False
    assert frame.width == FRAME_DEFAULT_WIDTH


# --------------------------------------------------------------------------- #
# Taking a frame away
# --------------------------------------------------------------------------- #


def test_deleting_a_frame_releases_its_members_where_they_stand():
    """Never deletes what is inside it: Figma deletes the children too, which
    here would mean one keypress destroying a board's references."""
    member = _Media(x=10.0, y=10.0, scale=0.1)
    scene = _Scene(media=[member])
    frame = frame_core.create_frame(scene, from_items=[member])
    frame_id = frame.frame_id

    assert frame_core.delete_frame(scene, frame_id) is True
    assert len(scene.mixie_moodboard_frames) == 0
    assert member.frame_id == ""
    assert member.position_x == 10.0, "the member moved"
    # Idempotent: a second delete is a no-op, not a crash.
    assert frame_core.delete_frame(scene, frame_id) is False


def test_deleting_one_frame_cannot_repoint_another():
    """The whole reason membership is a stable id: the old index-based model
    had to renumber every higher `group_index` by hand, in three separate
    operators, every time a group was removed."""
    a, b = _Media(x=0.0, y=0.0, scale=0.1), _Media(x=1000.0, y=0.0, scale=0.1)
    scene = _Scene(media=[a, b])
    first = frame_core.create_frame(scene, from_items=[a])
    second = frame_core.create_frame(scene, from_items=[b])

    frame_core.delete_frame(scene, first.frame_id)
    assert b.frame_id == second.frame_id
    assert frame_core.frame_by_id(scene, second.frame_id) is second


def test_ungroup_dissolves_both_a_selected_frame_and_a_members_frame():
    member = _Media(x=0.0, y=0.0, scale=0.1)
    other = _Media(x=1000.0, y=0.0, scale=0.1)
    scene = _Scene(media=[member, other])
    by_frame = frame_core.create_frame(scene, from_items=[member])
    by_member = frame_core.create_frame(scene, from_items=[other])

    by_frame.selected = True
    other.selected = True  # its frame is not selected, the item is

    assert frame_core.ungroup_selection(scene) == 2
    assert len(scene.mixie_moodboard_frames) == 0
    assert member.frame_id == "" and other.frame_id == ""
    assert by_member.frame_id  # the record itself is untouched, only removed


def test_select_contents_hands_over_from_the_frame_to_its_members():
    """Leaving the frame selected too would mean the next drag moved the frame
    AND applied its members' own recorded starts."""
    member = _Media(x=0.0, y=0.0, scale=0.1)
    scene = _Scene(media=[member])
    frame = frame_core.create_frame(scene, from_items=[member])
    frame.selected = True

    assert frame_core.select_frame_contents(scene, frame.frame_id) == 1
    assert member.selected is True
    assert frame.selected is False


# --------------------------------------------------------------------------- #
# Migration
# --------------------------------------------------------------------------- #


class _LegacyGroup:
    def __init__(self, name, color=(0.2, 0.6, 1.0, 1.0), visible=True, locked=False):
        self.name = name
        self.color = color
        self.visible = visible
        self.locked = locked
        self.selected = False


def test_a_pre_frame_board_migrates_to_real_frames():
    first = _Media(x=0.0, y=0.0, scale=0.1, group_index=0)
    second = _Media(x=200.0, y=0.0, scale=0.1, group_index=0)
    loose = _Media(x=900.0, y=0.0, scale=0.1, group_index=-1)
    scene = _Scene(media=[first, second, loose])
    scene.mixie_moodboard_groups = _Collection(lambda: _LegacyGroup(""))
    scene.mixie_moodboard_groups.append(_LegacyGroup("Interior refs"))

    assert frame_core.migrate_legacy_groups(scene) == 1
    frame = scene.mixie_moodboard_frames[0]
    assert frame.name == "Interior refs"
    assert first.frame_id == frame.frame_id
    assert second.frame_id == frame.frame_id
    assert loose.frame_id == ""
    # The rect is the members' bounds plus padding -- what the old draw pass
    # derived from scratch on every redraw.
    assert frame.position_x == pytest.approx(-FRAME_SELECTION_PADDING)
    assert frame.width == pytest.approx(270.0 + 2 * FRAME_SELECTION_PADDING)
    # A legacy group's colour came from a free colour picker, so it is almost
    # never one of the palette's pastels: keep what the user chose.
    assert frame.use_custom_color is True
    assert tuple(frame.custom_color) == (0.2, 0.6, 1.0)


def test_migration_is_one_way_and_idempotent():
    member = _Media(x=0.0, y=0.0, scale=0.1, group_index=0)
    scene = _Scene(media=[member])
    scene.mixie_moodboard_groups = _Collection(lambda: _LegacyGroup(""))
    scene.mixie_moodboard_groups.append(_LegacyGroup("Refs"))

    assert frame_core.migrate_legacy_groups(scene) == 1
    # The legacy collection is cleared as it converts, so every later tick
    # (this runs from the poll timer) finds nothing and returns immediately.
    assert len(scene.mixie_moodboard_groups) == 0
    assert member.group_index == -1
    assert frame_core.migrate_legacy_groups(scene) == 0
    assert len(scene.mixie_moodboard_frames) == 1


def test_a_hidden_legacy_group_migrates_to_a_collapsed_frame():
    member = _Media(x=0.0, y=0.0, scale=0.1, group_index=0)
    scene = _Scene(media=[member])
    scene.mixie_moodboard_groups = _Collection(lambda: _LegacyGroup(""))
    scene.mixie_moodboard_groups.append(
        _LegacyGroup("Hidden", visible=False, locked=True)
    )
    frame_core.migrate_legacy_groups(scene)
    frame = scene.mixie_moodboard_frames[0]
    assert frame.collapsed is True
    assert frame.locked is True


def test_a_legacy_group_with_no_surviving_members_is_dropped_not_framed():
    """Its rect WAS its members' bounds, so it drew nothing on the old canvas.

    Converting it anyway parks a default-sized frame at the canvas origin
    that then adopts, through `resolve_membership`, whatever real content
    happens to sit near (0, 0) -- content the user never grouped.
    """
    orphan = _Media(x=0.0, y=0.0, scale=0.1, embedded_node_id="node-1")
    scene = _Scene(media=[orphan])
    scene.mixie_moodboard_groups = _Collection(lambda: _LegacyGroup(""))
    scene.mixie_moodboard_groups.append(_LegacyGroup("Gone"))

    assert frame_core.migrate_legacy_groups(scene) == 0
    assert len(scene.mixie_moodboard_frames) == 0
    # Still one-way: the legacy collection is dropped either way, or the poll
    # tick re-runs this migration forever.
    assert len(scene.mixie_moodboard_groups) == 0


def test_get_or_create_frame_is_named_lookup_then_create():
    scene = _Scene()
    first = frame_core.get_or_create_frame(scene, "Generated")
    again = frame_core.get_or_create_frame(scene, "Generated")
    assert first is again
    assert len(scene.mixie_moodboard_frames) == 1
    assert frame_core.get_or_create_frame(scene, "") is None
