# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Ray candidates from captured meshes only; never traverse unrelated scene geometry."""
from collections import Counter
import time
import bpy
from mathutils import Matrix, Vector
from . import state

MAX_TARGETS = 2048
TIME_BUDGET = 5.0


def intersects(origin, direction, lower, upper, distance):
    near, far = 0.0, distance
    for i in range(3):
        if abs(direction[i]) < 1e-12:
            if origin[i] < lower[i] or origin[i] > upper[i]:
                return False
        else:
            a = (lower[i] - origin[i]) / direction[i]
            b = (upper[i] - origin[i]) / direction[i]
            near, far = max(near, min(a, b)), min(far, max(a, b))
            if near > far:
                return False
    return True


def cast(run, metadata, points):
    ids = metadata['render_ids']
    if len(ids) > MAX_TARGETS:
        state.fail('ray_scope_too_large', 'Use the raster selection or narrow ambiguous candidates to at most 2048 meshes before ray selection.')
    source = state.objects(run)
    graph = bpy.context.evaluated_depsgraph_get()
    targets = []
    for key in ids:
        obj = source[key]
        if not obj.visible_get() or obj.type != 'MESH':
            state.fail('ray_scope_unavailable', 'Captured meshes must be available in the current view layer; use the raster selection otherwise.')
        evaluated = obj.evaluated_get(graph)
        matrix = evaluated.matrix_world.copy()
        try:
            inverse = matrix.inverted()
        except ValueError:
            state.fail('ray_transform_invalid', 'A captured mesh has a singular transform; inspect its geometry separately.')
        corners = evaluated.bound_box
        targets.append((key, evaluated, matrix, inverse,
                        Vector(tuple(min(c[i] for c in corners) for i in range(3))),
                        Vector(tuple(max(c[i] for c in corners) for i in range(3)))))
    frame = metadata['camera']
    transform = Matrix(frame['matrix'])
    tr, br, bl, tl = [Vector(c) for c in frame['corners']]
    direction = (transform.to_quaternion() @ Vector((0, 0, -1))).normalized()
    distance = frame['clip_end'] - frame['clip_start']
    tally, samples = Counter(), 0
    started = time.monotonic()
    for u, v in points:
        if time.monotonic() - started > TIME_BUDGET:
            break
        local = bl.lerp(br, u).lerp(tl.lerp(tr, u), 1-v)
        origin = transform @ Vector((local.x, local.y, -frame['clip_start']))
        nearest, best = distance, None
        complete = True
        for key, obj, matrix, inverse, lower, upper in targets:
            if time.monotonic() - started > TIME_BUDGET:
                complete = False
                break
            local_origin = inverse @ origin
            local_direction = inverse.to_3x3() @ direction
            scale = local_direction.length
            if scale <= 1e-12:
                continue
            local_direction /= scale
            if not intersects(local_origin, local_direction, lower, upper, nearest * scale):
                continue
            hit, location, _, _ = obj.ray_cast(local_origin, local_direction, distance=nearest * scale)
            if hit:
                hit_distance = (matrix @ location - origin).length
                if hit_distance <= nearest:
                    nearest, best = hit_distance, key
        if not complete:
            break  # Never count an incompletely searched ray as the nearest hit.
        samples += 1
        if best is not None:
            tally[best] += 1
    return tally, samples, samples < len(points)
