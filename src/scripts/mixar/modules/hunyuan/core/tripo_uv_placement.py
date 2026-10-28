# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Put a Smart UV result back over its source.

Tripo ``/v3/mesh/uv`` returns the mesh centred on the origin and scaled so its
largest dimension is 1 m. Its orientation already matches world space, because
the upload is world-space geometry and Tripo only translates and scales it. So
the client records the source's world bounding box when the job is submitted
(:func:`source_world_bounds`; the union of the boxes for several meshes) and,
once the result is imported, measures the result's ACTUAL world box, scales the
import uniformly so its largest dimension equals the source's, and moves it so
the box centres match (:func:`place_over_source`).

Boxes are measured on the BASE mesh (``obj.data``, modifiers not applied),
because the GLB export sends the base mesh (``export_apply`` stays False). A box
is ``((min_x, min_y, min_z), (max_x, max_y, max_z))`` in world metres: plain
floats, so it can ride in a job's closure without holding Blender data.

The box maths is pure, and the mesh readers take any object exposing
``data.vertices.foreach_get`` and 4x4 matrices, so all of it is testable outside
Blender. Only :func:`place_over_source` touches ``bpy``.
"""

from __future__ import annotations

import math

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Boxes thinner than this (metres) on every axis cannot be fitted.
_MIN_DIMENSION = 1e-9
# Parent links followed when composing a fresh world matrix (cycles are
# impossible in Blender; this bounds a mocked object in tests).
_MAX_PARENT_DEPTH = 64


# ---------------------------------------------------------------------------
# Box maths (pure)
# ---------------------------------------------------------------------------


def union_bounds(boxes):
    """The box enclosing every box in *boxes* (``None`` entries skipped)."""
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        return None
    lo = tuple(min(box[0][i] for box in boxes) for i in range(3))
    hi = tuple(max(box[1][i] for box in boxes) for i in range(3))
    return lo, hi


def box_center(box):
    return tuple((box[0][i] + box[1][i]) * 0.5 for i in range(3))


def box_max_dimension(box):
    return max(box[1][i] - box[0][i] for i in range(3))


def fit_scale_and_offset(source, result):
    """``(scale, offset)`` carrying the *result* box onto the *source* box.

    A point ``p`` of the result maps to ``scale * p + offset``: a uniform scale
    making the result's largest dimension the source's, then the translation
    that puts the result's box centre on the source's. ``None`` when either box
    is missing, degenerate or not finite.
    """
    if source is None or result is None:
        return None
    source_size = box_max_dimension(source)
    result_size = box_max_dimension(result)
    values = (source_size, result_size, *source[0], *source[1],
              *result[0], *result[1])
    if not all(math.isfinite(v) for v in values):
        return None
    if source_size <= _MIN_DIMENSION or result_size <= _MIN_DIMENSION:
        return None
    scale = source_size / result_size
    source_mid = box_center(source)
    result_mid = box_center(result)
    offset = tuple(source_mid[i] - scale * result_mid[i] for i in range(3))
    return scale, offset


def fit_matrix(scale, offset):
    """4x4 rows of ``translate(offset) @ scale(scale)``."""
    s = float(scale)
    ox, oy, oz = (float(v) for v in offset)
    return [
        [s, 0.0, 0.0, ox],
        [0.0, s, 0.0, oy],
        [0.0, 0.0, s, oz],
        [0.0, 0.0, 0.0, 1.0],
    ]


# ---------------------------------------------------------------------------
# Measuring meshes (numpy; no bpy)
# ---------------------------------------------------------------------------


def _as_matrix(matrix):
    import numpy as np

    return np.array([[float(v) for v in row] for row in matrix], dtype=np.float64)


def mesh_world_bounds(objects, matrix_of=None):
    """World box of the BASE meshes of *objects*' MESH entries, or ``None``.

    *matrix_of* returns an object's 4x4 world matrix (default: its
    ``matrix_world``). Objects with no vertices are skipped.
    """
    import numpy as np

    matrix_of = matrix_of or (lambda obj: obj.matrix_world)
    boxes = []
    for obj in objects:
        if getattr(obj, "type", None) != 'MESH':
            continue
        vertices = obj.data.vertices
        count = len(vertices)
        if not count:
            continue
        co = np.empty(count * 3, dtype=np.float64)
        vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        matrix = _as_matrix(matrix_of(obj))
        world = co @ matrix[:3, :3].T + matrix[:3, 3]
        boxes.append((tuple(float(v) for v in world.min(axis=0)),
                      tuple(float(v) for v in world.max(axis=0))))
    return union_bounds(boxes)


def source_world_bounds(objects):
    """The box a Smart UV source occupies, recorded when the job is submitted.

    The source objects have been evaluated by the UI, so their
    ``matrix_world`` is current.
    """
    return mesh_world_bounds(objects)


def fresh_world_matrix(obj):
    """*obj*'s world matrix composed from its own transforms and parents.

    The glTF importer sets local transforms; ``matrix_world`` is refreshed only
    by the next depsgraph evaluation, so right after an import it can be stale.
    Constraints and bone parents are ignored (an import has neither).
    """
    world = _as_matrix(obj.matrix_basis)
    child, parent = obj, obj.parent
    for _ in range(_MAX_PARENT_DEPTH):
        if parent is None:
            break
        world = (_as_matrix(parent.matrix_basis)
                 @ _as_matrix(child.matrix_parent_inverse) @ world)
        child, parent = parent, parent.parent
    return world


# ---------------------------------------------------------------------------
# Applying it (bpy, main thread, right after the import)
# ---------------------------------------------------------------------------


def place_over_source(object_names: str, source_bounds) -> bool:
    """Scale and move the imported objects onto *source_bounds*. True if moved.

    Measures the imported meshes' actual world box and applies the fit to every
    imported root, so a hierarchy moves as one. Best effort: a missing box or a
    failure logs and leaves the import where it landed.
    """
    try:
        import bpy
        from mathutils import Matrix

        names = [name.strip() for name in object_names.split(",") if name.strip()]
        imported = [obj for obj in (bpy.data.objects.get(n) for n in names) if obj]
        result_bounds = mesh_world_bounds(imported, fresh_world_matrix)
        fit = fit_scale_and_offset(source_bounds, result_bounds)
        if fit is None:
            logger.warning(
                "[SmartUV] placement skipped: source box %s, result box %s",
                source_bounds, result_bounds)
            return False
        scale, offset = fit
        transform = Matrix(fit_matrix(scale, offset))
        for root in (obj for obj in imported if obj.parent is None):
            root.matrix_basis = transform @ root.matrix_basis
        logger.info(
            "[SmartUV] result placed over its source: scale %.4f, centre %s",
            scale, tuple(round(v, 4) for v in box_center(source_bounds)))
        return True
    except Exception as e:  # noqa: BLE001 — never lose the import over this
        logger.warning("[SmartUV] placement failed: %s", e, exc_info=True)
        return False
