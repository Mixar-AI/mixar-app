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
        elif ft == "VIDEO":
            from mixar.modules.moodboard.core.media_import import (
                import_generated_video,
            )

            options = import_options or {}
            return import_generated_video(
                filepath,
                scene_name=options.get("scene_name", ""),
                generation_prompt=options.get("generation_prompt", ""),
            )

        new_objects = new_object_names(before)
        return ", ".join(new_objects) if new_objects else "Unknown"
    finally:
        # Generated-video import moves the temp file into persistent Mixar
        # storage. Removing the now-missing source is harmless.
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

    Returns the final mesh object name (Blender may append ``.001`` on a name
    collision), or ``None`` when no mesh was found.
    """
    names = [n.strip() for n in object_names_str.split(",") if n.strip()]
    if not names:
        return None

    imported = [bpy.data.objects.get(n) for n in names]
    imported = [o for o in imported if o is not None]
    if not imported:
        return None

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
        return None

    # Rename
    mesh_obj.name = target_name
    if mesh_obj.data:
        mesh_obj.data.name = mesh_obj.name

    # Apply transforms, set origin to bbox bottom-center, move to world origin.
    _set_origin_bottom_and_center(mesh_obj)

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
        "[ModelIO] Post-import setup complete: '%s'", mesh_obj.name
    )
    return mesh_obj.name


def _set_origin_bottom_and_center(mesh_obj):
    """Normalize a standalone mesh's placement.

    Applies all transforms, sets the object origin to the bottom-center of
    its bounding box (lowest Z), and moves the object to the world origin.
    Shared by ``post_import_rename_and_setup`` and ``rename_generated_model``.
    """
    from mathutils import Vector, Matrix

    # The operator calls below require OBJECT mode. Import runs on the main
    # thread right after the glTF import (itself object-mode), so this is a
    # cheap guard rather than a hot switch — but it keeps a stray Edit/Sculpt
    # mode on an unrelated object from poll-failing transform_apply.
    if bpy.context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

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


def rename_generated_model(object_names_str, target_name, front_zrot=0.0):
    """Rename + normalize a Model Gen import, per provider mesh shape.

    Two provider shapes are handled:

    - **Hunyuan / Tripo** return a single mesh: rename it (and its mesh
      data) to *target_name*, then normalize it via
      :func:`_set_origin_bottom_and_center` (apply transforms, origin to
      bbox bottom-center, move to world origin).
    - **Trellis** returns a mesh parented to an Empty: rename the mesh to
      *target_name* and the Empty to ``empty_<target_name>``, KEEP the
      parent hierarchy intact, and move the whole assembly (via the root
      Empty) so the mesh's world-space bottom-center rests at the world
      origin. Done in world space to preserve the Empty's own transform.

    *front_zrot* (radians) is a world-Z rotation applied first, so every
    engine's front faces the same axis (-Y) regardless of its native import
    orientation — see ``generation_enqueue.model_front_zrot``. The single
    mesh is rotated directly (baked by the following transform_apply); the
    Trellis assembly is rotated via its root Empty and then re-grounded.

    Naming/normalization only — unlike ``post_import_rename_and_setup`` it
    never deletes the Empty parent (the Trellis empty is intentional data).

    Returns the final mesh object name (Blender may append ``.001`` on a
    name collision), or ``None`` when no mesh was found.
    """
    from mathutils import Vector, Matrix

    if not target_name:
        return None

    names = [n.strip() for n in object_names_str.split(",") if n.strip()]
    imported = [bpy.data.objects.get(n) for n in names]
    imported = [o for o in imported if o is not None]
    if not imported:
        return None

    zrot = Matrix.Rotation(front_zrot, 4, 'Z') if front_zrot else None

    # Trellis: an Empty parenting a mesh child.
    empty_parent = None
    for obj in imported:
        if obj.type == 'EMPTY' and any(c.type == 'MESH' for c in obj.children):
            empty_parent = obj
            break

    if empty_parent is not None:
        mesh_obj = next(
            (c for c in empty_parent.children if c.type == 'MESH'), None)
        if mesh_obj is None:
            return None
        mesh_obj.name = target_name
        if mesh_obj.data:
            mesh_obj.data.name = mesh_obj.name
        # Derive the Empty name from the mesh's ACTUAL name (post collision
        # suffix), so a ``car`` -> ``car.001`` clash keeps ``empty_car.001``
        # rather than a mismatched ``empty_car``.
        empty_parent.name = f"empty_{mesh_obj.name}"

        # Face -Y: rotate the whole assembly about world Z via the root Empty,
        # then refresh so the child's world matrix reflects the new pose.
        if zrot is not None:
            empty_parent.matrix_world = zrot @ empty_parent.matrix_world
            bpy.context.view_layer.update()

        # Move the assembly so the mesh's world-space bottom-center sits at
        # the world origin, keeping the parent hierarchy and the Empty's own
        # transform intact.
        world_corners = [
            mesh_obj.matrix_world @ Vector(c) for c in mesh_obj.bound_box
        ]
        min_z = min(c.z for c in world_corners)
        center_x = sum(c.x for c in world_corners) / 8
        center_y = sum(c.y for c in world_corners) / 8
        bottom_center = Vector((center_x, center_y, min_z))
        empty_parent.matrix_world.translation -= bottom_center
        logger.info(
            "[ModelIO] Trellis model named + grounded: '%s' (parent '%s')",
            mesh_obj.name, empty_parent.name,
        )
        return mesh_obj.name

    # Hunyuan / Tripo: a single mesh.
    mesh_obj = next((o for o in imported if o.type == 'MESH'), None)
    if mesh_obj is None:
        return None
    mesh_obj.name = target_name
    if mesh_obj.data:
        mesh_obj.data.name = mesh_obj.name
    # Face -Y before normalization; transform_apply then bakes the rotation.
    if zrot is not None:
        mesh_obj.matrix_world = zrot @ mesh_obj.matrix_world
    _set_origin_bottom_and_center(mesh_obj)
    logger.info("[ModelIO] Model named + normalized: '%s'", mesh_obj.name)
    return mesh_obj.name


def rename_imported_object(object_names_str, target_name):
    """Rename the imported mesh (and its data) — NO transform/orientation change.

    For re-texture imports (PBR Generation / Texture Edit) whose geometry is the
    user's own mesh and must keep its pose and placement. Renames the first
    imported MESH to *target_name* and returns its final name (Blender may add a
    ``.001`` suffix), or ``None`` when no mesh was found.
    """
    if not target_name:
        return None
    names = [n.strip() for n in object_names_str.split(",") if n.strip()]
    imported = [bpy.data.objects.get(n) for n in names]
    imported = [o for o in imported if o is not None]
    mesh_obj = next((o for o in imported if o.type == 'MESH'), None)
    if mesh_obj is None:
        return None
    mesh_obj.name = target_name
    if mesh_obj.data:
        mesh_obj.data.name = mesh_obj.name
    logger.info(
        "[ModelIO] Imported mesh renamed (pose kept): '%s'", mesh_obj.name)
    return mesh_obj.name


# ============================================================================
# GENERATED-MATERIAL FINALIZE (rename material/images + split packed PBR map)
# ============================================================================
# Providers hand back messy material/image names (e.g. "tripo_material_<uuid>",
# "ORM_<hash>") and pack metallic+roughness into one glTF metallicRoughness
# texture (Separate Color: Green -> Roughness, Blue -> Metallic). We rename the
# material and every texture image to the "<mesh>_<map>" convention, and split
# the packed map into two standalone grayscale Non-Color images so each PBR map
# is an editable image in its own right (matching the Mixar paint per-channel
# model), deleting the Separate Color node + packed texture when no longer used.

_SEPARATE_COLOR_IDS = ("ShaderNodeSeparateColor", "ShaderNodeSeparateRGB")
_SOCKET_TO_CHANNEL = {"Red": 0, "Green": 1, "Blue": 2, "R": 0, "G": 1, "B": 2}


def finalize_generated_material(mesh_name):
    """Clean up the imported material(s) of *mesh_name* and return its PBR maps.

    For each material: rename it to the mesh's base name (indexed when several),
    rename its Base Color / Normal images to ``<base>_basecolor`` / ``<base>_normal``,
    and split the packed metallicRoughness map into standalone
    ``<base>_roughness`` / ``<base>_metallic`` images wired straight into the
    BSDF. No-op for scalar or already-separate maps. Main thread only.

    Returns the ``{basecolor, roughness, metallic, normal}`` Image datablocks of
    the first TEXTURED material (values may be ``None``), or ``{}`` when nothing
    textured is found — the caller can feed these into a paint fill layer.
    """
    obj = bpy.data.objects.get(mesh_name) if mesh_name else None
    if obj is None:
        logger.info("[ModelIO] Material finalize: object '%s' not found",
                    mesh_name)
        return {}

    # Unique materials, in slot order (a material shared by several slots is
    # processed once).
    mats = []
    for slot in getattr(obj, "material_slots", []):
        if slot.material is not None and slot.material not in mats:
            mats.append(slot.material)
    logger.info(
        "[ModelIO] Material finalize: '%s' has %d material(s)",
        mesh_name, len(mats))

    result = {}
    for i, mat in enumerate(mats):
        try:
            mat.name = mesh_name if len(mats) == 1 else f"{mesh_name}_{i + 1}"
            base = mat.name  # post-collision actual name — base for image names
            basecolor, normal = _rename_material_images(mat, base)
            reason, rough, metal = _split_material_packed_mr(mat, base)
            if reason:
                logger.info(
                    "[ModelIO] PBR split skipped '%s': %s", mat.name, reason)
            imgs = {
                "basecolor": basecolor, "normal": normal,
                "roughness": rough, "metallic": metal,
            }
            if not result and any(imgs.values()):
                result = imgs
        except Exception as e:
            logger.warning(
                "[ModelIO] Material finalize failed for '%s': %s",
                mat.name, e,
            )
    return result


def _rename_material_images(mat, base):
    """Rename Base Color / Normal images to the <base> convention.

    Returns ``(basecolor_image, normal_image)`` (each ``None`` when absent).
    """
    if not getattr(mat, "use_nodes", False) or mat.node_tree is None:
        return (None, None)
    bsdf = next(
        (n for n in mat.node_tree.nodes
         if n.bl_idname == "ShaderNodeBsdfPrincipled"),
        None,
    )
    if bsdf is None:
        return (None, None)

    basecolor = None
    normal = None

    # Base Color: a direct image texture into the socket.
    bc = bsdf.inputs.get("Base Color")
    if bc and bc.links:
        src = bc.links[0].from_node
        if src.bl_idname == "ShaderNodeTexImage" and src.image is not None:
            src.image.name = f"{base}_basecolor"
            basecolor = src.image

    # Normal: Normal Map node -> Color input <- image texture.
    nm = bsdf.inputs.get("Normal")
    if nm and nm.links:
        nmap = nm.links[0].from_node
        color_in = nmap.inputs.get("Color") if nmap else None
        if color_in and color_in.links:
            src = color_in.links[0].from_node
            if src.bl_idname == "ShaderNodeTexImage" and src.image is not None:
                src.image.name = f"{base}_normal"
                normal = src.image

    return (basecolor, normal)


def _split_material_packed_mr(mat, base_name):
    """Split the packed metallicRoughness map of a single material.

    Returns ``(reason, roughness_image, metallic_image)`` — *reason* is ``None``
    on success, else a short diagnostic string. The image values are the
    resolved roughness/metallic maps (a newly-created grayscale image when the
    channel was packed, or the existing dedicated image when already separate).
    """
    if not getattr(mat, "use_nodes", False) or mat.node_tree is None:
        return ("material has no node tree", None, None)
    nt = mat.node_tree

    bsdf = next(
        (n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"),
        None,
    )
    if bsdf is None:
        return ("no Principled BSDF", None, None)

    rough_in = bsdf.inputs.get("Roughness")
    metal_in = bsdf.inputs.get("Metallic")
    if rough_in is None or metal_in is None:
        return ("BSDF missing Roughness/Metallic input", None, None)

    # Resolve each input INDEPENDENTLY back to its (image, separate-node,
    # channel). This covers a shared Separate Color node (Hunyuan/ORM) AND two
    # different Separate Color nodes (Tripo) alike.
    rough_src = _resolve_channel_source(rough_in)
    metal_src = _resolve_channel_source(metal_in)
    if rough_src is None:
        return (f"cannot resolve Roughness source "
                f"[{_describe_input(rough_in)}]", None, None)
    if metal_src is None:
        return (f"cannot resolve Metallic source "
                f"[{_describe_input(metal_in)}]", None, None)

    r_tex, r_sep, r_idx = rough_src
    m_tex, m_sep, m_idx = metal_src

    changed = []
    sep_nodes = set()
    rough_img = None
    metal_img = None

    # Roughness: split from a packed channel, else the existing dedicated image.
    if r_sep is not None:
        rough_img = _grayscale_from_channel(
            r_tex.image, r_idx, f"{base_name}_roughness")
        if rough_img is None:
            return ("roughness packed image had no pixel data", None, None)
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = rough_img
        node.label = "Roughness"
        node.location = (r_tex.location.x, r_tex.location.y + 320)
        nt.links.new(node.outputs["Color"], rough_in)
        sep_nodes.add(r_sep)
        changed.append(rough_img.name)
    else:
        rough_img = r_tex.image
        if rough_img is not None:
            rough_img.name = f"{base_name}_roughness"

    # Metallic: same.
    if m_sep is not None:
        metal_img = _grayscale_from_channel(
            m_tex.image, m_idx, f"{base_name}_metallic")
        if metal_img is None:
            return ("metallic packed image had no pixel data", rough_img, None)
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = metal_img
        node.label = "Metallic"
        node.location = (m_tex.location.x, m_tex.location.y - 320)
        nt.links.new(node.outputs["Color"], metal_in)
        sep_nodes.add(m_sep)
        changed.append(metal_img.name)
    else:
        metal_img = m_tex.image
        if metal_img is not None:
            metal_img.name = f"{base_name}_metallic"

    # Clean up each Separate Color node (and its packed texture/image) only
    # where nothing else uses it now — an ORM node still feeding occlusion,
    # or a shared image, is kept.
    for sep in sep_nodes:
        tex = None
        if sep.inputs and sep.inputs[0].links:
            tex = sep.inputs[0].links[0].from_node
        if not any(out.links for out in sep.outputs):
            nt.nodes.remove(sep)
            if tex is not None and not any(out.links for out in tex.outputs):
                img = tex.image
                nt.nodes.remove(tex)
                if img is not None and img.users == 0:
                    bpy.data.images.remove(img)

    if changed:
        logger.info(
            "[ModelIO] Split packed PBR maps for '%s' -> %s",
            mat.name, ", ".join(changed),
        )
    return (None, rough_img, metal_img)


def _resolve_channel_source(socket):
    """Resolve a BSDF Roughness/Metallic input to its packed source.

    Returns ``(tex_node, sep_node, channel_idx)`` where *sep_node* is the
    Separate Color node (``None`` if the input already reads a dedicated image
    directly, i.e. nothing to split), or ``None`` when the input is unlinked or
    driven by something this splitter does not understand.
    """
    if not socket.links:
        return None
    link = socket.links[0]
    node = link.from_node

    # Already a dedicated image straight into the socket — nothing to split.
    if node.bl_idname == "ShaderNodeTexImage":
        return (node, None, None) if node.image is not None else None

    # <Image> -> Separate Color -> <channel> -> BSDF (the packed case).
    if node.bl_idname in _SEPARATE_COLOR_IDS:
        idx = _SOCKET_TO_CHANNEL.get(link.from_socket.name)
        if idx is not None and node.inputs and node.inputs[0].links:
            up = node.inputs[0].links[0].from_node
            if up.bl_idname == "ShaderNodeTexImage" and up.image is not None:
                return (up, node, idx)
    return None


def _describe_input(socket):
    """Compact description of what drives *socket*, for diagnostic logging."""
    if not socket.links:
        return "unlinked"
    link = socket.links[0]
    node = link.from_node
    desc = f"{node.bl_idname}.{link.from_socket.name}"
    if node.inputs and node.inputs[0].links:
        up = node.inputs[0].links[0].from_node
        img = getattr(getattr(up, "image", None), "name", "")
        desc += f"<-{up.bl_idname}" + (f"({img})" if img else "")
    return desc


def _grayscale_from_channel(src_img, channel_idx, name):
    """New packed grayscale Non-Color image from one channel of *src_img*."""
    import numpy as np

    w, h = src_img.size
    if not w or not h:
        logger.warning(
            "[ModelIO] Packed image '%s' has no pixel data; skipping split",
            getattr(src_img, "name", "?"),
        )
        return None

    # glTF-imported images are PACKED but lazily decoded: `size` comes from
    # metadata, but the pixel buffer (ImBuf) is not acquired until the image is
    # displayed/used — so `foreach_get` here would copy an all-zero buffer,
    # producing a completely BLACK split roughness/metallic map. Realize the
    # buffer first. Idioms: image_utils.image_to_png_bytes uses reload() for
    # not-decoded packed images; bake ops touch pixels[0] to force acquisition.
    if not getattr(src_img, "has_data", True):
        try:
            src_img.reload()
        except Exception:
            pass
    # Roughness/metallic are DATA maps — read as Non-Color so no sRGB->linear
    # decode corrupts the values.
    if src_img.colorspace_settings.name != 'Non-Color':
        try:
            src_img.colorspace_settings.name = 'Non-Color'
        except Exception:
            pass
    try:
        _ = src_img.pixels[0]  # force ImBuf acquisition before foreach_get
    except Exception:
        pass

    n = w * h
    src = np.empty(n * 4, dtype=np.float32)
    src_img.pixels.foreach_get(src)
    val = src.reshape(n, 4)[:, channel_idx]

    out = np.empty((n, 4), dtype=np.float32)
    out[:, 0] = val
    out[:, 1] = val
    out[:, 2] = val
    out[:, 3] = 1.0

    img = bpy.data.images.new(
        name, width=w, height=h, alpha=False,
        float_buffer=bool(getattr(src_img, "is_float", False)),
    )
    # Colorspace BEFORE writing pixels so the raw values aren't round-tripped
    # through a color transform.
    img.colorspace_settings.name = 'Non-Color'
    img.pixels.foreach_set(out.ravel())
    img.pack()
    return img
