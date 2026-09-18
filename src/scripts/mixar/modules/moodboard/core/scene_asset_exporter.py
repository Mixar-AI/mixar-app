# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Asset Exporter

Exports scene reconstruction meshes to a Blender asset library so they
can be discovered by the Asset Browser and the asset-fill system.
"""

import os
import re
import uuid

import bpy
from mathutils import Matrix, Vector

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _slugify(text):
    """Convert label to a filesystem-safe slug: lowercase, hyphens, no specials."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-") or "object"


def _ensure_catalog_entry(library_path, label):
    """Ensure a catalog entry exists in blender_assets.cats.txt.

    Returns the catalog UUID string for the entry.
    If the label already exists, reuses its UUID; otherwise appends a new line.
    """
    cats_path = os.path.join(library_path, "blender_assets.cats.txt")
    catalog_path = label.title()

    # Parse existing file
    lines = []
    existing_uuid = None
    if os.path.isfile(cats_path):
        with open(cats_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#") or line_stripped.startswith("VERSION"):
                continue
            parts = line_stripped.split(":", 2)
            if len(parts) >= 2 and parts[1].strip() == catalog_path:
                existing_uuid = parts[0].strip()
                break

    if existing_uuid:
        return existing_uuid

    # Generate new entry
    cat_uuid = str(uuid.uuid4())
    new_line = f"{cat_uuid}:{catalog_path}:{catalog_path}\n"

    if not lines:
        # Create file from scratch
        with open(cats_path, "w", encoding="utf-8") as f:
            f.write("# This is an Asset Catalog Definition file for Blender.\n")
            f.write("VERSION 1\n\n")
            f.write(new_line)
    else:
        with open(cats_path, "a", encoding="utf-8") as f:
            f.write(new_line)

    return cat_uuid


def _create_clean_copy(obj, asset_name=None):
    """Create a clean standalone mesh copy for asset export.

    - Bakes the full world transform into mesh vertices
    - No parent-child relationships
    - Centered at bounding-box center with identity transform
    - Materials and textures preserved

    ``asset_name`` overrides the copy's datablock name (the SEARCHABLE asset
    name); defaults to the source object's name. Callers that archive many
    same-typed objects (e.g. generations) pass a unique name so the embedding
    index — keyed on (name, library, blend_file) — doesn't collide.

    Returns the temporary object (caller must clean up via _remove_temp).
    """
    # Deep copy mesh data (preserves materials, UVs, vertex colors)
    clean_mesh = obj.data.copy()

    # Bake world transform into vertices
    clean_mesh.transform(obj.matrix_world)

    # Center geometry at origin
    verts = clean_mesh.vertices
    if len(verts) > 0:
        coords = [v.co for v in verts]
        bbox_min = Vector((
            min(c.x for c in coords),
            min(c.y for c in coords),
            min(c.z for c in coords),
        ))
        bbox_max = Vector((
            max(c.x for c in coords),
            max(c.y for c in coords),
            max(c.z for c in coords),
        ))
        center = (bbox_min + bbox_max) / 2
        clean_mesh.transform(Matrix.Translation(-center))

    name = asset_name or obj.name
    clean_mesh.name = name
    # Create standalone object at origin with identity transform
    clean_obj = bpy.data.objects.new(name, clean_mesh)
    return clean_obj


def _remove_temp(clean_obj):
    """Remove the temporary object and its mesh data from bpy.data."""
    mesh = clean_obj.data
    bpy.data.objects.remove(clean_obj, do_unlink=True)
    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _collect_datablocks(clean_obj):
    """Collect datablocks from a single clean mesh object."""
    blocks = {clean_obj, clean_obj.data}

    for mat in clean_obj.data.materials:
        if not mat:
            continue
        blocks.add(mat)
        if not mat.use_nodes or not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                blocks.add(node.image)

    return blocks


def _attach_preview(clean_obj):
    """Render a 512² thumbnail and embed it as the asset's datablock preview.

    Reuses the same rig as the embedding-training flow (EEVEE, transparent
    film, 3/4-view camera, key/fill lights) so generated assets (e.g.
    image-to-3D results) get a real thumbnail instead of the placeholder
    icon. The preview is written into the .blend by the caller's
    ``libraries.write`` — no extra file I/O.

    Best-effort: any failure (missing context, render error) leaves the
    asset preview-less rather than aborting the export.
    """
    try:
        from mixar.modules.asset_search.utils.preview_render import (
            PreviewRenderRig,
            frame_camera,
            render_to_image,
        )
    except Exception as e:
        logger.debug("[AssetExporter] Preview helpers unavailable: %s", e)
        return

    scene = bpy.context.scene
    if scene is None:
        return

    img = None
    linked = False
    try:
        with PreviewRenderRig(scene, size=512) as rig:
            scene.collection.objects.link(clean_obj)
            linked = True
            bpy.context.view_layer.update()
            frame_camera(rig.camera, [clean_obj])
            # pack=True so the pixels survive render_to_image deleting its temp file
            img = render_to_image(scene, f"_asset_preview_{clean_obj.name}", pack=True)

        if not img:
            return
        w, h = img.size
        if not (w and h):
            return
        pixels = [0.0] * (w * h * 4)
        img.pixels.foreach_get(pixels)
        preview = clean_obj.preview_ensure()
        preview.image_size = (w, h)
        preview.image_pixels_float.foreach_set(pixels)
        logger.debug(
            "[AssetExporter] Attached %dx%d preview to '%s'", w, h, clean_obj.name
        )
    except Exception as e:
        logger.debug(
            "[AssetExporter] Preview render failed for '%s': %s", clean_obj.name, e
        )
    finally:
        if linked and clean_obj.name in bpy.data.objects:
            try:
                scene.collection.objects.unlink(clean_obj)
            except Exception:
                pass
        if img is not None:
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass


def export_object_to_asset_library(
    obj, label, library_path, *, asset_name=None, description="", tags=None
):
    """Export a Blender object to an asset library as a clean .blend file.

    The exported asset is a flat mesh (no hierarchy, no empties) with its
    world transform baked into the vertices and centered at the origin.

    Args:
        obj: The Blender object to export (must be MESH type).
        label: Human-readable label for the asset (e.g. "wooden table").
        library_path: Root directory of the asset library.
        asset_name: Override for the SEARCHABLE asset (datablock) name. Defaults
            to the source object's name. Pass a unique value when archiving many
            same-typed objects so the embedding index doesn't collide on name.
        description: Optional asset description (feeds embedding-search text).
        tags: Optional list of tag strings (also feed embedding-search text).

    Returns:
        True on success, False on failure.
    """
    if not obj or not label or not library_path:
        return False

    if obj.type != "MESH":
        logger.debug("[AssetExporter] Skipping non-mesh object '%s' (type=%s)", obj.name, obj.type)
        return False

    library_path = bpy.path.abspath(library_path)
    if not os.path.isdir(library_path):
        logger.error("[AssetExporter] Library path does not exist")
        return False

    slug = _slugify(label)
    unique_dir = f"{slug}_{uuid.uuid4().hex[:8]}"
    asset_dir = os.path.join(library_path, "assets", "models", unique_dir)

    try:
        os.makedirs(asset_dir, exist_ok=True)
    except OSError as e:
        logger.error("[AssetExporter] Failed to create directory: %s", e)
        return False

    # Ensure catalog entry
    try:
        catalog_id = _ensure_catalog_entry(library_path, label)
    except Exception as e:
        logger.error("[AssetExporter] Catalog error: %s", e)
        catalog_id = None

    # Create a clean, flat copy (no hierarchy, baked transform, at origin)
    clean_obj = _create_clean_copy(obj, asset_name=asset_name)

    # Mark the clean copy as asset
    clean_obj.asset_mark()
    if catalog_id and clean_obj.asset_data:
        clean_obj.asset_data.catalog_id = catalog_id
    # Optional metadata — improves embedding-search relevance (name alone is
    # often generic for generated meshes).
    if clean_obj.asset_data:
        if description:
            try:
                clean_obj.asset_data.description = description
            except Exception:
                pass
        for tag in (tags or []):
            if tag:
                try:
                    clean_obj.asset_data.tags.new(str(tag), skip_if_exists=True)
                except TypeError:
                    clean_obj.asset_data.tags.new(str(tag))
                except Exception:
                    pass

    # Best-effort: render a thumbnail and embed it as the asset preview so
    # library assets (e.g. image-to-3D generations) aren't preview-less.
    _attach_preview(clean_obj)

    # Collect datablocks from the clean copy only
    datablocks = _collect_datablocks(clean_obj)

    # Write .blend file
    blend_path = os.path.join(asset_dir, f"{slug}.blend")
    try:
        bpy.data.libraries.write(blend_path, datablocks, fake_user=True)
        logger.debug("[AssetExporter] Saved asset '%s'", label)
    except Exception as e:
        logger.error("[AssetExporter] Failed to write asset: %s", e)
        _remove_temp(clean_obj)
        return False

    # Clean up temporary object
    _remove_temp(clean_obj)
    return True
