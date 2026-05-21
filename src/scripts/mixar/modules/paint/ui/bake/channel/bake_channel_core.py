# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel baking core functions"""

from mixar.config.logging_config import get_logger

import bpy

logger = get_logger(__name__)

# Core imports
from ....core.element.update_image import copy_image_channel_pixels, copy_image_pixels
from ....core.io.utils.io_utils import create_link
from ....core.layer.layer_utils import get_root_height_channel
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.get_nodes import get_active_mat_output_node, get_layer_source, get_material_output
from ....utils.blender_commons import get_all_image_users, get_unique_name, get_user_preferences, remove_datablock, simple_remove_node
from ....utils.blender_commons_image import safe_remove_image
from ....utils.common import get_channel_index
from ...udim.udim_utils import copy_tiles, get_tile_numbers, initial_pack_udim, swap_tile
from ...udim.udim_utils_segment import get_udim_segment_tilenums
from ..utils.bake_common import bake_object_op

# Local helper imports
from .bake_channel_helpers import create_bake_image, determine_bake_color, get_image_name_and_path, setup_baked_nodes
from .bake_channel_normal import handle_normal_channel_baking
from .bake_channel_temp import disable_temp_bake, temp_bake, rebake_baked_images

__all__ = ["bake_channel", "temp_bake", "disable_temp_bake", "rebake_baked_images"]


