# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""World ↔ region projection for mark resolution.

Everything here works against the **live** ``Region`` / ``RegionView3D``, never
against the baked mark camera. That is deliberate: the baked camera exists so
a lane can re-render what the user saw, and reconstructing it from a viewport
involves lens/sensor/ortho-scale conventions that are easy to get subtly
wrong. Resolution must not inherit that risk — if the camera bake is a degree
off, the picture the agent renders is a degree off, but *which object the user
pointed at* is still exactly right.

The per-vertex pass is vectorized through numpy. A dense mesh has hundreds of
thousands of vertices and this runs while the user waits for their message to
send; a Python loop there is seconds of frozen UI.
"""

from __future__ import annotations

from bpy_extras import view3d_utils
from mathutils import Vector

from mixar.config.logging_config import get_logger

from ..constants import RAYCAST_DISTANCE

logger = get_logger(__name__)


# =============================================================================
# Rays
# =============================================================================

def ray_from_region(region, rv3d, point):
    """``(origin, direction)`` of the view ray through a region-pixel point.

    Correct for both perspective and orthographic viewports, which is why the
    resolver uses this rather than a camera frame: an ortho viewport has no
    single eye position, and treating it as if it did splays every ray.
    """
    coord = (float(point[0]), float(point[1]))
    try:
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    except Exception as exc:  # noqa: BLE001 — a bad coord must not kill the send
        logger.debug("Mark ray construction failed at %s: %s", coord, exc)
        return None, None
    if origin is None or direction is None:
        return None, None
    return Vector(origin), Vector(direction).normalized()


def raycast(scene, depsgraph, region, rv3d, point):
    """Cast through a region point. ``(hit, location, normal, object)``.

    The returned object is the ORIGINAL datablock, not the evaluated copy —
    every consumer downstream looks things up by name in ``bpy.data.objects``,
    and an evaluated object's name can differ (and its lifetime is the
    depsgraph's, not ours).
    """
    origin, direction = ray_from_region(region, rv3d, point)
    if origin is None:
        return False, None, None, None
    try:
        ok, location, normal, _index, obj, _matrix = scene.ray_cast(
            depsgraph, origin, direction, distance=RAYCAST_DISTANCE
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Mark raycast failed: %s", exc)
        return False, None, None, None
    if not ok or obj is None:
        return False, None, None, None
    original = obj.original if hasattr(obj, "original") else obj
    return True, Vector(location), Vector(normal), original


# =============================================================================
# World → region
# =============================================================================

def project_point(region, rv3d, world_point):
    """Region-pixel position of a world point, or None when it will not
    project (behind the camera, or degenerate)."""
    try:
        result = view3d_utils.location_3d_to_region_2d(
            region, rv3d, Vector(world_point)
        )
    except Exception:  # noqa: BLE001
        return None
    return (result.x, result.y) if result is not None else None


def project_object_bbox(region, rv3d, obj):
    """Screen bbox of an object's world bounding box, or None.

    Corners that fail to project are DROPPED, never clamped — clamping one
    corner that sits behind the camera drags the box across the frame and
    makes a distant object measure as if it filled the view, which would
    report a mark as covering all of something it barely touched.
    """
    try:
        matrix = obj.matrix_world
        corners = [project_point(region, rv3d, matrix @ Vector(c))
                   for c in obj.bound_box]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Mark bbox projection failed for %s: %s", obj.name, exc)
        return None

    usable = [c for c in corners if c is not None]
    if len(usable) < 2:
        return None
    xs = [c[0] for c in usable]
    ys = [c[1] for c in usable]
    return (min(xs), min(ys), max(xs), max(ys))


# =============================================================================
# World → region, for every vertex at once
# =============================================================================

def project_mesh_vertices(region, rv3d, obj, front_facing_only=True):
    """``(xs, ys, usable)`` numpy arrays for the object's ORIGINAL vertices.

    Original, not evaluated: vertex groups are defined on the base mesh and
    indexed by base vertex, so anything measured against evaluated geometry
    could not be written back.

    ``usable`` is a boolean mask — False for vertices behind the camera and,
    when *front_facing_only*, for vertices whose normal points away from the
    viewer. Front-facing is what makes a mark mean "the wall I can see"
    rather than "this wall and the one behind it".

    Returns ``(None, None, None)`` when the object has no usable mesh or
    numpy is unavailable, so callers degrade to no vertex group rather than
    failing the send.
    """
    try:
        import numpy as np
    except ImportError:  # pragma: no cover — numpy ships with Blender
        logger.debug("Mark vertex projection skipped: numpy unavailable")
        return None, None, None

    mesh = getattr(obj, "data", None)
    vertices = getattr(mesh, "vertices", None)
    count = len(vertices) if vertices is not None else 0
    if not count:
        return None, None, None

    try:
        co = np.empty(count * 3, dtype=np.float64)
        vertices.foreach_get("co", co)
        co = co.reshape(count, 3)

        model = np.array(obj.matrix_world, dtype=np.float64)
        world = co @ model[:3, :3].T + model[:3, 3]

        mvp = np.array(rv3d.perspective_matrix, dtype=np.float64)
        homogeneous = np.empty((count, 4), dtype=np.float64)
        homogeneous[:, :3] = world
        homogeneous[:, 3] = 1.0
        clip = homogeneous @ mvp.T

        w = clip[:, 3]
        # In front of the near plane. A vertex at or behind the eye has no
        # screen position at all, and dividing by its w flips it to the
        # opposite side of the frame.
        usable = w > 1e-9
        safe_w = np.where(usable, w, 1.0)
        ndc_x = clip[:, 0] / safe_w
        ndc_y = clip[:, 1] / safe_w

        xs = (ndc_x * 0.5 + 0.5) * float(region.width)
        ys = (ndc_y * 0.5 + 0.5) * float(region.height)

        if front_facing_only:
            usable &= _front_facing_mask(np, obj, mesh, count, world, rv3d)

        return xs, ys, usable
    except Exception as exc:  # noqa: BLE001 — never fail the send over a group
        logger.debug("Mark vertex projection failed for %s: %s", obj.name, exc)
        return None, None, None


def _front_facing_mask(np, obj, mesh, count, world, rv3d):
    """Vertices whose normal faces the viewer."""
    normals = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("normal", normals)
    normals = normals.reshape(count, 3)

    # Normals transform by the inverse transpose, not the model matrix —
    # under non-uniform scale the model matrix skews them and the
    # front/back test silently inverts on stretched objects.
    normal_matrix = np.array(
        obj.matrix_world.inverted_safe().transposed().to_3x3(), dtype=np.float64
    )
    world_normals = normals @ normal_matrix.T

    if getattr(rv3d, "is_perspective", True):
        eye = np.array(rv3d.view_matrix.inverted_safe().translation, dtype=np.float64)
        view_dirs = world - eye
    else:
        forward = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
        view_dirs = np.array(forward, dtype=np.float64)[None, :]

    return np.einsum("ij,ij->i", world_normals, np.broadcast_to(view_dirs, world.shape)) < 0.0
