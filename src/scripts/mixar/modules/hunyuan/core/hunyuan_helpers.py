# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Hunyuan 3D -- Helper Functions

Pure utility functions used by operators and callbacks:
- get_poll_interval: progressive poll timing
- _redraw_3d_views: force viewport redraws
- _get_total_face_count: sum selected mesh faces
- export_selected_mesh: export selection to temp file
- download_file: download a URL to a temp file (safe for background threads)
- import_file: import a downloaded file into Blender (main thread only)
"""

import os
import tempfile
import urllib.request

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.constants import HUNYUAN_TIMEOUT

logger = get_logger(__name__)


# ============================================================================
# POLL INTERVAL
# ============================================================================


def get_poll_interval(poll_count):
    """Progressive poll interval: 10s -> 5s -> 3s."""
    if poll_count < 3:
        return 10.0
    elif poll_count < 6:
        return 5.0
    else:
        return 3.0


# ============================================================================
# VIEW REFRESH
# ============================================================================


def _redraw_3d_views():
    """Force redraw of all 3D viewports and MIXIE areas."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in ('VIEW_3D', 'MIXIE'):
                area.tag_redraw()


# ============================================================================
# MESH UTILITIES
# ============================================================================


def _get_total_face_count(context):
    """Get total face count of all selected mesh objects."""
    total = 0
    for obj in context.selected_objects:
        if obj.type == 'MESH':
            total += len(obj.data.polygons)
    return total


def export_selected_mesh(context, format="GLB"):
    """Export selected mesh objects to temp file. Returns (bytes, filename)."""
    ext_map = {"GLB": ".glb", "OBJ": ".obj", "FBX": ".fbx"}
    ext = ext_map[format]
    fd, filepath = tempfile.mkstemp(suffix=ext, prefix="hunyuan_export_")
    os.close(fd)

    selected = [o for o in context.selected_objects if o.type == 'MESH']
    if not selected:
        raise ValueError("No mesh objects selected")

    if format == "GLB":
        bpy.ops.export_scene.gltf(
            filepath=filepath, use_selection=True, export_format='GLB',
        )
    elif format == "OBJ":
        bpy.ops.wm.obj_export(
            filepath=filepath, export_selected_objects=True,
        )
    elif format == "FBX":
        bpy.ops.export_scene.fbx(filepath=filepath, use_selection=True)

    with open(filepath, "rb") as f:
        data = f.read()
    try:
        os.remove(filepath)
    except OSError:
        pass

    return data, f"export{ext}"


# ============================================================================
# DOWNLOAD & IMPORT
# ============================================================================

def download_file(url, file_type="GLB"):
    """Download a URL to a temp file. Safe to call from a background thread.

    Uses ``urllib.request.urlopen`` with an explicit timeout so the call
    never blocks indefinitely.

    Returns:
        The path to the downloaded temp file.
    """
    ext_map = {"GLB": ".glb", "OBJ": ".obj", "FBX": ".fbx"}
    ext = ext_map.get(file_type.upper(), ".glb")
    fd, filepath = tempfile.mkstemp(suffix=ext, prefix="hunyuan_result_")
    os.close(fd)

    response = urllib.request.urlopen(url, timeout=HUNYUAN_TIMEOUT)
    try:
        with open(filepath, "wb") as out:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                out.write(chunk)
    finally:
        response.close()

    return filepath


def import_file(filepath, file_type="GLB"):
    """Import a local file into Blender. Must run on the main thread.

    Returns:
        A comma-separated string of newly imported object names.
    """
    before = set(o.name for o in bpy.data.objects)

    try:
        ft = file_type.upper()
        if ft == "GLB":
            bpy.ops.import_scene.gltf(filepath=filepath)
        elif ft == "OBJ":
            bpy.ops.wm.obj_import(filepath=filepath)
        elif ft == "FBX":
            bpy.ops.import_scene.fbx(filepath=filepath)

        after = set(o.name for o in bpy.data.objects)
        new_objects = after - before

        return ", ".join(new_objects) if new_objects else "Unknown"
    finally:
        # Always unlink the temp file even when the import itself raises,
        # otherwise every failed import leaves a GLB/OBJ/FBX behind in /tmp.
        try:
            os.remove(filepath)
        except OSError:
            pass


# ============================================================================
# POST-IMPORT RENAME & SETUP
# ============================================================================

def post_import_rename_and_setup(object_names_str, target_name, smart_uv=False):
    """Post-import cleanup: remove Empty parents, rename mesh, set origin to
    bottom of bounding box, and move to world origin.

    1. Find imported objects by name from the comma-separated string.
    2. If any is an Empty parent, reparent mesh children preserving world
       transform, then delete the Empty.
    3. Rename the mesh to *target_name*.
    4. Apply all transforms (location/rotation/scale).
    5. Set origin to bottom-center of bounding box (lowest Z).
    6. Move object to world origin (0, 0, 0).
    7. (Optional) If *smart_uv* is True, run Smart UV Project on the mesh.
    """
    from mathutils import Vector, Matrix

    names = [n.strip() for n in object_names_str.split(",") if n.strip()]
    if not names:
        return

    imported = [bpy.data.objects.get(n) for n in names]
    imported = [o for o in imported if o is not None]
    if not imported:
        return

    # Remove Empty parents — reparent children, delete Empty
    mesh_obj = None
    for obj in list(imported):
        if obj.type == 'EMPTY':
            for child in list(obj.children):
                mat = child.matrix_world.copy()
                child.parent = None
                child.matrix_world = mat
                if child.type == 'MESH' and mesh_obj is None:
                    mesh_obj = child
            bpy.data.objects.remove(obj, do_unlink=True)
        elif obj.type == 'MESH' and mesh_obj is None:
            mesh_obj = obj

    if mesh_obj is None:
        return

    # Rename
    mesh_obj.name = target_name
    if mesh_obj.data:
        mesh_obj.data.name = target_name

    # Select only this object
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj

    # Apply all transforms
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # Set origin to bottom-center of bounding box (lowest Z)
    local_corners = [Vector(c) for c in mesh_obj.bound_box]
    min_z_local = min(c.z for c in local_corners)
    center_x = sum(c.x for c in local_corners) / 8
    center_y = sum(c.y for c in local_corners) / 8
    bottom_center = Vector((center_x, center_y, min_z_local))

    # Shift mesh data so origin moves to bottom_center
    mesh_obj.data.transform(Matrix.Translation(-bottom_center))
    mesh_obj.matrix_world.translation += bottom_center

    # Move to world origin (0, 0, 0)
    mesh_obj.location = (0, 0, 0)

    # Smart UV Project (for retopo meshes that lack UVs)
    if smart_uv:
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.02)
            bpy.ops.object.mode_set(mode='OBJECT')
            logger.info(
                "[HunyuanHelpers] Smart UV Project applied to '%s'", target_name
            )
        except Exception as e:
            # Ensure we return to object mode even on failure
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass
            logger.warning(
                "[HunyuanHelpers] Smart UV Project failed for '%s': %s",
                target_name, e,
            )

    logger.info(
        "[HunyuanHelpers] Post-import setup complete: '%s'", target_name
    )