def bake_channel(
    uv_map,
    mat,
    node,
    root_ch,
    width=1024,
    height=1024,
    target_layer=None,
    use_hdr=False,
    aa_level=1,
    force_use_udim=False,
    tilenums=None,
    interpolation="Linear",
    use_float_for_displacement=False,
    use_float_for_normal=False,
):
    """Bake a channel to an image.

    Parameters:
        uv_map (str): UV map name to use for baking
        mat (Material): Material containing the channel
        node: MPaint node
        root_ch: Root channel to bake
        width (int, optional): Image width. Default 1024
        height (int, optional): Image height. Default 1024
        target_layer (Layer, optional): Specific layer to bake. Default None
        use_hdr (bool, optional): Use HDR/float image. Default False
        aa_level (int, optional): Anti-aliasing level. Default 1
        force_use_udim (bool, optional): Force UDIM tiles. Default False
        tilenums (list, optional): Tile numbers for UDIM. Default None
        interpolation (str, optional): Interpolation type. Default "Linear"
        use_float_for_displacement (bool, optional): Use float for displacement. Default False
        use_float_for_normal (bool, optional): Use float for normal maps. Default False

    Returns:
        Image or bool: Baked image datablock or True/False for target layer baking
    """
    if tilenums is None:
        tilenums = []

    logger.info("BAKE CHANNEL: Baking %s channel...", root_ch.name)

    tree = node.node_tree
    mp = tree.mp
    mpup = get_user_preferences()
    scene = bpy.context.scene

    channel_idx = get_channel_index(root_ch)

    # Check if udim image is needed based on number of tiles
    if tilenums == []:
        objs = get_all_objects_with_same_materials(mat)
        tilenums = get_tile_numbers(objs, uv_map)

    # Check if temp bake is necessary for normal channel
    temp_baked = []
    if root_ch.type == "NORMAL":
        temp_baked = _prepare_temp_bakes(mp, width, height, scene, uv_map)

    # Handle target layer setup
    ch = None
    img = None
    segment = None
    source = None
    copy_dict = None
    segment_tilenums = None

    if target_layer:
        result = _setup_target_layer(target_layer, channel_idx)
        if result is False:
            return False
        ch, img, segment, source = result

    # Check if udim will be used
    use_udim = (
        force_use_udim
        or len(tilenums) > 1
        or (segment and segment.id_data.source == "TILED")
    )

    # Get output node and remember original bsdf input
    output = get_active_mat_output_node(mat.node_tree)
    ori_bsdf = output.inputs[0].links[0].from_socket

    # Get material output
    mat_out = get_material_output(mat)

    # Create setup nodes
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    emit = mat.node_tree.nodes.new("ShaderNodeEmission")

    # Normal baking needs special node setup
    bsdf = None
    norm = None
    if root_ch.type == "NORMAL":
        bsdf = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")

    # Set tex as active node
    mat.node_tree.nodes.active = tex

    # Handle displacement link
    ori_disp_from_node = ""
    ori_disp_from_socket = ""
    height_root_ch = get_root_height_channel(mp)
    if (
        height_root_ch
        and root_ch != height_root_ch
        and height_root_ch.enable_subdiv_setup
    ):
        for link in mat_out.inputs["Displacement"].links:
            ori_disp_from_node = link.from_node.name
            ori_disp_from_socket = link.from_socket.name
            mat.node_tree.links.remove(link)
            break

    # Connect emit to output material
    mat.node_tree.links.new(emit.outputs[0], output.inputs[0])

    # Get image name and path
    img_name, filepath = get_image_name_and_path(tree, root_ch, segment, img, use_hdr)
    baked = None

    if not target_layer:
        baked, img_name, filepath = setup_baked_nodes(tree, root_ch, uv_map, interpolation)

    # Create image if needed
    if not img:
        color, copy_dict, color_tilenums = determine_bake_color(
            root_ch, node, mp, channel_idx, segment, source
        )
        if color_tilenums:
            tilenums = color_tilenums
            segment_tilenums = get_udim_segment_tilenums(segment)

        # Handle segment width/height for image atlas
        seg_width, seg_height = width, height
        if segment and source and source.image.yia.is_image_atlas:
            seg_width = segment.width
            seg_height = segment.height

        img = create_bake_image(
            img_name,
            seg_width,
            seg_height,
            root_ch,
            color,
            use_udim,
            use_hdr,
            use_float_for_normal,
            tilenums,
            filepath,
            segment,
            source,
            copy_dict,
            segment_tilenums,
        )

    # Bake main image
    ori_normal_space = None
    if (
        target_layer
        and (root_ch.type != "NORMAL" or ch.normal_map_type == "NORMAL_MAP")
    ) or (not target_layer):
        ori_normal_space = _bake_main_image(
            root_ch, mp, img, tex, node, mat, bsdf, norm, output, emit, scene
        )

    # Bake displacement for normal channel
    if root_ch.type == "NORMAL":
        disp_result = handle_normal_channel_baking(
            tree,
            mp,
            root_ch,
            img,
            tex,
            node,
            mat,
            mat_out,
            bsdf,
            output,
            emit,
            scene,
            use_udim,
            filepath,
            use_float_for_displacement,
            target_layer,
            ch,
            ori_normal_space,
        )
        if disp_result[0]:
            ori_disp_from_node = disp_result[0]
            ori_disp_from_socket = disp_result[1]

    # Bake alpha
    if root_ch.enable_alpha:
        _bake_alpha(root_ch, img, tex, node, mat, emit, tilenums)

    # Set final image
    if not target_layer:
        if baked and baked.image:
            temp = baked.image
            img_users = get_all_image_users(baked.image)
            for user in img_users:
                user.image = img
            remove_datablock(bpy.data.images, temp)
        elif baked:
            baked.image = img

    # Cleanup
    simple_remove_node(mat.node_tree, tex, remove_data=tex.image != img)
    simple_remove_node(mat.node_tree, emit)
    if bsdf:
        simple_remove_node(mat.node_tree, bsdf)
    if norm:
        simple_remove_node(mat.node_tree, norm)

    # Recover displacement link
    if ori_disp_from_node != "":
        nod = mat.node_tree.nodes.get(ori_disp_from_node)
        if nod:
            soc = nod.outputs.get(ori_disp_from_socket)
            if soc:
                mat.node_tree.links.new(soc, mat_out.inputs["Displacement"])

    # Recover original bsdf
    mat.node_tree.links.new(ori_bsdf, output.inputs[0])

    # Recover baked temp
    for ent in temp_baked:
        logger.info("BAKE CHANNEL: Removing temporary baked %s...", ent.name)
        disable_temp_bake(ent)

    # Set image to target layer
    if target_layer:
        return _finalize_target_layer(
            target_layer, source, segment, img, copy_dict
        )

    return img


def _prepare_temp_bakes(mp, width, height, scene, uv_map):
    """Prepare temporary bakes for HEMI layers and masks."""
    temp_baked = []
    for lay in mp.layers:
        if lay.type in {"HEMI"} and not lay.use_temp_bake:
            logger.info(
                "BAKE CHANNEL: Fake lighting layer found! Baking temporary image of %s layer...",
                lay.name,
            )
            temp_bake(
                bpy.context,
                lay,
                width,
                height,
                True,
                1,
                scene.render.bake.margin,
                uv_map,
            )
            temp_baked.append(lay)
        for mask in lay.masks:
            if mask.type in {"HEMI"} and not mask.use_temp_bake:
                logger.info(
                    "BAKE CHANNEL: Fake lighting mask found! Baking temporary image of %s mask...",
                    mask.name,
                )
                temp_bake(
                    bpy.context,
                    mask,
                    width,
                    height,
                    True,
                    1,
                    scene.render.bake.margin,
                    uv_map,
                )
                temp_baked.append(mask)
    return temp_baked


