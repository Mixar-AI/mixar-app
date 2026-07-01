# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev 360 Utility Functions

Pre-processing and post-processing functions for Lookdev 360 texture generation.
Includes material checkpoint, UV unwrap, OBJ export, and texture download.

Paint module integration (MPaint setup, fill layer creation/removal) is in
lookdev360_paint_integration.py.
"""

import bpy
import json
import os
import tempfile
import datetime
import uuid

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# PRE-PROCESSING FUNCTIONS
# =============================================================================


def save_material_checkpoint(objects: list) -> str:
    """
    Save material state for selected objects as JSON.

    Args:
        objects: List of Blender mesh objects to checkpoint

    Returns:
        JSON string of the checkpoint data
    """
    checkpoint = {
        "objects": {},
        "timestamp": datetime.datetime.now().isoformat(),
    }

    for obj in objects:
        if obj.type != 'MESH':
            continue

        obj_data = {
            "material_slots": [],
            "active_material_index": obj.active_material_index,
            "uv_layers": [],
        }

        # Store material slot information
        for i, slot in enumerate(obj.material_slots):
            slot_data = {
                "index": i,
                "name": slot.name,
                "material_name": slot.material.name if slot.material else None,
                "link": slot.link,
            }
            obj_data["material_slots"].append(slot_data)

        # Store UV layer names
        if obj.data and obj.data.uv_layers:
            for uv_layer in obj.data.uv_layers:
                obj_data["uv_layers"].append(uv_layer.name)

        checkpoint["objects"][obj.name] = obj_data

    return json.dumps(checkpoint, indent=2)


def ensure_uv_unwrap(obj) -> bool:
    """
    Check if object has UV map, create via Smart UV Project if missing.

    Args:
        obj: Blender mesh object to check/unwrap

    Returns:
        True if UV exists or was created, False on failure
    """
    if obj.type != 'MESH':
        return False

    if not obj.data:
        return False

    # Check if UV layers exist
    if obj.data.uv_layers and len(obj.data.uv_layers) > 0:
        logger.debug("[Lookdev360] Object '%s' already has UV map", obj.name)
        return True

    logger.debug("[Lookdev360] Creating UV map for '%s' using Smart UV Project", obj.name)

    # Store current mode and selection
    original_mode = obj.mode if hasattr(obj, 'mode') else 'OBJECT'
    original_active = bpy.context.view_layer.objects.active

    try:
        # Set object as active and select it
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Add UV layer if none exist
        if len(obj.data.uv_layers) == 0:
            obj.data.uv_layers.new(name="UVMap")

        # Enter edit mode
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='VERT')
        bpy.ops.mesh.select_all(action='SELECT')

        # Run Smart UV Project
        bpy.ops.uv.smart_project(
            angle_limit=66.0,
            island_margin=0.02,
            correct_aspect=True,
        )

        logger.debug("[Lookdev360] UV map created for '%s'", obj.name)
        return True

    except Exception as e:
        logger.error("[Lookdev360] Failed to create UV map for '%s': %s", obj.name, e)
        return False

    finally:
        # Always return to object mode, then restore the original active object.
        # Do not restore original_mode: callers expect OBJECT mode on exit.
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass
        bpy.context.view_layer.objects.active = original_active


def export_objects_to_obj(objects: list) -> tuple:
    """
    Export selected objects to temporary OBJ file.

    Args:
        objects: List of Blender mesh objects to export

    Returns:
        Tuple of (filepath, success)
    """
    if not objects:
        logger.warning("[Lookdev360] No objects to export")
        return None, False

    # Create temp directory
    temp_dir = os.path.join(tempfile.gettempdir(), 'blender_lookdev360')
    os.makedirs(temp_dir, exist_ok=True)

    # Generate unique filename
    temp_filename = f"mixar_360_lookdev_{uuid.uuid4().hex}.obj"
    temp_path = os.path.join(temp_dir, temp_filename)

    # Store original selection
    original_selection = [o for o in bpy.context.selected_objects]
    original_active = bpy.context.view_layer.objects.active

    try:
        # Deselect all
        bpy.ops.object.select_all(action='DESELECT')

        # Select only mesh objects to export
        mesh_objects = [obj for obj in objects if obj.type == 'MESH']
        if not mesh_objects:
            logger.warning("[Lookdev360] No mesh objects in selection")
            return None, False

        for obj in mesh_objects:
            obj.select_set(True)

        bpy.context.view_layer.objects.active = mesh_objects[0]

        # Export OBJ
        bpy.ops.wm.obj_export(
            filepath=temp_path,
            export_selected_objects=True,
            export_uv=True,
            export_normals=True,
            export_materials=False,
        )

        if os.path.exists(temp_path):
            file_size = os.path.getsize(temp_path) / 1024
            logger.debug("[Lookdev360] Exported OBJ (%.1f KB)", file_size)
            return temp_path, True
        else:
            logger.error("[Lookdev360] OBJ export failed - file not created")
            return None, False

    except Exception as e:
        logger.error("[Lookdev360] OBJ export failed: %s", e)
        return None, False

    finally:
        # Restore original selection
        bpy.ops.object.select_all(action='DESELECT')
        for obj in original_selection:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = original_active


# =============================================================================
# POST-PROCESSING FUNCTIONS
# =============================================================================


def download_texture_to_tempfile(url: str) -> str:
    """Download a texture image from URL to a temp file.

    Thread-safe (no ``bpy`` access) — this is the half of the old
    ``download_texture_from_url`` that may run on a background thread.

    Returns:
        Path to the temp file. The caller owns it; ``load_texture_from_file``
        removes it after loading.
    """
    import urllib.request

    logger.debug("[Lookdev360] Downloading texture...")
    with urllib.request.urlopen(url, timeout=60) as response:
        image_bytes = response.read()
    logger.debug("[Lookdev360] Downloaded %s bytes", len(image_bytes))

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        f.write(image_bytes)
        return f.name


def load_texture_from_file(temp_path: str, name: str) -> bpy.types.Image:
    """Load + pack a downloaded texture and remove the temp file.

    MAIN THREAD ONLY: creating, renaming, and packing image datablocks
    mutates ``bpy.data``, which is not thread-safe.

    Args:
        temp_path: Path returned by ``download_texture_to_tempfile``
        name: Name for the loaded image

    Returns:
        Blender Image object
    """
    try:
        img = bpy.data.images.load(temp_path, check_existing=False)
        img.name = name
        img.pack()
        logger.debug("[Lookdev360] Loaded texture: %s", img.name)
        return img
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def download_texture_from_url(url: str, name: str) -> bpy.types.Image:
    """Download texture image from URL and load into Blender.

    MAIN THREAD ONLY (creates bpy datablocks). Background threads should use
    ``download_texture_to_tempfile`` and defer ``load_texture_from_file`` to
    a main-thread timer.

    Args:
        url: URL to download image from
        name: Name for the loaded image

    Returns:
        Blender Image object
    """
    return load_texture_from_file(download_texture_to_tempfile(url), name)


# Paint module integration functions re-exported from dedicated module
from .lookdev360_paint_integration import (  # noqa: F401, E402
    check_or_create_mpaint_setup,
    add_lookdev360_fill_layer,
    remove_lookdev360_fill_layer,
)
def create_lookdev360_material(
    albedo_img: bpy.types.Image,
    roughness_img: bpy.types.Image = None,
    metallic_img: bpy.types.Image = None,
    normal_img: bpy.types.Image = None,
    material_name: str = "Lookdev360_Material"
) -> bpy.types.Material:
    """
    Create Principled BSDF material with texture maps.

    Args:
        albedo_img: Albedo/BaseColor texture image (required)
        roughness_img: Roughness texture image (optional)
        metallic_img: Metallic texture image (optional)
        normal_img: Normal map texture image (optional)
        material_name: Name for the created material

    Returns:
        Created Blender Material
    """
    # Create or get material
    mat = bpy.data.materials.get(material_name)
    if mat:
        # Clear existing nodes
        mat.node_tree.nodes.clear()
    else:
        mat = bpy.data.materials.new(name=material_name)

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Clear default nodes
    nodes.clear()

    # Create nodes
    # Output
    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    output_node.location = (400, 0)

    # Principled BSDF
    bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf_node.location = (0, 0)

    # UV Map node (shared)
    uv_node = nodes.new(type='ShaderNodeUVMap')
    uv_node.location = (-800, 0)

    # Albedo/BaseColor texture (required)
    albedo_node = nodes.new(type='ShaderNodeTexImage')
    albedo_node.location = (-600, 300)
    albedo_node.image = albedo_img
    albedo_node.label = "BaseColor"
    links.new(uv_node.outputs['UV'], albedo_node.inputs['Vector'])
    links.new(albedo_node.outputs['Color'], bsdf_node.inputs['Base Color'])

    # Roughness texture (optional)
    if roughness_img:
        roughness_node = nodes.new(type='ShaderNodeTexImage')
        roughness_node.location = (-600, 0)
        roughness_node.image = roughness_img
        roughness_node.image.colorspace_settings.name = 'Non-Color'
        roughness_node.label = "Roughness"
        links.new(uv_node.outputs['UV'], roughness_node.inputs['Vector'])
        links.new(roughness_node.outputs['Color'], bsdf_node.inputs['Roughness'])

    # Metallic texture (optional)
    if metallic_img:
        metallic_node = nodes.new(type='ShaderNodeTexImage')
        metallic_node.location = (-600, -300)
        metallic_node.image = metallic_img
        metallic_node.image.colorspace_settings.name = 'Non-Color'
        metallic_node.label = "Metallic"
        links.new(uv_node.outputs['UV'], metallic_node.inputs['Vector'])
        links.new(metallic_node.outputs['Color'], bsdf_node.inputs['Metallic'])

    # Normal map texture (optional)
    if normal_img:
        normal_tex_node = nodes.new(type='ShaderNodeTexImage')
        normal_tex_node.location = (-600, -600)
        normal_tex_node.image = normal_img
        normal_tex_node.image.colorspace_settings.name = 'Non-Color'
        normal_tex_node.label = "Normal"
        links.new(uv_node.outputs['UV'], normal_tex_node.inputs['Vector'])

        # Normal Map node to convert texture to normal
        normal_map_node = nodes.new(type='ShaderNodeNormalMap')
        normal_map_node.location = (-300, -600)
        links.new(normal_tex_node.outputs['Color'], normal_map_node.inputs['Color'])
        links.new(normal_map_node.outputs['Normal'], bsdf_node.inputs['Normal'])

    # BSDF to Output
    links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])

    logger.debug("[Lookdev360] Created material: %s", mat.name)
    return mat


def apply_material_to_objects(material: bpy.types.Material, objects: list) -> None:
    """
    Apply generated material to all target objects.

    Args:
        material: Material to apply
        objects: List of mesh objects to apply material to
    """
    for obj in objects:
        if obj.type != 'MESH':
            continue

        # Clear existing material slots
        obj.data.materials.clear()

        # Add new material
        obj.data.materials.append(material)

        logger.debug("[Lookdev360] Applied material to: %s", obj.name)

    # Pack all textures
    bpy.ops.file.pack_all()
    logger.debug("[Lookdev360] Packed all textures")


def restore_material_checkpoint(checkpoint_json: str) -> bool:
    """
    Restore original materials from saved checkpoint.

    Args:
        checkpoint_json: JSON string of checkpoint data

    Returns:
        True if successful, False otherwise
    """
    if not checkpoint_json:
        logger.warning("[Lookdev360] No checkpoint data to restore")
        return False

    try:
        checkpoint = json.loads(checkpoint_json)
    except json.JSONDecodeError as e:
        logger.error("[Lookdev360] Failed to parse checkpoint: %s", e)
        return False

    objects_data = checkpoint.get("objects", {})
    restored_count = 0

    for obj_name, obj_data in objects_data.items():
        obj = bpy.data.objects.get(obj_name)
        if not obj or obj.type != 'MESH':
            logger.warning("[Lookdev360] Object not found or not mesh: %s", obj_name)
            continue

        # Clear current materials
        obj.data.materials.clear()

        # Restore material slots
        for slot_data in obj_data.get("material_slots", []):
            mat_name = slot_data.get("material_name")
            if mat_name:
                mat = bpy.data.materials.get(mat_name)
                if mat:
                    obj.data.materials.append(mat)
                else:
                    # Material was deleted, add empty slot
                    obj.data.materials.append(None)
            else:
                # Original slot was empty
                obj.data.materials.append(None)

        # Restore active material index
        active_idx = obj_data.get("active_material_index", 0)
        if active_idx < len(obj.material_slots):
            obj.active_material_index = active_idx

        restored_count += 1
        logger.debug("[Lookdev360] Restored materials for: %s", obj_name)

    logger.debug("[Lookdev360] Restored %s object(s)", restored_count)
    return restored_count > 0


def get_selected_mesh_objects() -> list:
    """Get list of selected mesh objects."""
    return [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']


def count_objects_without_uv(objects: list) -> int:
    """Count how many objects don't have UV maps."""
    count = 0
    for obj in objects:
        if obj.type == 'MESH' and obj.data:
            if not obj.data.uv_layers or len(obj.data.uv_layers) == 0:
                count += 1
    return count
