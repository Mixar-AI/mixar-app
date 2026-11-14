# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Import a generated World Labs world into the Blender scene.

Brings the converted Gaussian-splat PLY (as Blender's built-in splat object,
see ``splat_native``) and the GLB collider mesh into a fresh
``WorldLabs_<name>`` collection so it reads as a self-contained
environment/backdrop.

Must run on the main thread (it calls ``bpy.ops``).
"""

import math
import os

import bpy
from mixar.modules.common.gltf_import import import_gltf
from mathutils import Matrix, Vector

from mixar.config.logging_config import get_logger
from mixar.modules.moodboard.core.splat_lifecycle import (
    finalize_splat_handles,
    note_splats_imported,
)
from mixar.modules.moodboard.core.splat_native import import_splat_ply

logger = get_logger(__name__)

# Orientation of CONVERTED World Labs splats: **+90deg X**, validated against
# a real Marble 1.1 room (2026-08-10: at -90 the furniture hung from the
# ceiling — a full interior is the only unambiguous evidence; outdoor spray
# blobs and the old fixture misled a brief -90 detour). Why +90 and not the
# raw-PLY -90: Marble SPZ stores the INRIA-style RDF frame, and our
# decoder's RUB->RDF step NEGATES Y/Z — so the temp PLY it emits is
# effectively y-UP, and y-up -> Blender z-up is Rx(+90). The -90 applies to
# UNCONVERTED INRIA PLYs (y-down) — that convention lives in
# ``RAW_PLY_ROT_EULER_DEG`` for the local .ply import path. Don't add a Z yaw
# here: none was ever measured. Blender's own ``wm.spz_import`` assumes the
# spec's RUB frame and lands Marble worlds 180deg about X from this, which is
# why SPZ still goes through our converter.
_SPLAT_ROT_EULER_DEG = (90.0, 0.0, 0.0)

# Raw (unconverted) 3DGS PLYs — e.g. a user-supplied INRIA/graphdeco file in
# the local splat import — keep the vendor y-DOWN frame, so they need the
# opposite rotation.
RAW_PLY_ROT_EULER_DEG = (-90.0, 0.0, 0.0)


def import_world_labs_world(
    ply_path: str, glb_path: str = "", name: str = "World", semantics: dict = None,
) -> list:
    """Import the splat PLY (+ optional GLB collider) into a new collection.

    Parameters
    ----------
    ply_path : str
        Path to the 3DGS PLY produced by ``world_labs_spz.spz_to_ply``.
    glb_path : str, optional
        Path to the GLB collider mesh; skipped if empty.
    name : str
        Used for the collection name (``WorldLabs_<name>``).
    semantics : dict, optional
        World Labs ``semantics_metadata`` (``metric_scale_factor``,
        ``ground_plane_offset``). Stored on the collider so the placement step
        can scale objects to world units.

    Returns
    -------
    list[str]
        Names of the objects imported into the scene.
    """
    _ensure_object_mode()
    collection = _new_collection(name)
    # Monotonic sequence so placement can pick the MOST RECENT world.
    collection["wl_seq"] = 1 + max(
        (float(c.get("wl_seq", 0) or 0) for c in bpy.data.collections
         if c.name.startswith("WorldLabs_")),
        default=0,
    )

    # 1) Import the raw geometry: splat point cloud + collider room.
    splat_objs = _import_tracked(lambda: _import_splat_ply(ply_path))
    _orient_splats(splat_objs)

    glb_objs = []
    if glb_path:
        glb_objs = _import_tracked(lambda: _import_collider_glb(glb_path))

    # Tag roles so the placement step can find the collider deterministically.
    for obj in splat_objs:
        obj["wl_role"] = "splat"
    sem = semantics or {}
    for obj in glb_objs:
        obj["wl_role"] = "collider"
        if sem.get("metric_scale_factor"):
            obj["wl_metric_scale_factor"] = float(sem["metric_scale_factor"])
        if sem.get("ground_plane_offset") is not None:
            obj["wl_ground_plane_offset"] = float(sem["ground_plane_offset"])

    # 2) Fix the world's ORIENTATION + POSITION, splat and collider moving
    #    together: reconcile the collider onto the splat (their import frames differ
    #    by Rx180), then ground the whole world (floor -> z=0, centre -> origin).
    _align_collider_to_splat(splat_objs, glb_objs)
    _recenter_world_to_ground(splat_objs, glb_objs)

    new_objects = splat_objs + glb_objs
    _move_to_collection(new_objects, collection)
    _finalize_visibility(glb_objs)
    finalize_splat_handles(collection, splat_objs)
    _frame_objects(splat_objs)

    note_splats_imported()
    logger.info(
        "[WorldLabs] imported into '%s' (%d splat, %d collider)",
        collection.name, len(splat_objs), len(glb_objs),
    )
    return [o.name for o in new_objects]


def _finalize_visibility(glb_objs: list) -> None:
    """Hide the collider; the splat is what the user sees and renders.

    The collider stays in the file and usable: placement still ray-casts it
    (Object.ray_cast reads mesh data regardless of viewport visibility).
    """
    for obj in glb_objs:
        try:
            obj.hide_render = True
            obj.hide_set(True)
        except Exception:  # noqa: BLE001 - no view layer / context
            pass


def _import_tracked(do_import) -> list:
    """Run an import callable and return only the objects it created."""
    before = set(bpy.data.objects.keys())
    do_import()
    return [
        bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before
    ]


def _orient_splats(objects: list, euler_deg: tuple = None) -> None:
    """Rotate splat roots into Blender's Z-up frame.

    Default is the converted-World-Labs rotation (+90 X); the raw-PLY path
    passes ``RAW_PLY_ROT_EULER_DEG``.
    """
    euler = tuple(math.radians(d) for d in (euler_deg or _SPLAT_ROT_EULER_DEG))
    for obj in objects:
        if obj.parent is None:  # roots only; children inherit the transform
            obj.rotation_euler = euler


def _world_bbox(objects: list):
    """World-space AABB over the objects' bounding boxes → (min, max) or None."""
    corners = []
    for obj in objects:
        bb = getattr(obj, "bound_box", None)
        if not bb:
            continue
        mw = obj.matrix_world
        corners.extend(mw @ Vector(c) for c in bb)
    if not corners:
        return None
    mn = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    mx = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return mn, mx


