# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Arranging the moodboard: align, distribute, and tidy into a flow.

Scoped to whatever the user is pointing at: two or more selected items means
those, anything less means the whole board. "The whole board" is everything
placed on the canvas -- reference images, text boxes, inference nodes and 3D
asset nodes alike -- because an arrange is asked for when the canvas as a whole
has become a mess, and an arrange that quietly skipped most of what is on
screen read as a broken feature.

Pure position math over any object exposing ``position_x`` / ``position_y`` /
``width`` / ``height``, so it runs against the fake scene in the tests as
readily as against RNA.
"""

from .moodboard_utils import get_moodboard_image_display_size

# Column and row spacing when tidying, in canvas units. The horizontal gap
# matches what `node_graph.create_connected_action` already leaves between a
# source and the node it spawns, so a tidied graph and a grown one agree.
TIDY_COLUMN_GAP = 220.0
TIDY_ROW_GAP = 90.0

# How tall one tidied column may grow before it wraps into a second stack
# beside it. Unconnected items are all roots and so all land in the first
# column: on a board of reference images that would be a single strip hundreds
# of items tall, which is not a tidy board. Roughly three full-size images.
TIDY_MAX_COLUMN_HEIGHT = 2400.0

# A cycle is already impossible (`node_graph._path_exists` refuses to close
# one), but the depth walk still bounds itself rather than trusting that: a
# corrupt .blend must not hang the UI.
_MAX_DEPTH = 512

ALIGN_EDGES = ('LEFT', 'RIGHT', 'TOP', 'BOTTOM', 'CENTER_X', 'CENTER_Y')


class LayoutItem:
    """One arrangeable thing on the board, in canvas units.

    Media items carry no ``width``/``height`` of their own -- their canvas size
    is the base size times their scale, by the image's aspect -- so every
    target is wrapped in this and the math below sees one shape. Position
    writes through to the wrapped item, which is what actually moves.
    """

    __slots__ = ("item", "node_id", "width", "height")

    def __init__(self, item, width, height, node_id=""):
        self.item = item
        self.width = float(width)
        self.height = float(height)
        self.node_id = node_id or ""

    @property
    def selected(self) -> bool:
        return bool(getattr(self.item, "selected", False))

    @property
    def position_x(self) -> float:
        return float(self.item.position_x)

    @position_x.setter
    def position_x(self, value) -> None:
        self.item.position_x = float(value)

    @property
    def position_y(self) -> float:
        return float(self.item.position_y)

    @position_y.setter
    def position_y(self, value) -> None:
        self.item.position_y = float(value)


def _left(node):
    return float(node.position_x)


def _right(node):
    return float(node.position_x) + float(node.width)


def _bottom(node):
    return float(node.position_y)


def _top(node):
    return float(node.position_y) + float(node.height)


def align_nodes(nodes, edge: str) -> int:
    """Line the items up on one edge. Returns how many moved."""
    nodes = list(nodes)
    if len(nodes) < 2 or edge not in ALIGN_EDGES:
        return 0

    if edge == 'LEFT':
        target = min(_left(n) for n in nodes)
        for node in nodes:
            node.position_x = target
    elif edge == 'RIGHT':
        target = max(_right(n) for n in nodes)
        for node in nodes:
            node.position_x = target - float(node.width)
    elif edge == 'BOTTOM':
        target = min(_bottom(n) for n in nodes)
        for node in nodes:
            node.position_y = target
    elif edge == 'TOP':
        target = max(_top(n) for n in nodes)
        for node in nodes:
            node.position_y = target - float(node.height)
    elif edge == 'CENTER_X':
        # The centre of the SPAN, not the mean of the centres: the mean drifts
        # toward whichever side happens to hold more nodes.
        target = (min(_left(n) for n in nodes) + max(_right(n) for n in nodes)) * 0.5
        for node in nodes:
            node.position_x = target - float(node.width) * 0.5
    else:  # CENTER_Y
        target = (min(_bottom(n) for n in nodes) + max(_top(n) for n in nodes)) * 0.5
        for node in nodes:
            node.position_y = target - float(node.height) * 0.5
    return len(nodes)


def distribute_nodes(nodes, axis: str) -> int:
    """Even the gaps between items along one axis. Returns how many moved.

    The two outermost items stay put and define the span, which is what makes
    the result predictable: distributing twice changes nothing.
    """
    nodes = list(nodes)
    if len(nodes) < 3 or axis not in {'X', 'Y'}:
        return 0

    horizontal = axis == 'X'
    ordered = sorted(nodes, key=_left if horizontal else _bottom)
    size = (lambda n: float(n.width)) if horizontal else (lambda n: float(n.height))
    start = _left(ordered[0]) if horizontal else _bottom(ordered[0])
    end = _right(ordered[-1]) if horizontal else _top(ordered[-1])

    occupied = sum(size(n) for n in ordered)
    gap = (end - start - occupied) / (len(ordered) - 1)
    cursor = start
    for node in ordered:
        if horizontal:
            node.position_x = cursor
        else:
            node.position_y = cursor
        cursor += size(node) + gap
    return len(ordered)


def _incoming_sources(scene, node_ids: set) -> dict:
    """node_id -> the ids inside the set that feed it."""
    sources = {node_id: set() for node_id in node_ids}
    for link in getattr(scene, "mixie_moodboard_links", ()):
        if link.to_node_id in node_ids and link.from_node_id in node_ids:
            sources[link.to_node_id].add(link.from_node_id)
    return sources


def _depths(node_ids: set, sources: dict) -> dict:
    """Longest path from a root, which is what puts a node right of everything
    that feeds it -- shortest path would let a long chain overlap a short one."""
    depth = {}

    def resolve(node_id, guard):
        if node_id in depth:
            return depth[node_id]
        if guard > _MAX_DEPTH:
            return 0
        parents = sources.get(node_id) or ()
        value = 0 if not parents else 1 + max(
            resolve(parent, guard + 1) for parent in parents
        )
        depth[node_id] = value
        return value

    for node_id in node_ids:
        resolve(node_id, 0)
    return depth


def _wrap_column(column: list) -> list:
    """Split one depth column into side-by-side stacks of bounded height.

    A stack always takes at least one item, so an item taller than the budget
    gets its own stack rather than being dropped.
    """
    stacks = []
    current = []
    used = 0.0
    for node in column:
        height = float(node.height)
        if current and used + TIDY_ROW_GAP + height > TIDY_MAX_COLUMN_HEIGHT:
            stacks.append(current)
            current = []
            used = 0.0
        used += height + (TIDY_ROW_GAP if current else 0.0)
        current.append(node)
    if current:
        stacks.append(current)
    return stacks


def tidy_nodes(scene, nodes) -> int:
    """Lay the items out left-to-right in the order the graph flows.

    Columns are graph depth, so a node always sits right of everything feeding
    it. Within a column the current vertical order is kept, so a tidy reads as
    the arrangement the user already had, straightened -- not a reshuffle.
    Items that carry no graph id, and so cannot be fed by anything -- text
    boxes, and media saved before the id migration -- are roots.
    """
    nodes = list(nodes)
    if len(nodes) < 2:
        return 0

    by_id = {node.node_id: node for node in nodes if getattr(node, "node_id", "")}
    depth_by_id = _depths(set(by_id), _incoming_sources(scene, set(by_id)))

    columns = {}
    for node in nodes:
        depth = depth_by_id.get(getattr(node, "node_id", ""), 0)
        columns.setdefault(depth, []).append(node)

    # Anchor on the current top-left so a tidy stays where the user is looking
    # instead of jumping to the origin.
    origin_x = min(_left(n) for n in nodes)
    origin_y = max(_top(n) for n in nodes)

    x = origin_x
    for column_index in sorted(columns):
        column = sorted(columns[column_index], key=_top, reverse=True)
        for stack in _wrap_column(column):
            y = origin_y
            for node in stack:
                node.position_x = x
                node.position_y = y - float(node.height)
                y -= float(node.height) + TIDY_ROW_GAP
            x += max(float(n.width) for n in stack) + TIDY_COLUMN_GAP
    return len(nodes)


def board_items(scene) -> list:
    """Every item an arrange can move, wrapped so they all have a size."""
    items = []

    for media in getattr(scene, "mixie_moodboard_images", ()):
        # Generated media owned by an inference node is drawn INSIDE that
        # node's card rather than at its own position, so moving it moves
        # nothing on screen -- the owning node is the thing to arrange.
        if getattr(media, "embedded_node_id", ""):
            continue
        width, height = get_moodboard_image_display_size(
            getattr(media, "image", None), float(getattr(media, "scale", 1.0))
        )
        items.append(LayoutItem(media, width, height, getattr(media, "node_id", "")))

    for collection in (
        "mixie_moodboard_action_nodes",
        "mixie_moodboard_asset_nodes",
        "mixie_moodboard_textboxes",
    ):
        for node in getattr(scene, collection, ()):
            items.append(
                LayoutItem(
                    node, node.width, node.height, getattr(node, "node_id", "")
                )
            )

    return items


def layout_targets(scene) -> list:
    """The items an arrange acts on: the selection, or the whole board.

    Two or more selected items is an explicit "these"; anything less means the
    user is asking for the board to be tidied, not their one selected card
    moved to nowhere in particular.
    """
    everything = board_items(scene)
    selected = [item for item in everything if item.selected]
    return selected if len(selected) >= 2 else everything
