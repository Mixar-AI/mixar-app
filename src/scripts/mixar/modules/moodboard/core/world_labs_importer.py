# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Import a generated World Labs world into the Blender scene.

Brings the converted Gaussian-splat PLY (via the bundled KIRI 3DGS Render
addon, which sets up the real-time splat render modifier) and the GLB collider
mesh into a fresh ``WorldLabs_<name>`` collection so it reads as a self-
contained environment/backdrop.

Must run on the main thread (it calls ``bpy.ops``).
"""

import math
import os

import bpy
from mathutils import Matrix, Vector

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# KIRI 3DGS Render v4.1.5 operators (Serpens-generated ids).
#  - import: wm.ply_import + adds the KIRI_3DGS_Render_GN modifier.
#  - proxy:  "Create Proxy From Active" — builds the render proxy so the splats
#            display in colour instead of the green point-cloud preview.
_KIRI_IMPORT_PLY_OP = "sna.dgs_render_import_ply_e0a3a"
_KIRI_PROXY_OP = "sna.dgs_render_create_proxy_from_mesh_d5b41"

# Orientation: the SPZ decoder emits the graphdeco/INRIA 3DGS frame (RDF:
# x-right, y-DOWN, z-forward), so Blender Z-up needs **-90deg X** — the same
# rotation KIRI's own "Rotate for Blender Axes" applies to 3DGS PLYs. The
# original +90 rendered worlds UPSIDE-DOWN (world-up mapped to -Z); the tell
# was that the glTF collider — whose importer is guaranteed upright — only
# voxel-registered onto the splat after an extra Rx180. With -90 the two
# frames coincide directly and ``_align_collider_to_splat`` only needs the
# translation. Validated in-app against a real Marble world (horizon level,
# sky up, F12 render matches the viewport proxy at the same camera).
# Don't add a Z yaw here: none was ever measured.
_SPLAT_ROT_EULER_DEG = (-90.0, 0.0, 0.0)


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

    # 2) Fix the world's ORIENTATION + POSITION first, splat and collider moving
    #    together: reconcile the collider onto the splat (their import frames differ
    #    by Rx180), then ground the whole world (floor -> z=0, centre -> origin).
    _align_collider_to_splat(splat_objs, glb_objs)
    _recenter_world_to_ground(splat_objs, glb_objs)

    # 3) ONLY NOW build the KIRI render proxy, on the splat in its FINAL pose — so
    #    the proxy is created in place and never has to be moved afterwards.
    proxy_objs = _enable_splat_render(splat_objs)

    new_objects = splat_objs + proxy_objs + glb_objs
    _move_to_collection(new_objects, collection)
    _finalize_visibility(splat_objs, glb_objs, proxy_objs)
    _frame_objects(proxy_objs or splat_objs)

    logger.info(
        "[WorldLabs] imported into '%s' (%d splat, %d proxy, %d collider)",
        collection.name, len(splat_objs), len(proxy_objs), len(glb_objs),
    )
    return [o.name for o in new_objects]


def _finalize_visibility(splat_objs: list, glb_objs: list, proxy_objs: list) -> None:
    """Show only the KIRI render proxy after import.

    The proxy renders the Gaussians, so the heavy splat point-cloud mesh and the
    collision mesh are both hidden in the viewport. Both stay in the file and
    remain usable: the collider is still ray-cast for placement (Object.ray_cast
    reads mesh data regardless of viewport visibility) and the splat mesh is only
    eye-hidden (hide_set), so its geometry nodes still evaluate for the proxy.
    Only hide the splat mesh when a proxy actually exists — otherwise keep it
    visible so something shows.
    """
    has_proxy = bool(proxy_objs)
    for obj in glb_objs:  # collider — never shown / rendered
        try:
            obj.hide_render = True
            obj.hide_set(True)
        except Exception:  # noqa: BLE001 - no view layer / context
            pass
    if has_proxy:
        for obj in splat_objs:  # point-cloud source — the proxy renders instead
            try:
                obj.hide_set(True)
            except Exception:  # noqa: BLE001
                pass
    for obj in proxy_objs:  # the proxy is what stays visible
        try:
            obj.hide_set(False)
        except Exception:  # noqa: BLE001
            pass


def _import_tracked(do_import) -> list:
    """Run an import callable and return only the objects it created."""
    before = set(bpy.data.objects.keys())
    do_import()
    return [
        bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before
    ]


def _orient_splats(objects: list) -> None:
    """Apply KIRI's standard RDF-splat -> Blender Z-up rotation to splat roots."""
    euler = tuple(math.radians(d) for d in _SPLAT_ROT_EULER_DEG)
    for obj in objects:
        if obj.parent is None:  # roots only; children inherit the transform
            obj.rotation_euler = euler


def _world_bbox(objects: list):
    """World-space AABB over the objects' bounding boxes → (min, max) or None.

    Empties (the KIRI proxy) have no bound_box and are skipped.
    """
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
    """Translate the COLLIDER so it coincides with the splat room.

    The splat and the GLB collider are the SAME Marble room at the same scale.
    With the splat imported at Rx(-90) (see ``_SPLAT_ROT_EULER_DEG``) both
    frames agree rotationally — the historical Rx180 applied here was
    compensating for the splat itself being imported upside-down (the voxel
    registration that "validated" it was matching the collider onto a flipped
    splat). Only the offset remains: translate so the collider's footprint
    centre + floor match the splat's robust centre + floor. Leave the splat
    fixed; ``_recenter_world_to_ground`` then re-grounds the whole group.
    """
    if not glb_objs or not splat_objs:
        return
    glb_set = set(glb_objs)
    roots = [o for o in glb_objs if o.parent is None or o.parent not in glb_set]
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
        me = getattr(obj, "data", None)
        verts = getattr(me, "vertices", None) if me is not None else None
        if not verts:
            continue
        n = len(verts)
        co = np.empty(n * 3, dtype=np.float32)
        verts.foreach_get("co", co)
        co = co.reshape(n, 3).astype(np.float64)
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


