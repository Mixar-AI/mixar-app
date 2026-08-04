# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generic Blender-side model I/O and queue pacing helpers.

Provider-agnostic plumbing shared by the queue engine and feature
operators (moved out of ``modules/hunyuan/core/hunyuan_helpers.py`` —
it never contained vendor logic, only Blender-session work the backend
cannot do):

- get_poll_interval: progressive poll timing
- tag_redraw_queue_surfaces: repaint every area that shows queue state
  (``redraw_3d_views`` is the legacy alias)
- get_total_face_count: sum selected mesh faces
- export_selected_mesh: export selection to bytes for upload
- import_file: import a downloaded file into Blender (main thread only)
- post_import_rename_and_setup: rename/origin/UV cleanup after import

``download_file`` used to live here; it now lives in ``downloader.py``
(deadline / verification / retry policy earned its own file) and is
re-exported below so existing import sites keep working.

Deliberately imports nothing from the queue core so ``queue_manager``
can depend on it without cycles (``helpers.py`` is the image-side
counterpart but sits above ``queue_manager``).
"""

import os
import tempfile

import bpy

from mixar.config.logging_config import get_logger

from .downloader import download_file  # noqa: F401  (re-export)

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


# Every area type that renders live queue state: the 3D viewport (toasts,
# feature overlays), the MIXIE editor (Queue panel) and the floating Agent
# Bubble / status pill (queue-aware pill label).
#
# AGENT_BUBBLE is load-bearing: the bubble and its minimised pill each live
# in their OWN wmWindow, so a queue change tagged only VIEW_3D/MIXIE left the
# pill painting a stale label until the user happened to hover it — which is
# exactly the surface that is supposed to report background work.
QUEUE_SURFACE_AREA_TYPES = ('VIEW_3D', 'MIXIE', 'AGENT_BUBBLE')


def tag_redraw_queue_surfaces():
    """Tag every area that renders queue state for redraw."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type not in QUEUE_SURFACE_AREA_TYPES:
                continue
            area.tag_redraw()
            if area.type == 'AGENT_BUBBLE':
                # The bubble's header/pill needs its regions tagged
                # explicitly — same finding as the chat loader animation
                # (animation_manager._update_loader): tagging the area alone
                # leaves the pill static in Zen Mode.
                for region in area.regions:
                    region.tag_redraw()


def redraw_3d_views():
    """Deprecated alias — use ``tag_redraw_queue_surfaces()``."""
    tag_redraw_queue_surfaces()


# ============================================================================
# MESH UTILITIES
# ============================================================================


def get_total_face_count(context):
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
    fd, filepath = tempfile.mkstemp(suffix=ext, prefix="mixar_export_")
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
# SAFE OBJECT-DIFF SNAPSHOTS
# ============================================================================
# Reading obj.name raises UnicodeDecodeError when a scene object carries
# invalid UTF-8 bytes in its name (e.g. a binary file once fed to the OBJ
# importer). Diffing by session_uid never touches names, so one poisoned
# object can't fail every subsequent import in the session.


def snapshot_object_uids():
    """Session-uid snapshot of bpy.data.objects (never reads names)."""
    return {o.session_uid for o in bpy.data.objects}


def new_object_names(before):
    """Names of objects created since *before* (a snapshot_object_uids()
    set).

    Any object whose name can't be decoded — new or pre-existing — is
    renamed in place to a readable fallback (renaming never reads the old
    name), so a previously poisoned scene self-heals on the next import
    instead of breaking every later name read.
    """
    names = []
    for o in bpy.data.objects:
        try:
            name = o.name
        except UnicodeDecodeError:
            name = f"recovered_{o.session_uid}"
            try:
                o.name = name
            except Exception:
                continue  # not renameable (e.g. linked data) — skip
        if o.session_uid not in before:
            names.append(name)
    return names


# ============================================================================
# IMPORT
# ============================================================================

def import_file(filepath, file_type="GLB", import_options=None):
    """Import a local file into Blender. Must run on the main thread.

    ``import_options`` (dict, GLB only) is merged into the glTF import
    operator kwargs — used by the Animate feature to import Tripo rigged /
    animated glTF with ``guess_original_bind_pose=False`` so externally
    authored animations don't collapse (Blender's default guessed bind
    pose distorts non-Blender rigs). Callers pass only keys the glTF
    importer accepts.

    Returns:
        A comma-separated string of newly imported object names.
    """
    before = snapshot_object_uids()

    try:
        ft = file_type.upper()
        if ft == "GLB":
            gltf_kwargs = {"filepath": filepath}
            if import_options:
                gltf_kwargs.update(import_options)
            bpy.ops.import_scene.gltf(**gltf_kwargs)
        elif ft == "OBJ":
            bpy.ops.wm.obj_import(filepath=filepath)
        elif ft == "FBX":
            bpy.ops.import_scene.fbx(filepath=filepath)

        new_objects = new_object_names(before)
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
                "[ModelIO] Smart UV Project applied to '%s'", target_name
            )
        except Exception as e:
            # Ensure we return to object mode even on failure
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass
            logger.warning(
                "[ModelIO] Smart UV Project failed for '%s': %s",
                target_name, e,
            )

    logger.info(
        "[ModelIO] Post-import setup complete: '%s'", target_name
    )
