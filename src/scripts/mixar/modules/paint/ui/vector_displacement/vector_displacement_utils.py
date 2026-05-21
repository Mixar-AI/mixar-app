# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vector displacement utility functions for VDM baking and image generation.

This module provides functions for generating combined vector displacement maps
and baking tangent/bitangent images for VDM operations.
"""

import bpy
from mathutils import Vector
import numpy

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.get_elements import (
    get_mesh_hash,
    get_subsurf_modifier,
    get_uv_hash,
)
from ...core.layer.check_channels import check_all_channel_ios
from ...core.layer.get_channels import get_height_channel
from ...core.layer.layer_utils import get_root_height_channel, get_uv_layers
from ...core.lib.lib import COMBINED_VDM
from ...core.node.get_nodes import get_active_mat_output_node
from ...core.node.node_utils import get_active_mpaint_node, get_node_tree_lib
from ...utils.blender_commons import (
    get_active_material,
    link_object,
    remove_mesh_obj,
    set_active_object,
    set_object_select,
    simple_remove_node,
)
from ...utils.constants import (
    CACHE_BITANGENT_IMAGE_SUFFIX,
    CACHE_TANGENT_IMAGE_SUFFIX,
    io_suffix,
)
from .bake_settings_helpers import (
    prepare_bake_settings,
    recover_bake_settings,
    remember_before_bake,
)
from .vector_displacement_lib import (
    BSIGN_ATTR,
    get_bitangent_bake_mat,
    get_tangent_bake_mat,
)

# Re-export bake settings functions for backward compatibility
# These are internal functions (prefixed with _) that may be used by other modules
_remember_before_bake = remember_before_bake
_prepare_bake_settings = prepare_bake_settings
_recover_bake_settings = recover_bake_settings


TEMP_MULTIRES_NAME = "_YP_TEMP_MULTIRES"
TEMP_COMBINED_VDM_IMAGE_SUFFIX = "_YP_TEMP_COMBINED_VDM"
TEMP_LAYER_DISABLED_VDM_IMAGE_SUFFIX = "_YP_LAYER_DISABLED_VDM"


def get_combined_vdm_image(
    obj, uv_name, width=1024, height=1024, disable_current_layer=False
):
    """Generate a combined vector displacement map from all enabled VDM layers.

    Args:
        obj (bpy.types.Object): The object to bake VDM for.
        uv_name (str): Name of the UV map to use for baking.
        width (int, optional): Width of the baked image. Defaults to 1024.
        height (int, optional): Height of the baked image. Defaults to 1024.
        disable_current_layer (bool, optional): Whether to disable the current layer. Defaults to False.

    Returns:
        bpy.types.Image or None: The combined VDM image, or None if operation failed.
    """
    # Bake preparations
    book = _remember_before_bake(obj)
    _prepare_bake_settings(book, obj, uv_name)

    mat = get_active_material(obj)
    node = get_active_mpaint_node(obj)
    if not mat or not node:
        return None
    # mtree = mat.tree
    tree = node.node_tree
    mp = tree.mp
    height_root_ch = get_root_height_channel(mp)
    if not height_root_ch:
        return None

    # Get active layer
    try:
        cur_layer = mp.layers[mp.active_layer_index]
    except Exception as e:
        logger.error("Exception: %s", e)
        return None

    # Disable sculpt mode first
    ori_sculpt_mode = mp.sculpt_mode
    if mp.sculpt_mode:
        mp.sculpt_mode = False

    # Disable current layer
    ori_layer_enable = cur_layer.enable
    if disable_current_layer:
        cur_layer.enable = False

    # Disable all flip Y/Z
    ori_flip_yzs = {}
    for i, l in enumerate(mp.layers):
        height_ch = get_height_channel(l)
        if (
            not height_ch.enable
            or height_ch.normal_map_type != "VECTOR_DISPLACEMENT_MAP"
        ):
            continue
        ori_flip_yzs[str(i)] = height_ch.vdisp_enable_flip_yz
        height_ch.vdisp_enable_flip_yz = False

    # Make sure vdm output exists
    if not height_root_ch.enable_subdiv_setup:
        check_all_channel_ios(mp, force_height_io=True)

    # Combined VDM image name
    if disable_current_layer:
        image_name = obj.name + "_" + uv_name + TEMP_LAYER_DISABLED_VDM_IMAGE_SUFFIX
    else:
        image_name = obj.name + "_" + uv_name + TEMP_COMBINED_VDM_IMAGE_SUFFIX

    # Create combined vdm image
    image = bpy.data.images.new(
        name=image_name, width=width, height=height, alpha=False, float_buffer=True
    )
    image.generated_color = (0, 0, 0, 1)

    # Get output node and remember original bsdf input
    mat_out = get_active_mat_output_node(mat.node_tree)
    ori_bsdf = mat_out.inputs[0].links[0].from_socket

    # Create setup nodes
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    emit = mat.node_tree.nodes.new("ShaderNodeEmission")

    # Get combined vdm calculation node
    calc = mat.node_tree.nodes.new("ShaderNodeGroup")
    calc.node_tree = get_node_tree_lib(COMBINED_VDM)

    # Set tex as active node
    mat.node_tree.nodes.active = tex
    tex.image = image

    # Emission connection
    disp_outp = node.outputs.get(height_root_ch.name + io_suffix["HEIGHT"])
    max_height_outp = node.outputs.get(height_root_ch.name + io_suffix["MAX_HEIGHT"])
    vdisp_outp = node.outputs.get(height_root_ch.name + io_suffix["VDISP"])

    # Connection
    # mat.node_tree.links.new(vdisp_outp, emit.inputs[0])
    mat.node_tree.links.new(disp_outp, calc.inputs["Height"])
    mat.node_tree.links.new(max_height_outp, calc.inputs["Scale"])
    mat.node_tree.links.new(vdisp_outp, calc.inputs["Vector Displacement"])
    mat.node_tree.links.new(calc.outputs[0], emit.inputs[0])
    mat.node_tree.links.new(emit.outputs[0], mat_out.inputs[0])

    # Bake!
    bpy.ops.object.bake()

    # Set fake user for the bake result so it won't disappear
    # image.use_fake_user = True
    # image.pack()

    # Recover original bsdf
    mat.node_tree.links.new(ori_bsdf, mat_out.inputs[0])

    # Remove bake nodes
    simple_remove_node(mat.node_tree, tex, remove_data=False)
    simple_remove_node(mat.node_tree, emit)
    simple_remove_node(mat.node_tree, calc)

    # Recover active layer
    if ori_layer_enable != cur_layer.enable:
        cur_layer.enable = ori_layer_enable

    # Recover input outputs
    if not height_root_ch.enable_subdiv_setup:
        check_all_channel_ios(mp)

    # Recover flip yzs
    for key, val in ori_flip_yzs.items():
        l = mp.layers[int(key)]
        height_ch = get_height_channel(l)
        if height_ch.vdisp_enable_flip_yz != val:
            height_ch.vdisp_enable_flip_yz = val

    # Recover sculpt mode
    if ori_sculpt_mode:
        mp.sculpt_mode = True

    # Revover bake settings
    _recover_bake_settings(book, True)

    return image


def get_tangent_bitangent_images(obj, uv_name):
    """Get or bake tangent and bitangent images for the specified object and UV map.

    Args:
        obj (bpy.types.Object): The object to bake tangent/bitangent for.
        uv_name (str): Name of the UV map to use for baking.

    Returns:
        tuple[bpy.types.Image, bpy.types.Image]: Tuple of (tangent_image, bitangent_image).
    """
    tanimage_name = obj.name + "_" + uv_name + CACHE_TANGENT_IMAGE_SUFFIX
    bitimage_name = obj.name + "_" + uv_name + CACHE_BITANGENT_IMAGE_SUFFIX

    tanimage = bpy.data.images.get(tanimage_name)
    bitimage = bpy.data.images.get(bitimage_name)

    # Check mesh hash
    hash_invalid = False
    mh = get_mesh_hash(obj)
    if obj.mp.mesh_hash != mh:
        obj.mp.mesh_hash = mh
        hash_invalid = True
        # print('Hash invalid because of vertices')

    # Check uv hash
    hash_str = get_uv_hash(obj, uv_name)
    uvh = obj.mp.uv_hashes.get(uv_name)
    if not uvh or uvh.uv_hash != hash_str:

        if not uvh:
            uvh = obj.mp.uv_hashes.add()
            uvh.name = uv_name
        uvh.uv_hash = hash_str

        hash_invalid = True
        # print('Hash invalid because of UV')

    # Remove current images if hash doesn't match
    if hash_invalid:
        if tanimage:
            bpy.data.images.remove(tanimage)
        if bitimage:
            bpy.data.images.remove(bitimage)

        tanimage = None
        bitimage = None

    if not tanimage or not bitimage:
        context = bpy.context
        scene = context.scene

        # Copy object first
        temp = obj.copy()
        link_object(scene, temp)
        temp.data = temp.data.copy()
        context.view_layer.objects.active = temp
        temp.location += Vector(((obj.dimensions[0] + 0.1) * 1, 0.0, 0.0))

        # Set active uv
        uv_layers = get_uv_layers(temp)
        uv_layers.active = uv_layers.get(uv_name)

        # Mesh with ngons will can't calculate tangents
        try:
            temp.data.calc_tangents()
        except:
            # Triangulate ngon faces on temp object
            bpy.ops.object.select_all(action="DESELECT")
            temp.select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.reveal()
            bpy.ops.mesh.select_all(action="DESELECT")
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.mesh.select_face_by_sides(number=4, type="GREATER")
            bpy.ops.mesh.quads_convert_to_tris()
            bpy.ops.mesh.tris_convert_to_quads()
            bpy.ops.object.mode_set(mode="OBJECT")

            temp.data.calc_tangents()

        # Bitangent sign attribute's
        bs_att = temp.data.attributes.get(BSIGN_ATTR)
        if not bs_att:
            bs_att = temp.data.attributes.new(BSIGN_ATTR, "FLOAT", "CORNER")
        arr = numpy.zeros(len(temp.data.loops), dtype=numpy.float32)
        temp.data.loops.foreach_get("bitangent_sign", arr)
        bs_att.data.foreach_set("value", arr.ravel())

        # Disable multires modifiers if there's any
        for mod in temp.modifiers:
            if mod.type == "MULTIRES":
                mod.show_viewport = False
                mod.show_render = False

        # Get subsurf modifiers of temp object
        tsubsurf = get_subsurf_modifier(temp)
        if not tsubsurf:
            bpy.ops.object.modifier_add(type="SUBSURF")
            tsubsurf = [m for m in temp.modifiers if m.type == "SUBSURF"][0]
        tsubsurf.show_viewport = True
        tsubsurf.show_render = True

        # Disable non subsurf modifiers
        for m in temp.modifiers:
            if m != tsubsurf:
                m.show_viewport = False
                m.show_render = False

        # Set subsurf to max levels
        # tsubsurf.levels = tsubsurf.render_levels

        # Bake preparations
        book = _remember_before_bake(temp)
        _prepare_bake_settings(book, temp, uv_name)

        if not tanimage:
            tanimage = bpy.data.images.new(
                name=tanimage_name,
                width=1024,
                height=1024,
                alpha=False,
                float_buffer=True,
            )
            tanimage.generated_color = (0, 0, 0, 1)

            # Set bake tangent material
            temp.data.materials.clear()
            mat = get_tangent_bake_mat(uv_name, target_image=tanimage)
            temp.data.materials.append(mat)

            # Bake tangent
            bpy.ops.object.bake()

            # Remove temp mat
            if mat.users <= 1:
                bpy.data.materials.remove(mat, do_unlink=True)

        if not bitimage:

            bitimage = bpy.data.images.new(
                name=bitimage_name,
                width=1024,
                height=1024,
                alpha=False,
                float_buffer=True,
            )
            bitimage.generated_color = (0, 0, 0, 1)

            # Set bake bitangent material
            temp.data.materials.clear()
            mat = get_bitangent_bake_mat(uv_name, target_image=bitimage)
            temp.data.materials.append(mat)

            # Bake bitangent
            bpy.ops.object.bake()

            # Remove temp mat
            if mat.users <= 1:
                bpy.data.materials.remove(mat, do_unlink=True)

        # Pack tangent and bitangent images so they won't lost their data
        tanimage.pack()
        bitimage.pack()
        tanimage.use_fake_user = True
        bitimage.use_fake_user = True

        # Revover bake settings
        _recover_bake_settings(book, True)

        # Remove temp object
        remove_mesh_obj(temp)

        # Back to original object
        set_active_object(obj)
        set_object_select(obj, True)

    return tanimage, bitimage
