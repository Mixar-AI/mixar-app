# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Importer for Moodboard

Imports GLB objects with pose transforms for incremental scene generation.
Based on sam3d_blender_importer_incremental.py.
"""

import os
import tempfile
from math import pi, tan, sin, atan
from typing import List, Optional

import bpy
from mathutils import Matrix, Vector, Quaternion

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


# Global scene state
_scene_state = {
    "collection": None,
    "camera": None,
    "objects": [],
    "z_offset": 0.0,
    "z_offset_locked": False,
}


def _write_temp_glb(glb_bytes: bytes, name: str) -> str:
    """Write GLB bytes to temp file and return path."""
    import datetime
    temp_dir = os.path.join(tempfile.gettempdir(), 'mixar_scenegen')
    os.makedirs(temp_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(temp_dir, f"{name}_{timestamp}.glb")
    with open(path, 'wb') as f:
        f.write(glb_bytes)
    return path


def init_scene(
    clear_existing: bool = False,
    camera_direction: str = "-x",
    collection_name: Optional[str] = None,
):
    """
    Initialize scene for generated objects.

    Args:
        clear_existing: If True, removes the target collection if it already exists
        camera_direction: Camera look direction ("-x", "-y", "+x", "+y")
        collection_name: Unique collection name. If None, generates one with a timestamp suffix.

    Returns:
        The created collection
    """
    global _scene_state

    if collection_name is None:
        import datetime
        suffix = datetime.datetime.now().strftime("%H%M%S")
        collection_name = f"SceneGen_{suffix}"

    # Clear only the specific target collection if requested
    if clear_existing and collection_name in bpy.data.collections:
        old_collection = bpy.data.collections[collection_name]
        for obj in list(old_collection.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old_collection)

    # Create new collection
    collection = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(collection)

    # Create camera
    cam_data = bpy.data.cameras.new("SceneGen_Camera")
    cam_obj = bpy.data.objects.new("SceneGen_Camera", cam_data)
    collection.objects.link(cam_obj)

    # Camera placement by look direction (all Z-up)
    _camera_presets = {
        "-x": ((5, 0, 0), (pi/2, 0, pi/2)),
        "+x": ((-5, 0, 0), (pi/2, 0, -pi/2)),
        "-y": ((0, 5, 0), (pi/2, 0, pi)),
        "+y": ((0, -5, 0), (pi/2, 0, 0)),
    }
    loc, rot = _camera_presets.get(camera_direction, _camera_presets["-x"])
    cam_obj.location = loc
    cam_obj.rotation_euler = rot
    bpy.context.scene.camera = cam_obj

    # Reset state
    _scene_state = {
        "collection": collection,
        "camera": cam_obj,
        "camera_direction": camera_direction,
        "objects": [],
        "z_offset": 0.0,
        "z_offset_locked": False,
    }

    # Switch to camera view
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces[0].region_3d.view_perspective = 'CAMERA'
            break

    logger.debug("[SceneGen] Scene initialized")
    return collection


def set_z_offset(z_offset: float):
    """
    Manually set the Z offset for the scene.
    Call this if you know the average Z beforehand.

    Args:
        z_offset: The Z offset value to use
    """
    global _scene_state
    _scene_state["z_offset"] = z_offset
    _scene_state["z_offset_locked"] = True
    logger.debug("[SceneGen] Z offset set to: %.3f", z_offset)


def add_object(
    glb_bytes: bytes,
    pose_data: Optional[dict],
    object_id: int,
    name: Optional[str] = None,
    auto_adjust_camera: bool = True,
    camera_margin: float = 1.1,
):
    """
    Add a single object to the scene with pose transform.

    Args:
        glb_bytes: Raw GLB file content
        pose_data: Dict with 'quaternion' (w,x,y,z), 'translation' [x,y,z], 'scale' float
        object_id: Object index
        name: Optional name for the object
        auto_adjust_camera: If True, readjust camera after adding object
        camera_margin: Margin for camera framing (1.1 = 10% padding)

    Returns:
        The imported Blender object
    """
    global _scene_state

    # Ensure scene is initialized
    if _scene_state["collection"] is None:
        init_scene()

    collection = _scene_state["collection"]

    # Write GLB to temp file and import
    temp_path = _write_temp_glb(glb_bytes, f"scenegen_obj{object_id}")
    logger.debug("[SceneGen] Importing GLB...")

    bpy.ops.import_scene.gltf(filepath=temp_path)

    mesh_pose_matrix = pose_data.get("mesh_pose_matrix") if pose_data else None

    if mesh_pose_matrix is not None:
        # ================================================================
        # Scene-recon path: precomputed 4x4 matrix from backend
        # ================================================================
        # Replicates the working CLI pipeline (scene_blender_builder.py).
        #
        # DO NOT flatten the hierarchy or reset matrix_world to Identity.
        # The GLB importer creates a transform (Y-up → Z-up) that must be
        # preserved. We MULTIPLY our pose matrix onto it.

        imported_objs = list(bpy.context.selected_objects)
        if not imported_objs:
            logger.error("[SceneGen] Failed to import object %s", object_id)
            return None

        # Find root objects (those without a parent in the imported set)
        imported_set = set(imported_objs)
        root_objs = [obj for obj in imported_objs if obj.parent not in imported_set]

        # Build the 4x4 matrix from nested list
        mat = Matrix([
            mesh_pose_matrix[0],
            mesh_pose_matrix[1],
            mesh_pose_matrix[2],
            mesh_pose_matrix[3],
        ])

        # MULTIPLY pose onto importer's existing matrix (preserves Y-up→Z-up)
        for obj in root_objs:
            obj.matrix_world = mat @ obj.matrix_world

        # Use the first mesh object as target_obj for naming/collection
        target_obj = next(
            (o for o in imported_objs if o.type == 'MESH'), imported_objs[0]
        )

        logger.debug(
            "[SceneGen] Applied mesh_pose_matrix to object %s (%s nodes, %s roots)",
            object_id, len(imported_objs), len(root_objs)
        )

    else:
        # ================================================================
        # Legacy / scene_gen path: quaternion + translation + scale
        # ================================================================
        imported = bpy.context.selected_objects[0] if bpy.context.selected_objects else None

        if not imported:
            logger.error("[SceneGen] Failed to import object %s", object_id)
            return None

        # Flatten hierarchy (remove parent empty if present)
        if imported.parent:
            root = imported.parent
            imported.parent = None
            imported.matrix_world = Matrix.Identity(4)
            bpy.data.objects.remove(root, do_unlink=True)

        target_obj = imported

        # Apply pose transform if provided
        if pose_data:
            logger.debug("[SceneGen] Object %s raw pose data received", object_id)

            # Update Z offset if not locked (running average)
            if not _scene_state["z_offset_locked"]:
                current_z = pose_data["translation"][2]
                n = len(_scene_state["objects"])
                old_avg = _scene_state["z_offset"]
                new_avg = (old_avg * n + current_z) / (n + 1)
                _scene_state["z_offset"] = new_avg

            z_offset = Vector((0, 0, _scene_state["z_offset"]))

            # Build rotation from quaternion: Negate W (-w, x, y, z)
            q = pose_data["quaternion"]
            if isinstance(q, dict):
                rot_quat = Quaternion((-q["w"], q["x"], q["y"], q["z"]))
            else:
                rot_quat = Quaternion((-q[0], q[1], q[2], q[3]))

            rot_mat = rot_quat.to_matrix().to_4x4()

            # Build translation (subtract Z offset)
            t = Vector(pose_data["translation"]) - z_offset
            trans_mat = Matrix.Translation(t)

            # Build scale
            scale_val = pose_data["scale"]
            scale_mat = Matrix.Scale(scale_val, 4)

            # Coordinate system correction: (-Z forward, Y up) -> (+X forward, Z up)
            correction_mat = Matrix((
                (0, 0, -1, 0),
                (-1, 0, 0, 0),
                (0, 1, 0, 0),
                (0, 0, 0, 1)
            ))

            target_obj.matrix_world = correction_mat @ trans_mat @ rot_mat @ scale_mat

            logger.debug("[SceneGen] Applied pose to object %s", object_id)

    # Collect all objects that need relinking and naming
    if mesh_pose_matrix is not None:
        all_imported = imported_objs
    else:
        all_imported = [target_obj]

    # Move ALL imported objects to SceneGen collection
    for obj in all_imported:
        for coll in list(obj.users_collection):
            coll.objects.unlink(obj)
        collection.objects.link(obj)

    # Set names
    obj_name = name or f"SceneGen_Object_{object_id}"
    target_obj.name = obj_name
    # Rename root empties to match the object label
    if mesh_pose_matrix is not None:
        for obj in root_objs:
            if obj is not target_obj:
                obj.name = obj_name

    # Track all imported objects (for bounding sphere / camera framing)
    _scene_state["objects"].extend(all_imported)

    logger.debug("[SceneGen] Added: %s", target_obj.name)

    # Readjust camera
    if auto_adjust_camera:
        adjust_camera(margin=camera_margin)

    return target_obj


def add_bbox_placeholder(
    center: List[float],
    dimensions: List[float],
    rotation: List[float],
    scale: float,
    object_id: int,
    name: Optional[str] = None,
    auto_adjust_camera: bool = True,
    bbox_pose_matrix: Optional[list] = None,
):
    """
    Create a wireframe bounding-box cube as a placeholder.

    When ``bbox_pose_matrix`` (4x4 nested list) is provided, it is applied
    via **direct assignment** to a unit cube — encoding position, orientation
    and per-axis scale in one matrix.  This is the preferred path.

    Falls back to composing from center/dimensions/rotation/scale when the
    matrix is not available (old backend).

    Args:
        center: [x, y, z] world position (fallback)
        dimensions: [w, h, d] bounding box size (fallback)
        rotation: [w, x, y, z] quaternion (fallback)
        scale: uniform scale factor (fallback)
        object_id: object index
        name: display name / label
        auto_adjust_camera: if True, readjust camera after adding
        bbox_pose_matrix: precomputed 4x4 world matrix (preferred)

    Returns:
        The created placeholder object, or None on failure.
    """
    global _scene_state

    if _scene_state["collection"] is None:
        init_scene()

    collection = _scene_state["collection"]

    try:
        bpy.ops.mesh.primitive_cube_add(size=1)
        obj = bpy.context.active_object

        if bbox_pose_matrix is not None:
            # Preferred path: precomputed 4x4 world matrix.
            # DIRECT ASSIGNMENT — unit cube has identity, no importer matrix.
            mat = Matrix([
                bbox_pose_matrix[0],
                bbox_pose_matrix[1],
                bbox_pose_matrix[2],
                bbox_pose_matrix[3],
            ])
            obj.matrix_world = mat
            logger.debug("[SceneGen] Applied bbox_pose_matrix to placeholder %s", object_id)
        else:
            # Legacy fallback: compose from separate fields
            w, h, d = dimensions
            obj.dimensions = (w * scale, h * scale, d * scale)
            obj.location = Vector(center)
            qw, qx, qy, qz = rotation
            obj.rotation_mode = 'QUATERNION'
            obj.rotation_quaternion = Quaternion((qw, qx, qy, qz))

        # Wireframe display
        obj.display_type = 'WIRE'

        # Name
        obj_name = name or f"BBox_{object_id}"
        obj.name = obj_name

        # Store object_id as custom property for later reference
        obj["bbox_object_id"] = object_id

        # Move to SceneGen collection
        for coll in list(obj.users_collection):
            coll.objects.unlink(obj)
        collection.objects.link(obj)

        # Track in scene state
        _scene_state["objects"].append(obj)

        logger.debug("[SceneGen] Added bbox placeholder: %s", obj_name)

        if auto_adjust_camera:
            adjust_camera()

        return obj

    except Exception as e:
        logger.error("[SceneGen] Failed to create bbox placeholder %s: %s", object_id, e)
        return None


def replace_placeholder(placeholder_obj, imported_objs):
    """
    Place imported asset objects at a wireframe placeholder's location.

    Scales the imported objects to fit within the placeholder's bounding box
    and positions them at the placeholder's location.  The placeholder is
    kept (hidden) so the user can toggle its visibility later.

    Args:
        placeholder_obj: the wireframe cube used as spatial reference
        imported_objs: list of imported Blender objects (root + children)

    Returns:
        The primary imported object, or None on failure.
    """
    global _scene_state

    if not placeholder_obj or not imported_objs:
        return None

    collection = _scene_state["collection"]

    try:
        # Decompose the placeholder's full world matrix so we get the
        # correct location, rotation and per-axis scale regardless of
        # the object's rotation_mode (which defaults to Euler).
        ph_loc, ph_rot, ph_scale = placeholder_obj.matrix_world.decompose()

        # Placeholder is a unit cube (size=1), so its world-space extents
        # along each axis equal the corresponding scale component.
        ph_dims = Vector((abs(ph_scale.x), abs(ph_scale.y), abs(ph_scale.z)))

        # Link all imported objects to the same collection
        for obj in imported_objs:
            for coll in list(obj.users_collection):
                coll.objects.unlink(obj)
            if collection:
                collection.objects.link(obj)

        bpy.context.view_layer.update()

        # Find root objects (those whose parent is NOT in the imported set).
        # We must position the roots; children follow via parenting.
        imported_set = set(imported_objs)
        roots = [o for o in imported_objs if o.parent not in imported_set]
        if not roots:
            roots = imported_objs[:1]

        # Compute the world-space AABB across ALL imported meshes so we
        # get the true extent regardless of hierarchy or existing transforms.
        all_corners = []
        for obj in imported_objs:
            if obj.type == 'MESH' and obj.data and obj.data.vertices:
                for corner in obj.bound_box:
                    all_corners.append(obj.matrix_world @ Vector(corner))

        if all_corners:
            bbox_min = Vector((
                min(c.x for c in all_corners),
                min(c.y for c in all_corners),
                min(c.z for c in all_corners),
            ))
            bbox_max = Vector((
                max(c.x for c in all_corners),
                max(c.y for c in all_corners),
                max(c.z for c in all_corners),
            ))
            imp_dims = bbox_max - bbox_min
            imp_center = (bbox_min + bbox_max) / 2
        else:
            imp_dims = Vector((0.001, 0.001, 0.001))
            imp_center = Vector((0, 0, 0))

        imp_dims.x = max(imp_dims.x, 0.001)
        imp_dims.y = max(imp_dims.y, 0.001)
        imp_dims.z = max(imp_dims.z, 0.001)

        # Scale to fit within placeholder bbox (uniform, use smallest ratio)
        scale_ratio = min(
            ph_dims.x / imp_dims.x,
            ph_dims.y / imp_dims.y,
            ph_dims.z / imp_dims.z,
        )

        # Compute offset from the asset's current center to the roots,
        # so after moving roots to ph_loc the asset's bbox center lands there.
        for root in roots:
            root_offset = root.matrix_world.translation - imp_center
            root.scale *= scale_ratio
            # After scaling, the offset also scales
            root.location = ph_loc + root_offset * scale_ratio
            root.rotation_mode = 'QUATERNION'
            root.rotation_quaternion = ph_rot

        bpy.context.view_layer.update()

        # Track imported objects alongside the placeholder
        _scene_state["objects"].extend(imported_objs)

        primary = next(
            (o for o in imported_objs if o.type == 'MESH'), imported_objs[0]
        )
        logger.debug("[SceneGen] Placed %s at placeholder (scale_ratio=%.3f, roots=%s)",
                     primary.name, scale_ratio, len(roots))
        return primary

    except Exception as e:
        logger.error("[SceneGen] Failed to place asset at placeholder: %s", e)
        return None


def get_scene_bounding_sphere():
    """
    Calculate bounding sphere for all objects in the scene.

    Returns:
        Tuple of (center: Vector, radius: float)
    """
    objects = _scene_state["objects"]

    if not objects:
        return Vector((0, 0, 0)), 1.0

    # Force update
    bpy.context.view_layer.update()

    # Collect all world-space bounding box corners
    all_points = []
    for obj in objects:
        if obj.type == 'MESH':
            bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            all_points.extend(bbox_corners)

    if not all_points:
        return Vector((0, 0, 0)), 1.0

    # Calculate center (average of all points)
    center = sum(all_points, Vector((0, 0, 0))) / len(all_points)

    # Calculate radius (max distance from center)
    radius = max((p - center).length for p in all_points)

    return center, radius


def adjust_camera(margin: float = 1.1):
    """
    Adjust camera to fit all objects in the scene.

    Args:
        margin: Extra margin around the scene (1.1 = 10% padding)
    """
    global _scene_state

    cam_obj = _scene_state["camera"]
    if cam_obj is None:
        return

    objects = _scene_state["objects"]
    if not objects:
        return

    # Get bounding sphere
    center, radius = get_scene_bounding_sphere()
    radius *= margin

    # Get camera FOV
    cam_data = cam_obj.data
    render = bpy.context.scene.render
    aspect_ratio = render.resolution_x / render.resolution_y

    sensor_width = cam_data.sensor_width
    focal_length = cam_data.lens

    # Horizontal and vertical FOV
    fov_h = 2 * atan(sensor_width / (2 * focal_length))
    fov_v = 2 * atan(tan(fov_h / 2) / aspect_ratio)

    # Use smaller FOV to ensure everything fits
    fov = min(fov_h, fov_v)

    # Calculate camera distance: distance = radius / sin(fov / 2)
    camera_distance = radius / sin(fov / 2) if sin(fov / 2) > 0 else 5.0

    # Position camera along the stored direction
    direction = _scene_state.get("camera_direction", "-x")
    cx, cy, cz = center.x, center.y, center.z
    _cam_offsets = {
        "-x": ((cx + camera_distance, cy, cz), (pi/2, 0, pi/2)),
        "+x": ((cx - camera_distance, cy, cz), (pi/2, 0, -pi/2)),
        "-y": ((cx, cy + camera_distance, cz), (pi/2, 0, pi)),
        "+y": ((cx, cy - camera_distance, cz), (pi/2, 0, 0)),
    }
    loc, rot = _cam_offsets.get(direction, _cam_offsets["-x"])
    cam_obj.location = loc
    cam_obj.rotation_euler = rot

    # Ensure camera view is active
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces[0].region_3d.view_perspective = 'CAMERA'
            break


def get_scene_info() -> dict:
    """
    Get information about the current scene state.

    Returns:
        Dict with scene information
    """
    center, radius = get_scene_bounding_sphere()

    return {
        "object_count": len(_scene_state["objects"]),
        "object_names": [obj.name for obj in _scene_state["objects"]],
        "z_offset": _scene_state["z_offset"],
        "z_offset_locked": _scene_state["z_offset_locked"],
        "bounding_center": tuple(center),
        "bounding_radius": radius,
        "camera_location": tuple(_scene_state["camera"].location) if _scene_state["camera"] else None,
    }


def clear_scene():
    """Remove all objects but keep the scene structure."""
    global _scene_state

    for obj in list(_scene_state["objects"]):
        bpy.data.objects.remove(obj, do_unlink=True)

    _scene_state["objects"] = []
    _scene_state["z_offset"] = 0.0
    _scene_state["z_offset_locked"] = False

    logger.debug("[SceneGen] Scene cleared")


def is_scene_initialized() -> bool:
    """Check if scene has been initialized."""
    return _scene_state["collection"] is not None