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


def assign_mesh_reference(node, obj):
    """Bind an existing card without replacing its identity, placement or links."""
    if obj is None or getattr(obj, "type", None) != 'MESH':
        raise ValueError("Select a mesh object from the scene")
    if node.title in ('', 'Add Mesh', node.object_names):
        node.title = obj.name
    node.object_names = obj.name
    node.preview_object = obj
    node.scene_mesh_reference = True
    try:
        obj.asset_generate_preview()
    except (AttributeError, RuntimeError):
        # A preview failure must not invalidate an otherwise usable mesh source.
        pass


def create_empty_mesh_node(scene, *, center=(0.0, 0.0)):
    """Create an unbound scene reference; choosing a mesh is a separate undo step."""
    from .node_graph import deselect_graph_nodes, new_node_id

    node = scene.mixie_moodboard_asset_nodes.add()
    node.node_id = new_node_id()
    node.title = 'Add Mesh'
    node.scene_mesh_reference = True
    node.position_x, node.position_y = find_free_asset_position(
        scene, *center, node.width, node.height, exclude=node,
    )
    deselect_graph_nodes(scene)
    node.selected = True
    scene.mixie_moodboard_active_node_id = node.node_id
    return node


def create_asset_node(scene, obj, *, center=(0.0, 0.0)):
    """Add or reveal one scene mesh reference, preserving its identity and links."""
    if obj is None or getattr(obj, "type", None) != 'MESH':
        raise ValueError("Select a mesh object in Object Mode")

    from .node_graph import deselect_graph_nodes

    existing = next((n for n in scene.mixie_moodboard_asset_nodes
                     if getattr(n, 'preview_object', None) == obj
                     and (getattr(n, 'scene_mesh_reference', False)
                          or n.object_names == obj.name)), None)
    if existing is not None:
        if existing.title == existing.object_names:
            existing.title = obj.name
        existing.object_names = obj.name
        existing.scene_mesh_reference = True
        deselect_graph_nodes(scene)
        existing.selected = True
        scene.mixie_moodboard_active_node_id = existing.node_id
        return existing

    node = create_empty_mesh_node(scene, center=center)
    assign_mesh_reference(node, obj)
    return node


def selected_mesh_objects(context):
    """Object-mode selection in either canvas host, independent of active type."""
    if getattr(context, 'mode', 'OBJECT') != 'OBJECT':
        return []
    return [obj for obj in getattr(context, 'selected_objects', ())
            if getattr(obj, 'type', None) == 'MESH'
            and getattr(obj, 'mode', 'OBJECT') == 'OBJECT']


def add_mesh_references(scene, objects, *, center=(0.0, 0.0), active=None):
    """One card per mesh, one selection for the batch, no scene-object mutation."""
    meshes = []
    for obj in objects:
        if obj is None or getattr(obj, 'type', None) != 'MESH':
            raise ValueError('Select mesh objects in Object Mode')
        if obj not in meshes:
            meshes.append(obj)
    if not meshes:
        raise ValueError('Select mesh objects in Object Mode')
    # Adding a collection entry can relocate its earlier RNA elements. Hold
    # identities during mutation and resolve live entries before selecting them.
    node_ids = [create_asset_node(scene, obj, center=center).node_id for obj in meshes]
    by_id = {node.node_id: node for node in scene.mixie_moodboard_asset_nodes}
    nodes = [by_id[node_id] for node_id in node_ids]
    for node in nodes:
        node.selected = True
    active_index = meshes.index(active) if active in meshes else 0
    scene.mixie_moodboard_active_node_id = nodes[active_index].node_id
    return nodes
