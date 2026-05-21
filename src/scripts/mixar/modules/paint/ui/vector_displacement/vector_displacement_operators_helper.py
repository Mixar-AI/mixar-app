# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from mathutils import Vector
import numpy

from .....config.logging_config import get_logger
from ...core.element.get_elements import get_subsurf_modifier
from ...core.layer.get_channels import get_height_channel
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import (
    link_object,
    remove_mesh_obj,
    set_active_object,
    set_object_select,
)
from ...utils.common import get_entity_prop_value
from ..bake.utils.bake_scene_settings import (
    get_scene_bake_clear,
    get_scene_bake_margin,
    get_scene_bake_multires,
    get_scene_render_bake_type,
)
from ..vector_displacement.vector_displacement_lib import (
    OFFSET_ATTR,
    get_offset_bake_mat,
    get_vdm_loader_geotree,
)
from .vector_displacement_utils import (
    get_combined_vdm_image,
    get_tangent_bitangent_images,
)
from .vector_displacement_utils import (
    _prepare_bake_settings,
    _recover_bake_settings,
    _remember_before_bake,
)

logger = get_logger(__name__)


def _remember_before_bake(obj):
    """Store current scene and object settings before baking.

    Args:
        obj (bpy.types.Object): The object being prepared for baking.

    Returns:
        dict: Dictionary containing all saved settings.
    """
    book = {}
    book["scene"] = scene = bpy.context.scene
    book["obj"] = obj
    book["mode"] = obj.mode
    uv_layers = obj.data.uv_layers
    mpui = bpy.context.window_manager.mpui

    # Remember render settings
    book["ori_engine"] = scene.render.engine
    book["ori_bake_type"] = scene.cycles.bake_type
    book["ori_samples"] = scene.cycles.samples
    book["ori_threads_mode"] = scene.render.threads_mode
    book["ori_margin"] = scene.render.bake.margin
    book["ori_margin_type"] = scene.render.bake.margin_type
    book["ori_use_clear"] = scene.render.bake.use_clear
    book["ori_normal_space"] = scene.render.bake.normal_space
    book["ori_simplify"] = scene.render.use_simplify
    book["ori_device"] = scene.cycles.device
    book["ori_use_selected_to_active"] = scene.render.bake.use_selected_to_active
    book["ori_max_ray_distance"] = scene.render.bake.max_ray_distance
    book["ori_cage_extrusion"] = scene.render.bake.cage_extrusion
    book["ori_use_cage"] = scene.render.bake.use_cage
    book["ori_use_denoising"] = scene.cycles.use_denoising
    book["ori_bake_target"] = scene.render.bake.target
    book["ori_material_override"] = bpy.context.view_layer.material_override

    # Multires related
    book["ori_use_bake_multires"] = get_scene_bake_multires(scene)
    book["ori_use_bake_clear"] = get_scene_bake_clear(scene)
    book["ori_render_bake_type"] = get_scene_render_bake_type(scene)
    book["ori_bake_margin"] = get_scene_bake_margin(scene)
    book["ori_view_transform"] = scene.view_settings.view_transform

    # Remember world settings
    if scene.world:
        book["ori_distance"] = scene.world.light_settings.distance

    # Remember image editor images
    book["editor_images"] = [
        a.spaces[0].image for a in bpy.context.screen.areas if a.type == "IMAGE_EDITOR"
    ]
    book["editor_pins"] = [
        a.spaces[0].use_image_pin
        for a in bpy.context.screen.areas
        if a.type == "IMAGE_EDITOR"
    ]

    # Remember uv
    book["ori_active_uv"] = uv_layers.active.name
    active_render_uvs = [u for u in uv_layers if u.active_render]
    if active_render_uvs:
        book["ori_active_render_uv"] = active_render_uvs[0].name

    return book


