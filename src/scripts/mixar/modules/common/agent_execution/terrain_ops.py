# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded terrain queries before linking/moving scatter objects."""


def raycast_terrain(terrain, origins, *, direction=(0, 0, -1), distance=10000):
    """Cast 1–128 world-space rays against one evaluated terrain snapshot.

    Returns a list of None (miss) or {position, normal, face_index}. The terrain
    may have modifiers and nonsingular nonuniform transforms. No scene edits,
    source copies, persistent BVH caches or worker processes are made. Collect
    all hits before creating/moving instances; send larger batches as steps.
    """
    import math
    import bpy
    from mathutils import Vector

    scene = bpy.context.scene
    if terrain.type != 'MESH' or scene.objects.get(terrain.name) != terrain:
        raise ValueError('Terrain must be a mesh in the current scene')
    rows = list(origins)
    if not 1 <= len(rows) <= 128:
        raise ValueError('Use 1–128 terrain rays per script step')
    rows = [tuple(float(v) for v in row) for row in rows]
    direction = tuple(float(v) for v in direction)
    distance = float(distance)
    if (len(direction) != 3 or any(len(row) != 3 for row in rows)
            or not all(math.isfinite(v) for row in [*rows, direction, (distance,)] for v in row)
            or distance <= 0 or Vector(direction).length == 0):
        raise ValueError('Rays require finite XYZ origins, a nonzero direction and positive distance')
    # Exactly one dependency-graph evaluation; evaluated object raycasts below
    # read the same geometry without triggering an update per placement.
    graph = bpy.context.evaluated_depsgraph_get()
    evaluated = terrain.evaluated_get(graph)
    world = evaluated.matrix_world.copy()
    if abs(world.to_3x3().determinant()) < 1e-20:
        raise ValueError('Terrain transform must be nonsingular')
    inverse = world.inverted()
    local_direction = inverse.to_3x3() @ Vector(direction).normalized()
    local_distance = distance * local_direction.length
    local_direction.normalize()
    normal_matrix = inverse.to_3x3().transposed()
    results = []
    for row in rows:
        hit, point, normal, index = evaluated.ray_cast(
            inverse @ Vector(row), local_direction, distance=local_distance)
        results.append({'position': tuple(world @ point),
                        'normal': tuple((normal_matrix @ normal).normalized()),
                        'face_index': int(index)} if hit else None)
    return results
