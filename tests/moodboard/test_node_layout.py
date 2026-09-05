# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Align / distribute / tidy for the moodboard canvas.

Exercised against plain objects rather than the bpy mock: this is position
arithmetic, and a MagicMock would accept every assignment and assert nothing.
"""

import pytest

from mixar.modules.moodboard.constants import MOODBOARD_IMAGE_BASE_SIZE
from mixar.modules.moodboard.core import node_layout


class _Node:
    def __init__(self, node_id="", x=0.0, y=0.0, w=100.0, h=100.0, selected=False):
        self.node_id = node_id
        self.position_x = x
        self.position_y = y
        self.width = w
        self.height = h
        self.selected = selected


class _Image:
    """Stand-in for a bpy Image: only its pixel size is ever read."""

    def __init__(self, width=100, height=50):
        self.size = (width, height)


class _Media:
    """A moodboard image item, which has a scale rather than a size."""

    def __init__(self, node_id="", x=0.0, y=0.0, scale=1.0, image=None,
                 selected=False, embedded_node_id=""):
        self.node_id = node_id
        self.position_x = x
        self.position_y = y
        self.scale = scale
        self.image = image if image is not None else _Image()
        self.selected = selected
        self.embedded_node_id = embedded_node_id


class _TextBox:
    def __init__(self, x=0.0, y=0.0, w=200.0, h=80.0, selected=False):
        self.position_x = x
        self.position_y = y
        self.width = w
        self.height = h
        self.selected = selected


class _Link:
    def __init__(self, from_id, to_id):
        self.from_node_id = from_id
        self.to_node_id = to_id


class _Scene:
    def __init__(self, action=(), asset=(), links=(), images=(), textboxes=()):
        self.mixie_moodboard_action_nodes = list(action)
        self.mixie_moodboard_asset_nodes = list(asset)
        self.mixie_moodboard_links = list(links)
        self.mixie_moodboard_images = list(images)
        self.mixie_moodboard_textboxes = list(textboxes)


def _wrapped(scene):
    """``layout_targets`` returns wrappers; compare the items they move."""
    return [target.item for target in node_layout.layout_targets(scene)]


# --------------------------------------------------------------------------- #
# Align
# --------------------------------------------------------------------------- #


def test_align_left_shares_the_leftmost_edge():
    nodes = [_Node(x=10.0), _Node(x=200.0), _Node(x=95.0)]
    assert node_layout.align_nodes(nodes, 'LEFT') == 3
    assert {n.position_x for n in nodes} == {10.0}


def test_align_right_accounts_for_differing_widths():
    """Right edges line up, so the wider node starts further left."""
    narrow = _Node(x=0.0, w=100.0)
    wide = _Node(x=0.0, w=300.0)
    node_layout.align_nodes([narrow, wide], 'RIGHT')
    assert narrow.position_x + narrow.width == pytest.approx(300.0)
    assert wide.position_x + wide.width == pytest.approx(300.0)


def test_centre_uses_the_span_not_the_mean():
    """Averaging the centres drags the result toward whichever side holds more
    nodes; the span's midpoint is stable however they are clustered."""
    nodes = [_Node(x=0.0, w=100.0), _Node(x=10.0, w=100.0), _Node(x=900.0, w=100.0)]
    node_layout.align_nodes(nodes, 'CENTER_X')
    expected = (0.0 + 1000.0) * 0.5
    for node in nodes:
        assert node.position_x + node.width * 0.5 == pytest.approx(expected)


def test_align_needs_two_nodes_and_a_known_edge():
    assert node_layout.align_nodes([_Node()], 'LEFT') == 0
    assert node_layout.align_nodes([_Node(), _Node()], 'SIDEWAYS') == 0


# --------------------------------------------------------------------------- #
# Distribute
# --------------------------------------------------------------------------- #


def test_distribute_evens_the_gaps_and_keeps_the_outer_two():
    a = _Node(x=0.0, w=100.0)
    b = _Node(x=130.0, w=100.0)
    c = _Node(x=600.0, w=100.0)
    assert node_layout.distribute_nodes([a, b, c], 'X') == 3
    assert a.position_x == pytest.approx(0.0)
    assert c.position_x == pytest.approx(600.0)
    assert (b.position_x - (a.position_x + a.width)) == pytest.approx(
        c.position_x - (b.position_x + b.width)
    )


def test_distribute_is_idempotent():
    """Running it twice must not creep, or repeated use drifts the layout."""
    nodes = [_Node(x=0.0), _Node(x=130.0), _Node(x=600.0)]
    node_layout.distribute_nodes(nodes, 'X')
    first = [n.position_x for n in nodes]
    node_layout.distribute_nodes(nodes, 'X')
    assert [n.position_x for n in nodes] == pytest.approx(first)


def test_distribute_needs_three_nodes():
    assert node_layout.distribute_nodes([_Node(), _Node()], 'X') == 0


# --------------------------------------------------------------------------- #
# Tidy
# --------------------------------------------------------------------------- #


def test_tidy_puts_each_node_right_of_what_feeds_it():
    a = _Node("a", x=900.0, y=0.0)
    b = _Node("b", x=0.0, y=0.0)
    c = _Node("c", x=450.0, y=0.0)
    scene = _Scene(action=[a, b, c], links=[_Link("a", "b"), _Link("b", "c")])

    assert node_layout.tidy_nodes(scene, [a, b, c]) == 3
    assert a.position_x < b.position_x < c.position_x