def get_offset_attributes(base, sclupted_mesh, layer_disabled_mesh=None, intensity=1.0):
    """Calculate offset attributes between base and sculpted mesh.

    Args:
        base (bpy.types.Object): The base mesh object.
        sclupted_mesh (bpy.types.Object): The sculpted mesh object.
        layer_disabled_mesh (bpy.types.Object, optional): Mesh with current layer disabled. Defaults to None.
        intensity (float, optional): Displacement intensity to divide by. Defaults to 1.0.

    Returns:
        tuple[bpy.types.Attribute or None, float or None]: Tuple of (offset_attribute, max_value), or (None, None) if vertex counts don't match.
    """
    logger.info("Getting offset attributes...")

    if len(base.data.vertices) != len(sclupted_mesh.data.vertices):
        return None, None

    # Get coordinates for each vertices
    base_arr = numpy.zeros(len(base.data.vertices) * 3, dtype=numpy.float32)
    base.data.vertices.foreach_get("co", base_arr)

    sculpted_arr = numpy.zeros(
        len(sclupted_mesh.data.vertices) * 3, dtype=numpy.float32
    )
    sclupted_mesh.data.vertices.foreach_get("co", sculpted_arr)

    if layer_disabled_mesh:

        layer_disabled_arr = numpy.zeros(
            len(layer_disabled_mesh.data.vertices) * 3, dtype=numpy.float32
        )
        layer_disabled_mesh.data.vertices.foreach_get("co", layer_disabled_arr)

        sculpted_arr = numpy.subtract(sculpted_arr, base_arr)
        layer_disabled_arr = numpy.subtract(layer_disabled_arr, base_arr)

        # Subtract to get offset
        offset = numpy.subtract(sculpted_arr, layer_disabled_arr)

        # Free numpy memory
        del layer_disabled_arr

    else:
        offset = numpy.subtract(sculpted_arr, base_arr)

    if intensity != 1.0 or intensity != 0.0:
        offset = numpy.divide(offset, intensity)

    max_value = numpy.abs(offset).max()
    offset.shape = (offset.shape[0] // 3, 3)

    # Create new attribute to store the offset
    att = base.data.attributes.get(OFFSET_ATTR)
    if not att:
        att = base.data.attributes.new(OFFSET_ATTR, "FLOAT_VECTOR", "POINT")
    att.data.foreach_set("vector", offset.ravel())

    # Free numpy array memory just in case
    del base_arr
    del sculpted_arr
    del offset

    logger.info("Getting offset attributes finished!")

    return att, max_value


def bake_multires_image(obj, image, uv_name, intensity=1.0):
    """Bake multires sculpt data to a vector displacement image.

    Args:
        obj (bpy.types.Object): The object with multires modifier to bake.
        image (bpy.types.Image): The target image to bake to.
        uv_name (str): Name of the UV map to use for baking.
        intensity (float, optional): Displacement intensity multiplier. Defaults to 1.0.
    """
    context = bpy.context
    scene = context.scene

    # Get combined but active layer disabled image
    layer_disabled_vdm_image = None
    node = get_active_mpaint_node(obj)
    if node:
        mp = node.node_tree.mp
        if is_multi_disp_used(mp):
            layer_disabled_vdm_image = get_combined_vdm_image(
                obj,
                uv_name,
                width=image.size[0],
                height=image.size[1],
                disable_current_layer=True,
            )

    set_active_object(obj)
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    if len(context.selected_objects) > 1:
        bpy.ops.object.select_all(action="DESELECT")
    if not obj.select_get():
        set_object_select(obj, True)

    # Disable other modifiers
    ori_mod_show_viewport = []
    ori_mod_show_render = []
    for mod in obj.modifiers:
        if mod.type == "MULTIRES" or mod.type == "SUBSURF":
            continue
        if mod.show_viewport:
            mod.show_viewport = False
            ori_mod_show_viewport.append(mod.name)
        if mod.show_render:
            mod.show_render = False
            ori_mod_show_render.append(mod.name)

    # Temp object 0: Base
    temp0 = obj.copy()
    link_object(scene, temp0)
    temp0.data = temp0.data.copy()
    temp0.location = obj.location + Vector(((obj.dimensions[0] + 0.1) * 1, 0.0, 0.0))

    # Delete multires and shape keys
    set_active_object(temp0)
    if temp0.data.shape_keys:
        bpy.ops.object.shape_key_remove(all=True)
    max_level = 0
    for mod in temp0.modifiers:
        if mod.type == "MULTIRES":
            max_level = mod.total_levels
            bpy.ops.object.modifier_remove(modifier=mod.name)
            break

    # Disable use simplify before apply modifier
    ori_use_simplify = scene.render.use_simplify
    scene.render.use_simplify = False

    # Apply subsurf
    tsubsurf = get_subsurf_modifier(temp0)
    if not tsubsurf:
        bpy.ops.object.modifier_add(type="SUBSURF")
        tsubsurf = [m for m in temp0.modifiers if m.type == "SUBSURF"][0]
    tsubsurf.show_viewport = True
    tsubsurf.levels = max_level
    tsubsurf.render_levels = max_level
    bpy.ops.object.modifier_apply(modifier=tsubsurf.name)

    # Temp object 2: Sculpted/Multires mesh
    temp2 = obj.copy()
    link_object(scene, temp2)
    temp2.data = temp2.data.copy()
    temp2.location = obj.location + Vector(((obj.dimensions[0] + 0.1) * 3, 0.0, 0.0))

    # Apply multires
    set_active_object(temp2)
    if temp2.data.shape_keys:
        bpy.ops.object.shape_key_remove(all=True)
    for mod in temp2.modifiers:
        if mod.type == "MULTIRES":
            mod.levels = max_level
            bpy.ops.object.modifier_apply(modifier=mod.name)
            break

    # Get tangent and bitangent images
    tanimage, bitimage = get_tangent_bitangent_images(obj, uv_name)

    # Temp object 1: Half combined vdm mesh
    temp1 = None
    if layer_disabled_vdm_image:
        temp1 = temp0.copy()
        link_object(scene, temp1)
        temp1.data = temp1.data.copy()
        temp1.location = obj.location + Vector(
            ((obj.dimensions[0] + 0.1) * 2, 0.0, 0.0)
        )
        set_active_object(temp1)

        vdm_loader = get_vdm_loader_geotree(
            uv_name, layer_disabled_vdm_image, tanimage, bitimage
        )
        bpy.ops.object.modifier_add(type="NODES")
        geomod = temp1.modifiers[-1]
        geomod.node_group = vdm_loader
        temp1.modifiers.active = geomod

        # Apply geomod
        bpy.ops.object.modifier_apply(modifier=geomod.name)

        # Remove vdm loader group
        bpy.data.node_groups.remove(vdm_loader)

    # Calculate offset from two temp objects
    att, max_value = get_offset_attributes(temp0, temp2, temp1, intensity)

    # Set material to temp object 0
    temp0.data.materials.clear()
    mat = get_offset_bake_mat(uv_name, target_image=image, bitangent_image=bitimage)
    temp0.data.materials.append(mat)

    # Bake preparations
    book = _remember_before_bake(obj)
    _prepare_bake_settings(book, temp0, uv_name)

    # Bake offest
    logger.info("Baking vdm...")
    bpy.ops.object.bake()
    logger.info("Baking vdm is finished!")

    # Pack image
    # image.pack()

    # Recover use simplify
    if ori_use_simplify:
        scene.render.use_simplify = True

    # Recover bake settings
    _recover_bake_settings(book, True)

    # Remove temp data
    remove_mesh_obj(temp0)
    remove_mesh_obj(temp2)
    if temp1:
        remove_mesh_obj(temp1)
    # bpy.data.images.remove(tanimage)
    # bpy.data.images.remove(bitimage)
    if layer_disabled_vdm_image:
        bpy.data.images.remove(layer_disabled_vdm_image)

    # Remove material
    if mat.users <= 1:
        bpy.data.materials.remove(mat, do_unlink=True)

    # Recover disabled modifiers
    for mod in obj.modifiers:
        if mod.name in ori_mod_show_viewport:
            mod.show_viewport = True
        if mod.name in ori_mod_show_render:
            mod.show_render = True

    # Set back object to active
    set_active_object(obj)
    set_object_select(obj, True)
   
def get_vdm_intensity(layer, ch):
    """Calculate the total VDM intensity from layer and channel properties.

    Args:
        layer: The layer object containing intensity properties.
        ch: The channel object containing intensity and strength properties.

    Returns:
        float: Combined intensity value (layer_intensity * channel_intensity * channel_strength).
    """
    layer_intensity = get_entity_prop_value(layer, "intensity_value")
    ch_intensity = get_entity_prop_value(ch, "intensity_value")
    ch_strength = get_entity_prop_value(ch, "vdisp_strength")
    return layer_intensity * ch_intensity * ch_strength


def is_multi_disp_used(mp):
    """Check if multiple displacement layers are being used.

    Args:
        mp: The mpaint object containing layer information.

    Returns:
        bool: True if more than one displacement layer is enabled, False otherwise.
    """
    num_disps = 0

    # Check if there's another vdm layer
    for l in mp.layers:
        if not l.enable:
            continue
        hch = get_height_channel(l)
        if (
            not hch
            or not hch.enable
            or hch.normal_map_type
            not in {"BUMP_MAP", "BUMP_NORMAL_MAP", "VECTOR_DISPLACEMENT_MAP"}
        ):
            continue
        num_disps += 1

    return num_disps > 1