def _recenter_world_to_ground(splat_objs: list, glb_objs: list) -> None:
    """Bring the SPLAT floor onto the X-Y plane with its centre at the origin.

    The visible world is the splat (the gaussians) — so position by the SPLAT, not
    the collider (which may be misaligned / not represent the floor). Compute a
    robust floor (low-percentile Z) + dense-occupancy XY centre over the splat
    points, then shift the whole world (splat + collider) by the same offset so the
    splat floor lands at z=0 and the floor centre at (0, 0, 0). The KIRI proxy is
    created AFTER this, so it isn't part of the group here.
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


def _enable_splat_render(splat_objs: list) -> list:
    """Create KIRI's render proxy so splats display in colour, not as points.

    Returns any objects KIRI created (the proxy Empty). Degrades gracefully: if
    the proxy operator isn't available, the splats stay in point-cloud preview
    and the user can create a proxy manually.
    """
    _ensure_kiri()
    # Render-side setup is independent of the viewport proxy: renders draw the
    # splat via its geometry nodes, which need camera-driven socket updates
    # (see core/splat_render_camera.py) or F12 output is black.
    try:
        from mixar.modules.moodboard.core.splat_render_camera import (
            enable_render_updates,
        )
        enable_render_updates(splat_objs)
    except Exception as e:  # noqa: BLE001
        logger.warning("[WorldLabs] render-update enable failed: %s", e)

    proxy_op = _resolve_op(_KIRI_PROXY_OP)
    if proxy_op is None or not splat_objs:
        if proxy_op is None:
            logger.info("[WorldLabs] KIRI proxy operator unavailable; splats will "
                        "show as a point cloud until a proxy is created")
        return []

    mesh = next((o for o in splat_objs if o.type == "MESH"), splat_objs[0])
    before = set(bpy.data.objects.keys())
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:  # noqa: BLE001
        pass
    try:
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = mesh
        proxy_op()
    except Exception as e:  # noqa: BLE001
        logger.warning("[WorldLabs] KIRI render-proxy creation failed (%s); "
                       "splats will show as a point cloud", e)
        return []
    return [
        bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before
    ]


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


def _ensure_kiri() -> None:
    """Enable the vendored KIRI addon on demand (self-heal).

    The bootstrap normally enables it via a deferred timer, but if that was
    missed (old prefs, startup-order regressions) the import must not quietly
    degrade to a plain point cloud when the addon is sitting in the bundle.
    Session-only enable — prefs persistence stays the bootstrap's job.
    """
    if _resolve_op(_KIRI_IMPORT_PLY_OP) is not None:
        return
    try:
        import addon_utils

        addon_utils.enable("kiri_3dgs_render", default_set=False)
        logger.info("[WorldLabs] enabled KIRI 3DGS Render on demand")
    except Exception as e:  # noqa: BLE001 - addon genuinely absent/broken
        logger.debug("[WorldLabs] on-demand KIRI enable failed: %s", e)


def _import_splat_ply(ply_path: str) -> None:
    """Import the splat via KIRI; fall back to native PLY (mesh-only) on failure."""
    _ensure_kiri()
    kiri_op = _resolve_op(_KIRI_IMPORT_PLY_OP)
    if kiri_op is not None:
        try:
            kiri_op(filepath=ply_path)
            return
        except Exception as e:  # noqa: BLE001 - operator can raise RuntimeError
            logger.warning(
                "[WorldLabs] KIRI splat import failed (%s); falling back to "
                "native PLY import (no splat rendering)", e,
            )
    else:
        logger.warning(
            "[WorldLabs] KIRI 3DGS Render addon not available; importing PLY as "
            "a plain point cloud (no splat rendering)"
        )
    bpy.ops.wm.ply_import(filepath=ply_path)


def _import_collider_glb(glb_path: str) -> None:
    if not os.path.exists(glb_path):
        return
    try:
        bpy.ops.import_scene.gltf(filepath=glb_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("[WorldLabs] collider GLB import failed: %s", e)


def _move_to_collection(objects: list, collection: bpy.types.Collection) -> None:
    for obj in objects:
        for existing in list(obj.users_collection):
            existing.objects.unlink(obj)
        collection.objects.link(obj)


def _frame_objects(objects: list) -> None:
    """Select the imported objects and make the first mesh active."""
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:  # noqa: BLE001 - no object mode / no view layer
        pass
    for obj in objects:
        try:
            obj.select_set(True)
        except Exception:  # noqa: BLE001
            continue
        if obj.type == "MESH":
            bpy.context.view_layer.objects.active = obj


def _resolve_op(idname: str):
    """Return the bpy.ops callable for ``module.operator`` if registered."""
    module, _, op = idname.partition(".")
    group = getattr(bpy.ops, module, None)
    fn = getattr(group, op, None) if group is not None else None
    if fn is None:
        return None
    try:
        # get_rna_type raises if the operator isn't actually registered.
        fn.get_rna_type()
    except Exception:  # noqa: BLE001
        return None
    return fn