def _align_collider_to_splat(splat_objs: list, glb_objs: list) -> None:
    """Rotate + translate the COLLIDER so it coincides with the splat room.

    The splat and the GLB collider are the SAME Marble room at the same scale,
    but with the splat at Rx(+90) the collider lands 180deg about X from it
    (voxel registration on Marble output: an Rx(180) on the collider matched
    ~81% of its verts onto the dense splat occupancy, vs <47% for every other
    axis-aligned rotation). The splat is the visual the user trusts, so we
    move the COLLIDER onto it: rotate its roots 180deg about X, then translate
    so its footprint centre + floor match the splat's robust centre + floor.
    Leave the splat fixed; ``_recenter_world_to_ground`` re-grounds the group.
    """
    if not glb_objs or not splat_objs:
        return
    glb_set = set(glb_objs)
    roots = [o for o in glb_objs if o.parent is None or o.parent not in glb_set]
    rx180 = Matrix.Rotation(math.pi, 4, "X")
    for root in roots:
        root.matrix_world = rx180 @ root.matrix_world
    # A child mesh's matrix_world is stale until the depsgraph re-evaluates, and we
    # read the collider mesh verts (children) for centring next — force the update.
    try:
        bpy.context.view_layer.update()
    except Exception:  # noqa: BLE001 - no view layer in some contexts
        pass

    # Match collider footprint centre + floor to the splat's (robust median XY +
    # low-percentile Z over each point cloud; bbox fallback if numpy is absent).
    s = _splat_ground_and_center(splat_objs)
    c = _splat_ground_and_center(glb_objs)
    if s is None or c is None:
        s_box = _world_bbox(splat_objs)
        c_box = _world_bbox(glb_objs)
        if s_box is None or c_box is None:
            return
        s = ((s_box[0].x + s_box[1].x) / 2.0, (s_box[0].y + s_box[1].y) / 2.0, s_box[0].z)
        c = ((c_box[0].x + c_box[1].x) / 2.0, (c_box[0].y + c_box[1].y) / 2.0, c_box[0].z)
    offset = Vector((s[0] - c[0], s[1] - c[1], s[2] - c[2]))
    shift = Matrix.Translation(offset)
    for root in roots:
        root.matrix_world = shift @ root.matrix_world
    logger.info("[WorldLabs] aligned collider to splat (Rx180 + offset %.3f, %.3f, %.3f)",
                offset.x, offset.y, offset.z)


