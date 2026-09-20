# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Create standalone 3D asset nodes from Blender scene meshes."""

from __future__ import annotations

from ..constants import MOODBOARD_MAX_PLACEMENT_RING, MOODBOARD_MULTI_IMAGE_GAP
from .node_layout import board_items


def _overlaps(left, bottom, width, height, item, gap) -> bool:
    item_left = float(item.position_x)
    item_bottom = float(item.position_y)
    item_right = item_left + float(item.width)
    item_top = item_bottom + float(item.height)
    return (
        left - gap < item_right
        and left + width + gap > item_left
        and bottom - gap < item_top
        and bottom + height + gap > item_bottom
    )


def find_free_asset_position(
    scene,
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    *,
    exclude=None,
) -> tuple[float, float]:
    """Place a new asset card near the visible canvas centre without stacking."""
    start_x = float(center_x) - float(width) * 0.5
    start_y = float(center_y) - float(height) * 0.5
    exclude_id = str(getattr(exclude, "node_id", "") or "")
    occupied = [
        item
        for item in board_items(scene)
        if item.item is not exclude
        and (not exclude_id or item.node_id != exclude_id)
    ]
    gap = float(MOODBOARD_MULTI_IMAGE_GAP)

    def is_free(x, y):
        return not any(_overlaps(x, y, width, height, item, gap) for item in occupied)

    if is_free(start_x, start_y):
        return start_x, start_y

    step_x = float(width) + gap
    step_y = float(height) + gap
    for ring in range(1, MOODBOARD_MAX_PLACEMENT_RING + 1):
        for dy in range(ring, -ring - 1, -1):
            for dx in range(-ring, ring + 1):
                if max(abs(dx), abs(dy)) != ring:
                    continue
                x = start_x + dx * step_x
                y = start_y + dy * step_y
                if is_free(x, y):
                    return x, y
    return start_x, start_y


def create_asset_node(scene, obj, *, center=(0.0, 0.0)):
    """Create and select a moodboard source node for one scene mesh object."""
    if obj is None or getattr(obj, "type", None) != 'MESH':
        raise ValueError("Select a mesh object in Object Mode")

    from .node_graph import deselect_graph_nodes, new_node_id

    node = scene.mixie_moodboard_asset_nodes.add()
    node.node_id = new_node_id()
    node.title = obj.name
    node.object_names = obj.name
    node.preview_object = obj
    node.position_x, node.position_y = find_free_asset_position(
        scene,
        center[0],
        center[1],
        node.width,
        node.height,
        exclude=node,
    )

    deselect_graph_nodes(scene)
    node.selected = True
    scene.mixie_moodboard_active_node_id = node.node_id

    try:
        obj.asset_generate_preview()
    except (AttributeError, RuntimeError):
        # The card remains a valid mesh source even when Blender cannot build
        # an icon preview for the current object state.
        pass
    return node
