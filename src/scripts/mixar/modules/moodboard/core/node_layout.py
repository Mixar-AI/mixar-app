# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Arranging moodboard nodes: align, distribute, and tidy into a flow.

Deliberately scoped to inference and 3D asset nodes. Reference images and text
boxes are never moved -- the canvas is also a moodboard, and their placement is
composition the user made on purpose. A node's position, by contrast, carries
no meaning beyond legibility, which is exactly what these operations improve.

Pure position math over any object exposing ``position_x`` / ``position_y`` /
``width`` / ``height``, so it runs against the fake scene in the tests as
readily as against RNA.
"""

# Column and row spacing when tidying, in canvas units. The horizontal gap
# matches what `node_graph.create_connected_action` already leaves between a
# source and the node it spawns, so a tidied graph and a grown one agree.
TIDY_COLUMN_GAP = 220.0
TIDY_ROW_GAP = 90.0

# A cycle is already impossible (`node_graph._path_exists` refuses to close
# one), but the depth walk still bounds itself rather than trusting that: a
# corrupt .blend must not hang the UI.
_MAX_DEPTH = 512

ALIGN_EDGES = ('LEFT', 'RIGHT', 'TOP', 'BOTTOM', 'CENTER_X', 'CENTER_Y')


def _left(node):
    return float(node.position_x)


def _right(node):
    return float(node.position_x) + float(node.width)


def _bottom(node):
    return float(node.position_y)


def _top(node):
    return float(node.position_y) + float(node.height)


def align_nodes(nodes, edge: str) -> int:
    """Line the nodes up on one edge. Returns how many moved."""
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
    """Even the gaps between nodes along one axis. Returns how many moved.

    The two outermost nodes stay put and define the span, which is what makes
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


def tidy_nodes(scene, nodes) -> int:
    """Lay the nodes out left-to-right in the order the graph flows.

    Columns are graph depth, so a node always sits right of everything feeding
    it. Within a column the current vertical order is kept, so a tidy reads as
    the arrangement the user already had, straightened -- not a reshuffle.
    """
    nodes = list(nodes)
    if len(nodes) < 2:
        return 0

    by_id = {node.node_id: node for node in nodes if node.node_id}
    if not by_id:
        return 0
    depth = _depths(set(by_id), _incoming_sources(scene, set(by_id)))

    columns = {}
    for node_id, node in by_id.items():
        columns.setdefault(depth.get(node_id, 0), []).append(node)

    # Anchor on the current top-left so a tidy stays where the user is looking
    # instead of jumping to the origin.
    origin_x = min(_left(n) for n in by_id.values())
    origin_y = max(_top(n) for n in by_id.values())

    x = origin_x
    for column_index in sorted(columns):
        column = sorted(columns[column_index], key=_top, reverse=True)
        y = origin_y
        for node in column:
            node.position_x = x
            node.position_y = y - float(node.height)
            y -= float(node.height) + TIDY_ROW_GAP
        x += max(float(n.width) for n in column) + TIDY_COLUMN_GAP
    return len(by_id)


def layout_targets(scene) -> list:
    """The nodes an arrange acts on: the selection, or the whole graph.

    Two or more selected nodes is an explicit "these"; anything less means the
    user is asking for the board to be tidied, not their one selected card
    moved to nowhere in particular.
    """
    everything = [
        node
        for collection in ("mixie_moodboard_action_nodes", "mixie_moodboard_asset_nodes")
        for node in getattr(scene, collection, ())
    ]
    selected = [node for node in everything if node.selected]
    return selected if len(selected) >= 2 else everything