def _splat_ground_and_center(splat_objs: list):
    """Robust floor Z + footprint centre over a point cloud (splat OR collider).

    The splat imports with its volumetric centre near the origin (so the room
    floats with half below z=0) AND with a halo of stray "spray" gaussians well
    outside the room, which bias a plain median. So:
      * floor_z = a low percentile of Z (stray points below the floor can't drag
        it down);
      * cx, cy  = the centroid of the DENSE voxels (cells holding at least half the
        mean occupied-cell count) — the room's mass, not the sparse spray. This
        matches the splat<->collider footprints within ~0.3 m (validated by voxel
        registration on the fixture) where a raw median was ~0.5 m off.
    Returns (cx, cy, floor_z) in world space, or None.
    """
    try:
        import numpy as np
    except Exception:  # noqa: BLE001 - numpy missing; caller falls back to bbox
        return None
    chunks = []
    for obj in splat_objs:
        co = _local_points(obj, np)
        if co is None:
            continue
        mw = np.array(obj.matrix_world, dtype=np.float64)
        chunks.append(co @ mw[:3, :3].T + mw[:3, 3])  # local -> world
    if not chunks:
        return None
    W = np.concatenate(chunks, axis=0)
    floor = float(np.percentile(W[:, 2], 2.0))
    # Dense-occupancy XY centre (spray-immune). Cell ~0.15 m.
    cell = 0.15
    q = np.floor(W / cell).astype(np.int64)
    cells, counts = np.unique(q, axis=0, return_counts=True)
    thr = max(2.0, 0.5 * float(counts.mean()))
    keep = cells[counts >= thr]
    if len(keep) == 0:
        return float(np.median(W[:, 0])), float(np.median(W[:, 1])), floor
    cen = keep.mean(axis=0) * cell + cell * 0.5
    return float(cen[0]), float(cen[1]), floor


def _local_points(obj, np):
    """Object-space point positions of a mesh or a point cloud, or None."""
    data = getattr(obj, "data", None)
    if data is None:
        return None
    verts = getattr(data, "vertices", None)
    if verts is not None:
        n = len(verts)
        if not n:
            return None
        co = np.empty(n * 3, dtype=np.float32)
        verts.foreach_get("co", co)
        return co.reshape(n, 3).astype(np.float64)
    attributes = getattr(data, "attributes", None)
    position = attributes.get("position") if attributes is not None else None
    n = len(position.data) if position is not None else 0
    if not n:
        return None
    co = np.empty(n * 3, dtype=np.float32)
    position.data.foreach_get("vector", co)
    return co.reshape(n, 3).astype(np.float64)


def _recenter_world_to_ground(splat_objs: list, glb_objs: list) -> None:
    """Bring the SPLAT floor onto the X-Y plane with its centre at the origin.

    The visible world is the splat (the gaussians) — so position by the SPLAT, not
    the collider (which may be misaligned / not represent the floor). Compute a
    robust floor (low-percentile Z) + dense-occupancy XY centre over the splat
    points, then shift the whole world (splat + collider) by the same offset so the
    splat floor lands at z=0 and the floor centre at (0, 0, 0).
    """
    gc = _splat_ground_and_center(splat_objs)
    if gc is None:  # numpy/verts unavailable — fall back to the splat bbox
        box = _world_bbox(splat_objs or glb_objs)
        if box is None:
            return
        mn, mx = box
        gc = ((mn.x + mx.x) / 2.0, (mn.y + mx.y) / 2.0, mn.z)
    cx, cy, floor = gc
    offset = Vector((-cx, -cy, -floor))
    if offset.length < 1e-7:
        return
    group = splat_objs + glb_objs
    group_set = set(group)
    shift = Matrix.Translation(offset)
    for obj in group:  # roots only; children inherit
        if obj.parent is None or obj.parent not in group_set:
            obj.matrix_world = shift @ obj.matrix_world
    logger.info("[WorldLabs] recentred: splat floor -> z=0, centre -> origin "
                "(offset %.3f, %.3f, %.3f)", offset.x, offset.y, offset.z)


def _ensure_object_mode() -> None:
    """Import operators require OBJECT mode; a job may finish while the user is
    in edit/sculpt/paint mode."""
    obj = bpy.context.view_layer.objects.active if bpy.context.view_layer else None
    if obj is not None and getattr(obj, "mode", "OBJECT") != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:  # noqa: BLE001 - no valid context to switch
            pass


def _new_collection(name: str) -> bpy.types.Collection:
    base = f"WorldLabs_{name}"[:60]
    collection = bpy.data.collections.new(base)
    bpy.context.scene.collection.children.link(collection)
    return collection


def _import_splat_ply(ply_path: str) -> None:
    """Import the splat PLY as Blender's built-in Gaussian splat."""
    import_splat_ply(ply_path)


def _import_collider_glb(glb_path: str) -> None:
    if not os.path.exists(glb_path):
        return
    try:
        import_gltf(filepath=glb_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("[WorldLabs] collider GLB import failed: %s", e)


def _move_to_collection(objects: list, collection: bpy.types.Collection) -> None:
    for obj in objects:
        for existing in list(obj.users_collection):
            existing.objects.unlink(obj)
        collection.objects.link(obj)


def _frame_objects(objects: list) -> None:
    """Select the imported splats and leave the first one active."""
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:  # noqa: BLE001 - no object mode / no view layer
        pass
    active = None
    for obj in objects:
        try:
            obj.select_set(True)
        except Exception:  # noqa: BLE001
            continue
        if active is None:
            active = obj
    if active is not None:
        try:
            bpy.context.view_layer.objects.active = active
        except Exception:  # noqa: BLE001 - object not in the view layer
            pass

