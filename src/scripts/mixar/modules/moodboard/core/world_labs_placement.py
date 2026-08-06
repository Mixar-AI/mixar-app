# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Place generated objects onto a World Labs environment.

The World Labs import produces a splat (visual) + a GLB collider (geometry) in a
``WorldLabs_*`` collection (objects tagged ``wl_role``). To place a generated
object "in" the world we ray-cast **straight down** at a horizontal position
derived from the object's 2D position in the source image, and rest the object on
whatever collider surface it hits. This is geometry-aware placement without the
World Labs source camera pose (which the API doesn't expose).

Correctness details:
  * Objects imported from a GLB come in as a flat parent+child hierarchy — we
    resolve and move the **root**, and size by the **whole hierarchy's** bbox.
  * Objects are scaled to the world using the World Labs ``metric_scale_factor``
    when available (stored on the collider at import).
  * Already-placed footprints are avoided with a small spiral nudge.
  * The world's own meshes (splat/collider, tagged ``wl_role``) are never moved.

Public API:
    place_objects(placements, collection_name="") -> dict
        placements: [{"object_name": str, "image_x": 0..1, "image_y": 0..1}, ...]
"""

import math

import bpy
from mathutils import Vector

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# image_x → collider X, image_y → collider Y(depth). If a future World Labs frame
# change flips an axis, adjust these signs (validated against the marble-test
# fixture). +1 keeps the mapping; -1 flips that axis.
_AXIS_X_SIGN = 1.0
_AXIS_Y_SIGN = 1.0


# ---------------------------------------------------------------------------
# Collider / collection lookup
# ---------------------------------------------------------------------------

def _find_collider(collection_name: str = ""):
    """Find the World Labs collider mesh (tagged ``wl_role == 'collider'``).

    With no collection_name, prefer the MOST RECENT world (highest ``wl_seq``).
    """
    if collection_name:
        coll = bpy.data.collections.get(collection_name)
        if coll is not None:
            for obj in coll.objects:
                if obj.type == "MESH" and obj.get("wl_role") == "collider":
                    return obj, coll

    best = None
    best_seq = -1.0
    for coll in bpy.data.collections:
        if not coll.name.startswith("WorldLabs_"):
            continue
        seq = float(coll.get("wl_seq", 0) or 0)
        collider = next(
            (o for o in coll.objects if o.type == "MESH" and o.get("wl_role") == "collider"),
            None,
        )
        if collider is not None and seq >= best_seq:
            best, best_seq = (collider, coll), seq
    if best is not None:
        return best
    # Fallback: any collider-tagged mesh anywhere.
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.get("wl_role") == "collider":
            return obj, None
    return None, None


# ---------------------------------------------------------------------------
# Hierarchy helpers
# ---------------------------------------------------------------------------

def _find_root(obj):
    """Walk up parents to the topmost object (the import root)."""
    root = obj
    seen = set()
    while root.parent is not None and root.parent.name not in seen:
        seen.add(root.name)
        root = root.parent
    return root


def _hierarchy_meshes(root):
    """All MESH objects in root's subtree (root + descendants)."""
    out = []
    stack = [root]
    seen = set()
    while stack:
        o = stack.pop()
        if o.name in seen:
            continue
        seen.add(o.name)
        if o.type == "MESH" and o.data and o.data.vertices:
            out.append(o)
        stack.extend(o.children)
    return out


def _hierarchy_bbox(root):
    """World-space AABB over all mesh descendants → (min, max) or None."""
    corners = []
    for o in _hierarchy_meshes(root):
        mw = o.matrix_world
        corners.extend(mw @ Vector(c) for c in o.bound_box)
    if not corners:
        return None
    mn = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    mx = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return mn, mx


def _raycast_down(collider, x: float, y: float, z_top: float, z_bottom: float):
    """Cast straight down at (x, y) and return the FLOOR hit (the LOWEST surface).

    A World Labs room collider is a closed shell, so a ray cast downward from above
    hits the ROOF/ceiling first — resting objects on that puts them on top of the
    room instead of inside on the floor. So we walk through every intersection along
    the ray and keep the lowest one (the floor). Returns the world hit or None.
    """
    mw = collider.matrix_world
    mwi = mw.inverted()
    dir_l = (mwi.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    eps = 1e-3
    cur_z = z_top
    lowest = None
    for _ in range(16):  # cap: handles roof + floor (+ any interior ledges)
        origin_l = mwi @ Vector((x, y, cur_z))
        distance = abs(cur_z - z_bottom) + 2.0
        try:
            hit, loc, _n, _i = collider.ray_cast(origin_l, dir_l, distance=distance)
        except Exception as e:  # noqa: BLE001
            logger.debug("[WorldLabs] ray_cast failed: %s", e)
            break
        if not hit:
            break
        world_hit = mw @ loc
        lowest = world_hit
        next_z = world_hit.z - eps  # step just past this hit to find the next one
        if next_z <= z_bottom:
            break
        cur_z = next_z
    return lowest


def _scale_root(root, factor: float) -> None:
    """Uniformly scale the import root about its own origin."""
    if factor and abs(factor - 1.0) > 1e-4:
        root.scale = root.scale * factor


def _rest_root_at(root, bbox, point: Vector) -> None:
    """Move root so the hierarchy bbox bottom-centre sits at ``point``."""
    mn, mx = bbox
    center_x = (mn.x + mx.x) / 2.0
    center_y = (mn.y + mx.y) / 2.0
    bottom_z = mn.z
    root.matrix_world.translation = root.matrix_world.translation + Vector(
        (point.x - center_x, point.y - center_y, point.z - bottom_z)
    )


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def place_objects(placements, collection_name: str = "") -> dict:
    """Rest each placement's object on the World Labs collider surface."""
    collider, coll = _find_collider(collection_name)
    if collider is None:
        return {"success": False, "error": "World Labs collider not found", "placed": []}

    # Show the collider room: it's the only World Labs geometry that renders in
    # Workbench (splats don't), so the agent needs it visible to verify placement.
    _show_collider(collider)

    # World scale: World Labs metric_scale_factor (stored on the collider at
    # import). Object meshes come at ~metre scale; bring them into world units.
    msf = float(collider.get("wl_metric_scale_factor", 0) or 0)
    obj_scale = (1.0 / msf) if msf > 1e-4 else 1.0

    bmn, bmx = _hierarchy_bbox(collider) or _simple_bbox(collider)
    placed, missed = [], []
    footprints = []  # (x, y, radius) of already-placed objects, for overlap nudge

    for p in placements or []:
        if not isinstance(p, dict) or not p.get("object_name"):
            missed.append({
                "object_name": None,
                "reason": "malformed placement (expected {object_name, image_x, image_y})",
            })
            continue
        name = p["object_name"]
        obj = bpy.data.objects.get(name)
        if obj is None:
            missed.append({"object_name": name, "reason": "object not found in scene"})
            continue
        if obj.get("wl_role"):
            missed.append({"object_name": name, "reason": "is a World Labs world mesh, not a placeable object"})
            continue

        root = _find_root(obj)
        if obj_scale != 1.0:
            _scale_root(root, obj_scale)
        bbox = _hierarchy_bbox(root)
        if bbox is None:
            missed.append({"object_name": name, "reason": "no mesh geometry"})
            continue

        nx = min(max(float(p.get("image_x", 0.5)), 0.0), 1.0)
        ny = min(max(float(p.get("image_y", 0.5)), 0.0), 1.0)
        tx = bmn.x + (bmx.x - bmn.x) * (nx if _AXIS_X_SIGN > 0 else (1.0 - nx))
        ty = bmn.y + (bmx.y - bmn.y) * (ny if _AXIS_Y_SIGN > 0 else (1.0 - ny))

        radius = max((bbox[1].x - bbox[0].x), (bbox[1].y - bbox[0].y)) / 2.0 or 0.1
        tx, ty = _avoid_overlap(tx, ty, radius, footprints, bmn, bmx)

        hit = _raycast_down(collider, tx, ty, bmx.z + 1.0, bmn.z - 1.0)
        if hit is None:
            hit = Vector((tx, ty, bmn.z))  # ground fallback on a miss
        _rest_root_at(root, _hierarchy_bbox(root) or bbox, hit)
        footprints.append((hit.x, hit.y, radius))
        placed.append(root.name)

    logger.info("[WorldLabs] placed %d object(s) on '%s' (%d missed, msf=%.3f)",
                len(placed), collider.name, len(missed), msf)
    return {
        "success": True, "placed": placed, "missed": missed,
        "collider": collider.name,
        "collection": coll.name if coll else None,
    }


def seat_on_floor(object_names, collection_name: str = "") -> dict:
    """Re-seat already-placed objects on the collider floor at their CURRENT XY.

    After the agent nudges objects with ``transform_object`` they can end up
    floating or sunk. This ray-casts straight down from each object's current
    world position onto the collider and rests its bbox bottom-centre on the hit,
    WITHOUT changing its XY — a pure "drop it onto the floor" refinement.
    """
    collider, coll = _find_collider(collection_name)
    if collider is None:
        return {"success": False, "error": "World Labs collider not found", "seated": []}

    _show_collider(collider)
    bmn, bmx = _hierarchy_bbox(collider) or _simple_bbox(collider)
    seated, missed = [], []

    names = object_names or []
    if isinstance(names, str):
        names = [names]

    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            missed.append({"object_name": name, "reason": "object not found in scene"})
            continue
        if obj.get("wl_role"):
            missed.append({"object_name": name, "reason": "is a World Labs world mesh"})
            continue
        root = _find_root(obj)
        bbox = _hierarchy_bbox(root)
        if bbox is None:
            missed.append({"object_name": name, "reason": "no mesh geometry"})
            continue

        cx = (bbox[0].x + bbox[1].x) / 2.0
        cy = (bbox[0].y + bbox[1].y) / 2.0
        hit = _raycast_down(collider, cx, cy, bmx.z + 1.0, bmn.z - 1.0)
        if hit is None:
            hit = Vector((cx, cy, bmn.z))  # ground fallback on a miss
        _rest_root_at(root, bbox, hit)
        seated.append(root.name)

    logger.info("[WorldLabs] seated %d object(s) on '%s' (%d missed)",
                len(seated), collider.name, len(missed))
    return {
        "success": True, "seated": seated, "missed": missed,
        "collider": collider.name,
        "collection": coll.name if coll else None,
    }


def _show_collider(collider) -> None:
    """Make the collider room visible for Workbench verification renders."""
    try:
        from mixar.modules.moodboard.core.world_labs_scene_layout import (
            _set_collider_visible,
        )
        _set_collider_visible(collider, True)
    except Exception as e:  # noqa: BLE001
        logger.debug("[WorldLabs] could not show collider: %s", e)


def _simple_bbox(obj):
    mw = obj.matrix_world
    pts = [mw @ Vector(c) for c in obj.bound_box]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx


def _avoid_overlap(x, y, radius, footprints, bmn, bmx):
    """Spiral-nudge (x, y) until it clears already-placed footprints."""
    def _clear(px, py):
        for fx, fy, fr in footprints:
            if (px - fx) ** 2 + (py - fy) ** 2 < (radius + fr) ** 2:
                return False
        return True

    if _clear(x, y):
        return x, y
    step = max(radius, 0.05)
    for ring in range(1, 12):
        for ang in range(0, 360, 45):
            a = math.radians(ang)
            nx = x + ring * step * math.cos(a)
            ny = y + ring * step * math.sin(a)
            nx = min(max(nx, bmn.x), bmx.x)
            ny = min(max(ny, bmn.y), bmx.y)
            if _clear(nx, ny):
                return nx, ny
    return x, y  # give up — accept overlap rather than fail
