# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""World Labs scene layout: recon-box store, placeholders, and mesh snapping.

The final World Labs scene build places Hunyuan objects (generated from per-object
cutouts) inside the splat world using 3D bounding boxes from scene reconstruction.
This module is the client side of that:

  * a per-scene STORE of the extracted recon boxes (label + 3D box, keyed by a
    ``chain_id`` the agent threads through cutout/3D generation),
  * creation of wireframe BOX PLACEHOLDERS seeded into the splat under a single
    ``SceneLayout`` empty (so the agent can fit the whole layout, then nudge),
  * SNAPPING each finished Hunyuan mesh into its box (matched by ``chain_id``).

The boxes come from scene reconstruction with ``generate_mesh=False`` — metric,
Z-up, ground at z=0 (see ``scene_gen_exp_labels_queue``). Placement is only a seed;
the agent verifies/refines by sight (render_viewport + transform_object).
"""

import json
import math
import uuid

import bpy
from mathutils import Matrix, Quaternion, Vector

from mixar.config.logging_config import get_logger

# Reuse the World Labs collider lookup + bbox helpers.
from .world_labs_placement import _find_collider, _hierarchy_bbox, _simple_bbox

logger = get_logger(__name__)

_SCENE_LAYOUT_NAME = "SceneLayout"

# Scene custom property holding the extracted boxes as JSON:
#   {"status": "pending"|"done"|"failed"|"none", "boxes": [...], "error": str}
_STORE_KEY = "mixar_recon_boxes"


# ---------------------------------------------------------------------------
# Box store (written by the labels job callback, read by the agent / placement)
# ---------------------------------------------------------------------------

def _scene():
    return getattr(bpy.context, "scene", None)


def _write(payload: dict) -> None:
    scene = _scene()
    if scene is not None:
        scene[_STORE_KEY] = json.dumps(payload)


def get_labels_store() -> dict:
    """Return the current store ``{status, boxes, error}`` (never raises)."""
    scene = _scene()
    raw = scene.get(_STORE_KEY) if scene is not None else None
    if not raw:
        return {"status": "none", "boxes": []}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"status": "none", "boxes": []}
    except Exception:  # noqa: BLE001
        return {"status": "none", "boxes": []}


def get_recon_boxes() -> list:
    """The stored boxes (empty until extraction finishes)."""
    return get_labels_store().get("boxes", []) or []


def set_labels_pending() -> None:
    """Mark extraction in-flight (call when the labels job is enqueued)."""
    _write({"status": "pending", "boxes": []})


def set_labels_failed(message: str = "") -> None:
    _write({"status": "failed", "error": message or "label extraction failed", "boxes": []})


def store_recon_boxes(objects: list) -> list:
    """Persist the extracted per-object boxes; assign a ``chain_id`` to each.

    Designed as the ``on_objects`` callback for the labels job: it receives the
    raw Phase-2 ``objects`` array (each with ``label`` and the 3D box fields) and
    writes a normalized list to the scene store. Returns the stored boxes.
    """
    boxes = []
    for i, obj in enumerate(objects or []):
        label = str(obj.get("label", "")).strip() or f"object_{i}"
        center = obj.get("center") or [0.0, 0.0, 0.0]
        dims = obj.get("dimensions") or [0.0, 0.0, 0.0]
        rot = obj.get("rotation") or [1.0, 0.0, 0.0, 0.0]
        boxes.append({
            "label": label,
            "chain_id": str(uuid.uuid4()),
            "center": [float(x) for x in center[:3]],
            "dimensions": [float(x) for x in dims[:3]],
            "rotation": [float(x) for x in rot[:4]],
            "scale": float(obj.get("scale", 1.0) or 1.0),
            "bbox_pose_matrix": obj.get("bbox_pose_matrix"),  # 4x4 nested list or None
        })
    _write({"status": "done", "boxes": boxes})
    logger.info("[WorldLabs] stored %d recon box(es)", len(boxes))
    return boxes


def enqueue_label_extraction(image_name: str, min_mask_pixels: int = 6000) -> dict:
    """Fire the labels job for a moodboard image; store boxes when it finishes.

    Resolves ``image_name`` (a ``bpy.data.images`` key), runs scene reconstruction
    in ``generate_mesh=False`` mode via the labels queue, and routes the extracted
    objects into this module's store (``store_recon_boxes``). Async: returns once
    the job is enqueued; poll ``get_labels_store()`` for completion.
    """
    from mixar.modules.common.utils.image_utils import compress_image_for_upload

    from .scene_gen_exp_labels_queue import enqueue_scene_gen_exp_labels_job

    img = bpy.data.images.get(image_name)
    if img is None:
        return {"success": False, "error": f"image '{image_name}' not found"}
    try:
        image_bytes = compress_image_for_upload(img)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"failed to read image: {e}"}

    set_labels_pending()

    def _on_err(*_a, **_k):
        set_labels_failed("label extraction failed")

    job = enqueue_scene_gen_exp_labels_job(
        image_bytes=image_bytes,
        min_mask_pixels=int(min_mask_pixels),
        on_objects=store_recon_boxes,
        on_error=_on_err,
    )
    ok = job is not None
    return {"success": ok, "enqueued": ok,
            "error": "" if ok else "failed to enqueue label extraction"}


# ---------------------------------------------------------------------------
# Box placeholders (seeded into the splat under a single SceneLayout root)
# ---------------------------------------------------------------------------

def _get_or_create_scene_layout(collection) -> "bpy.types.Object":
    """Return the SceneLayout empty (create + link if missing), at identity."""
    obj = bpy.data.objects.get(_SCENE_LAYOUT_NAME)
    if obj is None:
        obj = bpy.data.objects.new(_SCENE_LAYOUT_NAME, None)  # Empty
        obj.empty_display_type = "PLAIN_AXES"
        collection.objects.link(obj)
    obj["wl_scene_layout"] = True
    obj.matrix_world = Matrix.Identity(4)
    return obj


def _make_wire_box(box: dict, collection) -> "bpy.types.Object":
    """Create a unit wireframe cube tagged with the box's chain_id + label."""
    mesh = bpy.data.meshes.new(f"wlbox_{box['label']}")
    # Unit cube (extent 1, centred at origin) — verts at +-0.5.
    v = [(-.5, -.5, -.5), (.5, -.5, -.5), (.5, .5, -.5), (-.5, .5, -.5),
         (-.5, -.5, .5), (.5, -.5, .5), (.5, .5, .5), (-.5, .5, .5)]
    f = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
         (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh.from_pydata(v, [], f)
    mesh.update()
    obj = bpy.data.objects.new(f"wlbox_{box['label']}", mesh)
    obj.display_type = "WIRE"
    obj.show_in_front = True
    obj.hide_render = True
    obj["mixar_chain_id"] = box["chain_id"]
    obj["wl_box"] = True
    obj["wl_label"] = box["label"]
    collection.objects.link(obj)
    return obj


def _clamped_dims(dims):
    """Sanitize SAM3D box dimensions: floor tiny values, cap extreme stretch.

    SAM3D depth is noisy and sometimes blows one axis out (a huge Y), making the
    wireframe boxes look grotesquely stretched. Clamp each axis to a sane minimum
    and to at most ~2.5x the median, so proportions stay roughly right without
    runaway stretch. Boxes are only placement markers (they don't size the
    objects), so this is purely cosmetic.
    """
    d = [max(float(v), 0.05) for v in list(dims)[:3]]
    cap = max(sorted(d)[1] * 2.5, 0.05)  # 2.5x the median axis
    return tuple(min(v, cap) for v in d)


def _apply_box_local_pose(obj, box: dict) -> None:
    """Set the box's LOCAL transform from its recon pose (parent at identity)."""
    obj.location = Vector(box["center"])
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Quaternion(box["rotation"])  # (w, x, y, z)
    obj.scale = _clamped_dims(box["dimensions"])


def _recon_footprint(boxes: list):
    """XY footprint + ground (min bottom-Z) over the recon boxes → (center, diag)."""
    xs, ys, zb = [], [], []
    for b in boxes:
        cx, cy, cz = b["center"]
        dx, dy, dz = b["dimensions"]
        xs += [cx - dx / 2.0, cx + dx / 2.0]
        ys += [cy - dy / 2.0, cy + dy / 2.0]
        zb.append(cz - dz / 2.0)
    center = Vector(((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, min(zb)))
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    return center, diag


def _seed_fit(scene_layout, boxes: list, collider) -> float:
    """Fit the recon layout into the splat collider footprint; return the scale."""
    cmn, cmx = _hierarchy_bbox(collider) or _simple_bbox(collider)
    splat_center = Vector(((cmn.x + cmx.x) / 2.0, (cmn.y + cmx.y) / 2.0, cmn.z))
    splat_diag = math.hypot(cmx.x - cmn.x, cmx.y - cmn.y)

    recon_center, recon_diag = _recon_footprint(boxes)
    scale = (splat_diag / recon_diag) if recon_diag > 1e-4 else 1.0

    scene_layout.matrix_world = (
        Matrix.Translation(splat_center)
        @ Matrix.Scale(scale, 4)
        @ Matrix.Translation(-recon_center)
    )
    return scale


def _set_collider_visible(collider, visible: bool) -> None:
    """Show/hide the collider room mesh in viewport AND render.

    The importer hides the collider (it's the bare room shell behind the splat).
    During placement we SHOW it: it's the only World Labs geometry that renders in
    Workbench (Gaussian splats don't), so it's the room reference the agent places
    against. It's re-hidden at the end to leave the clean splat-only look.
    """
    try:
        collider.hide_set(not visible)
    except Exception:  # noqa: BLE001 - no view layer / context
        pass
    collider.hide_viewport = not visible
    collider.hide_render = not visible


def create_box_placeholders(collection_name: str = "", chain_ids=None) -> dict:
    """Create wireframe box placeholders for the extracted recon boxes.

    Each box is created at its recon pose, parented to a single ``SceneLayout``
    empty, then the whole layout is seed-fitted into the splat collider footprint.
    The collider room mesh is made VISIBLE so the agent can place against it by
    sight. The agent then refines ``SceneLayout`` (and individual boxes).

    ``chain_ids`` (optional): only box these objects. Extraction usually detects
    far more objects than the user is generating models for — pass the chain_ids
    you actually generated cutouts/3D for so the scene isn't littered with empty
    boxes. Omit to box everything that was extracted.
    """
    boxes = get_recon_boxes()
    if not boxes:
        return {"success": False, "error": "no recon boxes — run extract_labels first"}
    if chain_ids:
        wanted = set(chain_ids)
        boxes = [b for b in boxes if b.get("chain_id") in wanted]
        if not boxes:
            return {"success": False,
                    "error": "none of the given chain_ids match the extracted boxes"}
    collider, coll = _find_collider(collection_name)
    if collider is None:
        return {"success": False, "error": "World Labs collider not found"}

    layout_coll = coll or bpy.context.scene.collection
    scene_layout = _get_or_create_scene_layout(layout_coll)

    created = []
    for box in boxes:
        cube = _make_wire_box(box, layout_coll)
        cube.parent = scene_layout
        cube.matrix_parent_inverse = Matrix.Identity(4)  # parent at identity
        _apply_box_local_pose(cube, box)
        created.append(cube.name)

    scale = _seed_fit(scene_layout, boxes, collider)
    _set_collider_visible(collider, True)  # show the room to place against
    logger.info("[WorldLabs] %d box placeholder(s) under '%s' (seed scale=%.4f)",
                len(created), scene_layout.name, scale)
    return {
        "success": True, "scene_layout": scene_layout.name, "collider": collider.name,
        "boxes": created, "count": len(created), "seed_scale": round(scale, 6),
        "collider_visible": True,
    }


def finalize_world_layout(collection_name: str = "") -> dict:
    """Re-hide the collider room mesh — call once placement looks right.

    Leaves the clean look: the splat proxy + the placed objects, with the bare
    collider shell hidden again (it stays in the file for ray-casts / re-runs).
    """
    collider, _coll = _find_collider(collection_name)
    if collider is None:
        return {"success": False, "error": "World Labs collider not found"}
    _set_collider_visible(collider, False)
    logger.info("[WorldLabs] finalized scene — collider '%s' hidden", collider.name)
    return {"success": True, "collider": collider.name, "collider_visible": False}


# ---------------------------------------------------------------------------
# Snap finished meshes into their boxes (matched by chain_id)
# ---------------------------------------------------------------------------

def _root(obj):
    """Topmost parent that is not the SceneLayout empty."""
    cur = obj
    seen = set()
    while (cur.parent is not None and cur.parent.name != _SCENE_LAYOUT_NAME
           and cur.name not in seen):
        seen.add(cur.name)
        cur = cur.parent
    return cur


def _find_mesh_by_chain_id(chain_id: str):
    """Find the imported (non-placeholder) object carrying this chain_id."""
    for obj in bpy.data.objects:
        if obj.get("wl_box") or obj.get("wl_role"):
            continue
        if obj.get("mixar_chain_id") == chain_id:
            return obj
    return None


def _resolve_assignments(assignments):
    """Build {chain_id: object_name} and {label: object_name} lookups."""
    by_chain, by_label = {}, {}
    for a in assignments or []:
        if not isinstance(a, dict):
            continue
        name = a.get("object_name")
        if not name:
            continue
        if a.get("chain_id"):
            by_chain[a["chain_id"]] = name
        if a.get("label"):
            by_label[str(a["label"]).strip().lower()] = name
    return by_chain, by_label


def snap_meshes_to_boxes(assignments=None) -> dict:
    """Place each finished Hunyuan mesh at its box; the mesh keeps its native size.

    Matching is, in order: an explicit ``assignments`` entry (by chain_id, then by
    label) the agent passes — it already knows label->chain_id and cutout->mesh —
    then a fallback scan for a mesh already tagged ``mixar_chain_id``. The matched
    mesh's pose (position + rotation) is set to its box's recon pose under
    ``SceneLayout`` (inheriting the one global uniform scale); no per-object resize.
    The mesh is stamped with ``mixar_chain_id`` so re-runs are idempotent.

    ``assignments``: list of ``{"object_name", "chain_id"?, "label"?}``.
    """
    boxes = get_recon_boxes()
    if not boxes:
        return {"success": False, "error": "no recon boxes — run extract_labels first"}
    scene_layout = bpy.data.objects.get(_SCENE_LAYOUT_NAME)
    by_chain, by_label = _resolve_assignments(assignments)

    snapped, missing = [], []
    for box in boxes:
        name = by_chain.get(box["chain_id"]) or by_label.get(box["label"].strip().lower())
        mesh = bpy.data.objects.get(name) if name else None
        if mesh is None:
            mesh = _find_mesh_by_chain_id(box["chain_id"])
        if mesh is None:
            missing.append(box["label"])
            continue
        root = _root(mesh)
        root["mixar_chain_id"] = box["chain_id"]  # persist the match
        if scene_layout is not None:
            root.parent = scene_layout
            root.matrix_parent_inverse = Matrix.Identity(4)
        # Position only. Do NOT apply the SAM3D box rotation — the meshes import
        # already upright (top +Z), and the box quaternion lays them on their back
        # (top -Y). Keep the correct import orientation; size stays native
        # (inherits SceneLayout's uniform scale via parenting).
        root.location = Vector(box["center"])
        snapped.append(root.name)

    logger.info("[WorldLabs] snapped %d mesh(es), %d still missing",
                len(snapped), len(missing))
    return {"success": True, "snapped": snapped, "missing": missing,
            "scene_layout": scene_layout.name if scene_layout else None}


# ---------------------------------------------------------------------------
# Viewpoint camera + mesh staging (place-from-the-viewpoint flow)
# ---------------------------------------------------------------------------

_VIEWPOINT_NAME = "WorldLabs_Viewpoint"


def _get_or_create_camera(name: str, collection):
    cam = bpy.data.objects.get(name)
    if cam is None or cam.type != "CAMERA":
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        collection.objects.link(cam)
    return cam


def _rest_on_floor(root, point: Vector) -> None:
    """Move root so its bbox bottom-centre sits at ``point`` (x, y, floor_z)."""
    bb = _hierarchy_bbox(root)
    if bb is None:
        root.matrix_world = Matrix.Translation(point) @ root.matrix_world
        return
    mn, mx = bb
    offset = Vector((
        point.x - (mn.x + mx.x) / 2.0,
        point.y - (mn.y + mx.y) / 2.0,
        point.z - mn.z,
    ))
    root.matrix_world = Matrix.Translation(offset) @ root.matrix_world


def setup_viewpoint_and_stage(mesh_names=None, collection_name: str = "") -> dict:
    """Put a camera at the world viewpoint and line the meshes up in front of it.

    A Marble world is a 360 panorama rendered from one centre point — the capture
    VIEWPOINT, roughly eye height above the floor (the splat origin). We drop a
    camera there ("WorldLabs_Viewpoint"), looking horizontally, so the agent sees
    the room as if standing in it (it can rotate the camera to look around the
    360). Then it stages the generated meshes in a row on the floor in front of the
    camera so they're all visible and separated, ready for the agent to place into
    the scene by sight.
    """
    collider, coll = _find_collider(collection_name)
    if collider is None:
        return {"success": False, "error": "World Labs collider not found"}
    cmn, cmx = _hierarchy_bbox(collider) or _simple_bbox(collider)
    cx = (cmn.x + cmx.x) / 2.0
    cy = (cmn.y + cmx.y) / 2.0
    floor = cmn.z
    room_h = max(cmx.z - cmn.z, 0.1)
    eye = floor + 0.45 * room_h  # mid-room height ~ a standing viewpoint

    layout_coll = coll or bpy.context.scene.collection
    cam = _get_or_create_camera(_VIEWPOINT_NAME, layout_coll)
    cam.location = (cx, cy, eye)
    # Blender cameras look down -Z; +90deg X makes it look horizontally along -Y.
    cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    try:
        bpy.context.scene.camera = cam
    except Exception:  # noqa: BLE001
        pass

    names = [n for n in (mesh_names or []) if bpy.data.objects.get(n)]
    count = max(len(names), 1)
    spacing = (cmx.x - cmn.x) * 0.6 / count
    front = (cmx.y - cmn.y) * 0.30  # distance in front of the camera (along -Y)
    staged = []
    for i, nm in enumerate(names):
        root = _root(bpy.data.objects[nm])
        bx = cx + (i - (len(names) - 1) / 2.0) * spacing
        _rest_on_floor(root, Vector((bx, cy - front, floor)))
        staged.append(root.name)

    logger.info("[WorldLabs] viewpoint camera '%s' at (%.2f, %.2f, %.2f); staged %d mesh(es)",
                cam.name, cx, cy, eye, len(staged))
    return {
        "success": True, "camera": cam.name,
        "viewpoint": [round(cx, 3), round(cy, 3), round(eye, 3)],
        "floor_z": round(floor, 3), "staged": staged,
        "note": "Rendering from this camera shows the room from the viewpoint. "
                "Rotate the camera (transform_object on it) to look around the 360.",
    }
