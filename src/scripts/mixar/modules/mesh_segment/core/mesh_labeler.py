# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mesh Labeler Module.

Applies UV island labels to mesh as vertex groups.
"""

import bpy
import bmesh
from typing import Dict, List, Optional, Set, Tuple

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def get_uv_islands(obj: bpy.types.Object) -> Dict[int, Set[int]]:
    """
    Get UV islands from a mesh object.

    Args:
        obj: Blender mesh object

    Returns:
        Dictionary mapping island index to set of vertex indices
    """
    if obj.type != 'MESH':
        return {}

    mesh = obj.data
    if not mesh.uv_layers.active:
        return {}

    # Create bmesh for UV island detection
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    uv_layer = bm.loops.layers.uv.active
    if not uv_layer:
        bm.free()
        return {}

    # Build face adjacency based on shared UV edges
    face_to_island: Dict[int, int] = {}
    island_to_faces: Dict[int, Set[int]] = {}
    current_island = 0

    # Track which faces share UV edges
    uv_edge_to_faces: Dict[Tuple[Tuple[float, float], Tuple[float, float]], List[int]] = {}

    for face in bm.faces:
        for loop in face.loops:
            next_loop = loop.link_loop_next
            uv1 = tuple(round(c, 6) for c in loop[uv_layer].uv)
            uv2 = tuple(round(c, 6) for c in next_loop[uv_layer].uv)
            edge_key = tuple(sorted([uv1, uv2]))
            if edge_key not in uv_edge_to_faces:
                uv_edge_to_faces[edge_key] = []
            uv_edge_to_faces[edge_key].append(face.index)

    # Find connected components (UV islands)
    visited = set()

    def flood_fill(start_face_idx: int, island_idx: int):
        stack = [start_face_idx]
        while stack:
            face_idx = stack.pop()
            if face_idx in visited:
                continue
            visited.add(face_idx)
            face_to_island[face_idx] = island_idx
            if island_idx not in island_to_faces:
                island_to_faces[island_idx] = set()
            island_to_faces[island_idx].add(face_idx)

            # Find adjacent faces via UV edges
            face = bm.faces[face_idx]
            for loop in face.loops:
                next_loop = loop.link_loop_next
                uv1 = tuple(round(c, 6) for c in loop[uv_layer].uv)
                uv2 = tuple(round(c, 6) for c in next_loop[uv_layer].uv)
                edge_key = tuple(sorted([uv1, uv2]))
                if edge_key in uv_edge_to_faces:
                    for adj_face_idx in uv_edge_to_faces[edge_key]:
                        if adj_face_idx not in visited:
                            stack.append(adj_face_idx)

    for face in bm.faces:
        if face.index not in visited:
            flood_fill(face.index, current_island)
            current_island += 1

    # Convert face islands to vertex islands
    island_to_verts: Dict[int, Set[int]] = {}
    for island_idx, face_indices in island_to_faces.items():
        verts = set()
        for face_idx in face_indices:
            face = bm.faces[face_idx]
            for vert in face.verts:
                verts.add(vert.index)
        island_to_verts[island_idx] = verts

    bm.free()
    return island_to_verts


def apply_labels_to_mesh(
    obj: bpy.types.Object,
    island_labels: Dict[str, str],
) -> Tuple[int, List[str]]:
    """
    Apply island labels to mesh as vertex groups.

    Args:
        obj: Blender mesh object
        island_labels: Dictionary mapping island index (as string) to label name

    Returns:
        Tuple of (number of groups created, list of label names)
    """
    if obj.type != 'MESH':
        return 0, []

    # Get UV islands
    uv_islands = get_uv_islands(obj)
    if not uv_islands:
        logger.warning("[Segmentation] No UV islands found in mesh")
        return 0, []

    # Use object name as prefix for vertex groups
    obj_prefix = f"{obj.name}_"

    # Clear existing segmentation vertex groups (those starting with object name prefix)
    groups_to_remove = [vg for vg in obj.vertex_groups if vg.name.startswith(obj_prefix)]
    for vg in groups_to_remove:
        obj.vertex_groups.remove(vg)

    # Create vertex groups for each label
    created_groups = []
    label_to_verts: Dict[str, Set[int]] = {}

    for island_idx_str, label in island_labels.items():
        island_idx = int(island_idx_str)
        if island_idx not in uv_islands:
            logger.warning("[Segmentation] Island %d not found in mesh UV islands", island_idx)
            continue

        verts = uv_islands[island_idx]
        group_name = f"{obj_prefix}{label}"

        if group_name not in label_to_verts:
            label_to_verts[group_name] = set()
        label_to_verts[group_name].update(verts)

    # Create vertex groups and assign vertices
    for group_name, verts in label_to_verts.items():
        if group_name in obj.vertex_groups:
            vg = obj.vertex_groups[group_name]
        else:
            vg = obj.vertex_groups.new(name=group_name)
            created_groups.append(group_name)

        vg.add(list(verts), 1.0, 'REPLACE')

    logger.debug("[Segmentation] Created %d vertex groups", len(created_groups))
    return len(created_groups), created_groups
