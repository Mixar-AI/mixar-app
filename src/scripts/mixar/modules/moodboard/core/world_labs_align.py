# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Align an imported World Labs splat world to the reconstructed scene.

Scene reconstruction places its object meshes directly in Blender Z-up **metric**
world coordinates. A World Labs world (splat + collider) is imported with its own
origin and "world units" (where ``metric = world_units * metric_scale_factor``).
This module computes a single similarity transform that scales the splat world to
metric and positions it so its floor/footprint wraps the already-placed
reconstruction objects — turning the splat into a backdrop around them.

Only the World Labs world is moved; the reconstruction objects stay put (they are
the placement ground-truth). Yaw is not derivable from World Labs (no camera pose
is exposed), so it defaults to 0 with a manual ``yaw_degrees`` knob.

Must run on the main thread (reads/writes object transforms).

Public API:
    align_world_to_scene(collection_name="", yaw_degrees=0.0) -> dict
"""

import math

import bpy
from mathutils import Matrix, Vector

from mixar.config.logging_config import get_logger

# Reuse the World Labs lookup + bbox helpers rather than duplicating them.
from .world_labs_placement import _find_collider, _hierarchy_bbox, _simple_bbox

logger = get_logger(__name__)


def _is_world_object(obj) -> bool:
    """True if obj belongs to a World Labs world (splat / collider / proxy)."""
    if obj.get("wl_role"):
        return True
    return any(c.name.startswith("WorldLabs_") for c in obj.users_collection)


def _scene_target_meshes() -> list:
    """Placeable meshes that are NOT World Labs world meshes — i.e. the
    reconstruction's placed objects (everything we want the world to wrap)."""
    out = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data is None or not obj.data.vertices:
            continue
        if _is_world_object(obj):
            continue
        out.append(obj)
    return out


def _aabb(objects: list):
    """World-space AABB over the objects' bounding boxes → (min, max) or None."""
    corners = []
    for obj in objects:
        mw = obj.matrix_world
        corners.extend(mw @ Vector(c) for c in obj.bound_box)
    if not corners:
        return None
    mn = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    mx = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return mn, mx


def _world_group(collider, coll):
    """Resolve the set of objects that make up the World Labs world."""
    if coll is None:
        coll = next(
            (c for c in collider.users_collection if c.name.startswith("WorldLabs_")),
            None,
        )
    if coll is not None:
        return list(coll.objects), coll
    # Last resort: every wl_role-tagged object anywhere.
    return [o for o in bpy.data.objects if o.get("wl_role")], None


def align_world_to_scene(collection_name: str = "", yaw_degrees: float = 0.0) -> dict:
    """Scale + position the World Labs world to wrap the reconstructed objects.

    Parameters
    ----------
    collection_name : str, optional
        ``WorldLabs_*`` collection to align; empty auto-detects the latest world.
    yaw_degrees : float, optional
        Z rotation applied to the world (manual knob; World Labs gives no pose).

    Returns
    -------
    dict
        ``{success, collection, collider, scaled, yaw_degrees, ground_delta,
        roots_moved, target_object_count}`` or ``{success: False, error}``.
    """
    collider, coll = _find_collider(collection_name)
    if collider is None:
        return {"success": False, "error": "World Labs collider not found"}

    targets = _scene_target_meshes()
    if not targets:
        return {
            "success": False,
            "error": "no reconstruction meshes found to align the world to",
        }
    tbox = _aabb(targets)
    if tbox is None:
        return {"success": False, "error": "reconstruction meshes have no geometry"}

    group, coll = _world_group(collider, coll)
    if not group:
        return {"success": False, "error": "World Labs world has no objects to move"}

    # Collider (room) footprint centroid at its ground (min Z) in world space.
    cmn, cmx = _hierarchy_bbox(collider) or _simple_bbox(collider)
    pivot_c = Vector(((cmn.x + cmx.x) / 2.0, (cmn.y + cmx.y) / 2.0, cmn.z))

    # Reconstruction footprint centroid at its ground (objects rest on the floor).
    tmn, tmx = tbox
    target_c = Vector(((tmn.x + tmx.x) / 2.0, (tmn.y + tmx.y) / 2.0, tmn.z))

    # World units -> metric: metric = world * metric_scale_factor. (Placement uses
    # the inverse, 1/msf, to bring metric objects into world units.) Fall back to
    # 1.0 if the world didn't report a scale.
    msf = float(collider.get("wl_metric_scale_factor", 0) or 0)
    scale = msf if msf > 1e-6 else 1.0

    # Similarity transform about the collider footprint pivot: scale + yaw, then
    # map the collider footprint/ground onto the reconstruction footprint/ground.
    delta = (
        Matrix.Translation(target_c)
        @ Matrix.Scale(scale, 4)
        @ Matrix.Rotation(math.radians(yaw_degrees), 4, "Z")
        @ Matrix.Translation(-pivot_c)
    )

    # Move only the world's roots (children inherit). A "root" here is any group
    # object whose parent is outside the group.
    group_set = set(group)
    roots = [o for o in group if o.parent is None or o.parent not in group_set]
    for root in roots:
        root.matrix_world = delta @ root.matrix_world

    logger.info(
        "[WorldLabs] aligned world '%s' to %d recon mesh(es): scale=%.4f yaw=%.1f "
        "ground_delta=%.3f",
        coll.name if coll else collider.name, len(targets), scale, yaw_degrees,
        target_c.z - pivot_c.z,
    )
    return {
        "success": True,
        "collection": coll.name if coll else None,
        "collider": collider.name,
        "scaled": round(scale, 6),
        "yaw_degrees": yaw_degrees,
        "ground_delta": round(target_c.z - pivot_c.z, 4),
        "roots_moved": len(roots),
        "target_object_count": len(targets),
    }