def test_tidy_uses_longest_path_so_chains_do_not_overlap():
    """`a` feeds both `b` and `c`, and `b` also feeds `c`. Shortest path would
    put `c` in the same column as `b`, on top of it."""
    a, b, c = _Node("a"), _Node("b"), _Node("c")
    scene = _Scene(action=[a, b, c],
                   links=[_Link("a", "b"), _Link("a", "c"), _Link("b", "c")])
    node_layout.tidy_nodes(scene, [a, b, c])
    assert b.position_x < c.position_x


def test_tidy_anchors_on_the_current_top_left():
    """It straightens what the user has; it does not teleport them to origin."""
    a = _Node("a", x=5000.0, y=3000.0)
    b = _Node("b", x=5400.0, y=3000.0)
    scene = _Scene(action=[a, b], links=[_Link("a", "b")])
    node_layout.tidy_nodes(scene, [a, b])
    assert min(n.position_x for n in (a, b)) == pytest.approx(5000.0)


def test_tidy_places_items_that_carry_no_graph_id():
    """A text box has no node id at all. Keying the layout by id dropped every
    one of them on the floor -- silently, since nothing raises."""
    node = _Node("a", x=0.0, y=0.0)
    text = _TextBox(x=4000.0, y=4000.0)
    scene = _Scene(action=[node], textboxes=[text], links=[])
    targets = node_layout.layout_targets(scene)

    assert node_layout.tidy_nodes(scene, targets) == 2
    assert text.position_x < 4000.0


def test_tidy_wraps_a_tall_column_instead_of_building_a_tower():
    """Loose items are all roots, so they share column zero. Without a wrap
    a board of reference images tidies into one endless vertical strip."""
    tall = node_layout.TIDY_MAX_COLUMN_HEIGHT
    nodes = [_Node(f"n{i}", y=-i * 10.0, h=tall * 0.4) for i in range(4)]
    scene = _Scene(action=nodes)
    top_before = max(n.position_y + n.height for n in nodes)

    node_layout.tidy_nodes(scene, nodes)
    assert len({n.position_x for n in nodes}) > 1
    # Each stack restarts at the top, so nothing runs off below the anchor.
    for node in nodes:
        assert node.position_y + node.height <= top_before + 1e-6


def test_tidy_ignores_links_that_leave_the_set():
    """Only links inside the arranged set order it; an outside feeder must not
    push a node into a phantom column."""
    a, b = _Node("a"), _Node("b")
    scene = _Scene(action=[a, b], links=[_Link("outside", "a"), _Link("a", "b")])
    node_layout.tidy_nodes(scene, [a, b])
    assert a.position_x < b.position_x


# --------------------------------------------------------------------------- #
# Targets
# --------------------------------------------------------------------------- #


def test_two_or_more_selected_items_scope_the_arrange():
    a = _Node("a", selected=True)
    b = _Node("b", selected=True)
    c = _Node("c")
    scene = _Scene(action=[a, b, c])
    assert _wrapped(scene) == [a, b]


def test_fewer_than_two_selected_means_the_whole_board():
    """One selected node is not an instruction to move that node nowhere."""
    a = _Node("a", selected=True)
    b = _Node("b")
    scene = _Scene(action=[a, b])
    assert _wrapped(scene) == [a, b]


def test_the_whole_board_means_images_and_text_boxes_too():
    """The arrange is asked for when the CANVAS is a mess; one that skipped
    most of what is on screen read as broken."""
    media = _Media("m")
    text = _TextBox()
    action = _Node("a")
    asset = _Node("b")
    scene = _Scene(action=[action], asset=[asset], images=[media], textboxes=[text])
    assert set(map(id, _wrapped(scene))) == {id(media), id(text), id(action), id(asset)}


def test_selection_across_kinds_scopes_the_arrange():
    media = _Media("m", selected=True)
    text = _TextBox(selected=True)
    scene = _Scene(action=[_Node("a")], images=[media], textboxes=[text])
    assert _wrapped(scene) == [media, text]


def test_node_owned_media_is_never_a_target():
    """A generated result is drawn inside its node's card, so moving it moves
    nothing on screen -- the node is the thing to arrange."""
    owned = _Media("m", embedded_node_id="a")
    node = _Node("a")
    scene = _Scene(action=[node], images=[owned])
    assert _wrapped(scene) == [node]


def test_media_is_sized_from_its_image_aspect_not_a_width_property():
    """Media carries a scale, not a size: a wrapper that read a `width` that
    is not there would arrange every image as a zero-width point."""
    media = _Media("m", scale=0.5, image=_Image(1000, 500))
    (target,) = node_layout.board_items(_Scene(images=[media]))
    assert target.width == pytest.approx(MOODBOARD_IMAGE_BASE_SIZE * 0.5)
    assert target.height == pytest.approx(target.width * 0.5)


def test_moving_a_wrapper_moves_the_underlying_item():
    media = _Media("m", x=10.0, y=20.0)
    (target,) = node_layout.board_items(_Scene(images=[media]))
    target.position_x = 300.0
    target.position_y = 400.0
    assert (media.position_x, media.position_y) == (300.0, 400.0)