def _setup_target_layer(target_layer, channel_idx):
    """Setup target layer for baking. Returns (ch, img, segment, source) or False."""
    if target_layer.type != "IMAGE":
        return False

    source = get_layer_source(target_layer)
    if not source.image:
        return False

    ch = None
    img = None
    segment = None

    if source.image.yia.is_image_atlas and target_layer.segment_name != "":
        segment = source.image.yia.segments.get(target_layer.segment_name)
    elif source.image.yua.is_udim_atlas and target_layer.segment_name != "":
        segment = source.image.yua.segments.get(target_layer.segment_name)
    else:
        img_name = source.image.name
        source.image.name = get_unique_name(img_name, bpy.data.images)
        img = source.image.copy()
        img.name = img_name

    ch = target_layer.channels[channel_idx]
    return ch, img, segment, source


def _bake_main_image(root_ch, mp, img, tex, node, mat, bsdf, norm, output, emit, scene):
    """Bake the main image. Returns original normal space if baking normal."""
    tex.image = img
    rgb = node.outputs[root_ch.name]
    ori_normal_space = None

    if root_ch.type == "NORMAL":
        if norm:
            rgb = create_link(mat.node_tree, rgb, norm.inputs[0])[0]
            mat.node_tree.links.new(rgb, emit.inputs[0])
        elif bsdf:
            ori_normal_space = scene.render.bake.normal_space
            scene.cycles.bake_type = "NORMAL"
            scene.render.bake.normal_space = "TANGENT"

            mat.node_tree.links.new(rgb, bsdf.inputs["Normal"])
            mat.node_tree.links.new(bsdf.outputs[0], output.inputs[0])

            # HACK: Sometimes the bsdf node needs color socket connected
            for rch in mp.channels:
                if rch.type == "RGB":
                    soc = node.outputs.get(rch.name)
                    if soc:
                        mat.node_tree.links.new(soc, bsdf.inputs[0])
                        break
    else:
        mat.node_tree.links.new(rgb, emit.inputs[0])

    # Bake!
    logger.info("BAKE CHANNEL: Baking main image of %s channel...", root_ch.name)
    bake_object_op(scene.cycles.bake_type)

    # Revert back the original bake settings
    if root_ch.type == "NORMAL" and bsdf:
        scene.cycles.bake_type = "EMIT"
        scene.render.bake.normal_space = ori_normal_space
        mat.node_tree.links.new(emit.outputs[0], output.inputs[0])

    return ori_normal_space


def _bake_alpha(root_ch, img, tex, node, mat, emit, tilenums):
    """Bake alpha channel to image."""
    from ....utils.blender_commons import get_noncolor_name
    from ....utils.constants import io_suffix

    # Create temp image
    alpha_img = img.copy()
    alpha_img.colorspace_settings.name = get_noncolor_name()
    create_link(
        mat.node_tree,
        node.outputs[root_ch.name + io_suffix["ALPHA"]],
        emit.inputs[0],
    )
    tex.image = alpha_img

    # Set temp filepath
    if img.source == "TILED":
        alpha_img.name = "__TEMP__"
        initial_pack_udim(alpha_img)

    # Bake
    logger.info("BAKE CHANNEL: Baking alpha of %s channel...", root_ch.name)
    bake_object_op()

    # Set tile pixels
    for tilenum in tilenums:
        if tilenum != 1001:
            swap_tile(img, 1001, tilenum)
            swap_tile(alpha_img, 1001, tilenum)

        copy_image_channel_pixels(alpha_img, img, 0, 3)

        if tilenum != 1001:
            swap_tile(img, 1001, tilenum)
            swap_tile(alpha_img, 1001, tilenum)

    # Remove temp image
    remove_datablock(bpy.data.images, alpha_img, user=tex, user_prop="image")


def _finalize_target_layer(target_layer, source, segment, img, copy_dict):
    """Finalize target layer after baking. Returns True if successful."""
    ori_img = source.image

    if segment:
        if ori_img.yia.is_image_atlas:
            copy_image_pixels(img, ori_img, segment)
        else:
            copy_tiles(img, ori_img, copy_dict)

        remove_datablock(bpy.data.images, img)
    else:
        source.image = img
        safe_remove_image(ori_img)

    return True
