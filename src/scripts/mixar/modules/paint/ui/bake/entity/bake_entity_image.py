# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bake entity as image - bakes layer or mask entity to an image texture."""

from mixar.config.logging_config import get_logger

import re
import bpy

logger = get_logger(__name__)

from ....core.element.update_image import replace_image
from ....core.element.update_uv import refresh_temp_uv, set_uv_neighbor_resolution
from ....core.layer.check_channels import check_all_channel_ios, check_start_end_root_ch_nodes
from ....core.layer.layer_utils import get_height_channel, get_layer_index
from ....core.layer.mappings import clear_mapping
from ....core.node.check_nodes import check_all_layer_channel_io_and_nodes, check_uv_nodes
from ....core.node.create_nodes import check_new_node, new_node
from ....core.node.get_nodes import get_entity_source
from ....core.node.node_utils import get_active_mpaint_node, remove_node
from ....core.subtree.get_subtree import get_mask_tree, get_source_tree, get_tree
from ....utils.blender_commons import (
    get_active_material, get_active_object, get_noncolor_name, get_srgb_name, simple_remove_node,
)
from ....utils.common import get_entity_prop_value, set_entity_prop_value
from ...image_atlas.image_atlas_utils import set_segment_mapping
from ...udim.udim_utils import fill_tile, get_tile_numbers, initial_pack_udim, remove_udim_atlas_segment_by_name


def _get_bake_imports():
    """Lazy import of bake-related modules to avoid circular dependencies."""
    from ..utils.bake_image_processing import blur_image, denoise_image, fxaa_image, noise_blur_image
    from ..object_prep.bake_object_prep import get_bakeable_objects_and_meshes
    from ..utils.bake_settings_manager import prepare_bake_settings, recover_bake_settings, remember_before_bake
    from ..utils.bake_temp_materials import put_image_to_image_atlas
    from ..utils.bake_validation import get_problematic_modifiers, is_object_bakeable
    return {
        'blur_image': blur_image, 'denoise_image': denoise_image, 'fxaa_image': fxaa_image,
        'noise_blur_image': noise_blur_image, 'get_bakeable_objects_and_meshes': get_bakeable_objects_and_meshes,
        'prepare_bake_settings': prepare_bake_settings, 'recover_bake_settings': recover_bake_settings,
        'remember_before_bake': remember_before_bake, 'put_image_to_image_atlas': put_image_to_image_atlas,
        'get_problematic_modifiers': get_problematic_modifiers, 'is_object_bakeable': is_object_bakeable,
    }


def bake_entity_as_image(entity, bprops, set_image_to_entity=False):
    """Bake layer or mask entity as an image.

    Args:
        entity: Layer or mask entity to bake.
        bprops: Bake properties configuration.
        set_image_to_entity (bool, optional): Set baked image to entity. Defaults to False.

    Returns:
        dict: Dictionary containing operation results and messages.
    """
    # Get lazy imports
    imports = _get_bake_imports()
    blur_image = imports['blur_image']
    denoise_image = imports['denoise_image']
    fxaa_image = imports['fxaa_image']
    noise_blur_image = imports['noise_blur_image']
    get_bakeable_objects_and_meshes = imports['get_bakeable_objects_and_meshes']
    prepare_bake_settings = imports['prepare_bake_settings']
    recover_bake_settings = imports['recover_bake_settings']
    remember_before_bake = imports['remember_before_bake']
    put_image_to_image_atlas = imports['put_image_to_image_atlas']
    get_problematic_modifiers = imports['get_problematic_modifiers']
    is_object_bakeable = imports['is_object_bakeable']

    rdict = {}
    rdict["message"] = ""

    mp = entity.id_data.mp
    mat = get_active_material()
    obj = get_active_object()
    objs = [obj] if is_object_bakeable(obj) else []
    if mat.users > 1:
        objs, _ = get_bakeable_objects_and_meshes(mat)

    if not objs:
        rdict["message"] = "No valid objects found to bake!"
        return rdict

    # Get tile numbers
    tilenums = [1001]
    if bprops.use_udim:
        tilenums = get_tile_numbers(objs, bprops.uv_map)

    m1 = re.match(r"^mp\.layers\[(\d+)\]$", entity.path_from_id())
    m2 = re.match(r"^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", entity.path_from_id())

    ori_use_baked = False
    ori_enabled_mods = []

    modifiers_disabled = False
    if m1:
        layer_idx = int(m1.group(1))
        if layer_idx >= len(mp.layers):
            rdict["message"] = "Layer index out of bounds!"
            return rdict
        layer = mp.layers[layer_idx]
        mask = None
        source_tree = get_source_tree(layer)
    elif m2:
        layer_idx = int(m2.group(1))
        mask_idx = int(m2.group(2))
        if layer_idx >= len(mp.layers):
            rdict["message"] = "Layer index out of bounds!"
            return rdict
        layer = mp.layers[layer_idx]
        if mask_idx >= len(layer.masks):
            rdict["message"] = "Mask index out of bounds!"
            return rdict
        mask = layer.masks[mask_idx]
        source_tree = get_mask_tree(mask)

    else:
        rdict["message"] = "Wrong entity!"
        return rdict

    # Disable use baked first
    if entity.use_baked:
        ori_use_baked = True
        entity.use_baked = False

    # Setting image to entity will disable modifiers
    if set_image_to_entity:
        for mod in entity.modifiers:
            if mod.enable:
                ori_enabled_mods.append(mod)
                mod.enable = False
        modifiers_disabled = True

    # Get existing baked image
    existing_image = None
    baked_source = source_tree.nodes.get(entity.baked_source)
    if baked_source:
        existing_image = baked_source.image

    # Remember things
    book = remember_before_bake(mp)

    # FXAA doesn't work with hdr image
    # FXAA also does not works well with baked image with alpha
    use_fxaa = not bprops.hdr and bprops.fxaa

    # Remember before doing preview
    ori_channel_index = mp.active_channel_index
    ori_preview_mode = mp.preview_mode
    ori_layer_preview_mode = mp.layer_preview_mode
    ori_layer_preview_mode_type = mp.layer_preview_mode_type

    ori_layer_intensity_value = 1.0
    changed_layer_channel_index = -1
    ori_layer_channel_intensity_value = 1.0
    ori_layer_channel_blend_type = "MIX"
    ori_layer_channel_override = None
    ori_layer_enable_masks = None

    # Make sure layer is enabled
    ori_layer_enable = layer.enable
    layer.enable = True
    layer_opacity = get_entity_prop_value(layer, "intensity_value")
    if layer_opacity != 1.0:
        ori_layer_intensity_value = layer_opacity
        set_entity_prop_value(layer, "intensity_value", 1.0)

    # Make sure layer is active one
    ori_layer_idx = mp.active_layer_index
    layer_idx = get_layer_index(layer)
    if mp.active_layer_index != layer_idx:
        mp.active_layer_index = layer_idx

    if mask:
        # Set up active edit
        ori_mask_enable = mask.enable
        mask.enable = True
    else:
        # Disable masks
        ori_layer_enable_masks = layer.enable_masks
        if layer.enable_masks:
            layer.enable_masks = False
        for m in layer.masks:
            if m.active_edit:
                m.active_edit = False

    # Set active channel so preview will output right value
    for i, ch in enumerate(layer.channels):
        if mask:
            if ch.enable and mask.channels[i].enable:
                mp.active_channel_index = i
                break
        else:
            if ch.enable:
                mp.active_channel_index = i

                # Make sure intensity value is 1.0
                intensity_value = get_entity_prop_value(ch, "intensity_value")
                if intensity_value != 1.0:
                    changed_layer_channel_index = i
                    ori_layer_channel_intensity_value = intensity_value
                    set_entity_prop_value(ch, "intensity_value", 1.0)

                if ch.blend_type != "MIX":
                    changed_layer_channel_index = i
                    ori_layer_channel_blend_type = ch.blend_type
                    ch.blend_type = "MIX"

                if ch.override:
                    changed_layer_channel_index = i
                    ori_layer_channel_override = True
                    ch.override = False

                break

    # Modifier setups
    ori_mods = {}
    ori_viewport_mods = {}

    for obj in objs:

        # Disable few modifiers
        ori_mods[obj.name] = [m.show_render for m in obj.modifiers]
        ori_viewport_mods[obj.name] = [m.show_viewport for m in obj.modifiers]

        for m in get_problematic_modifiers(obj):
            m.show_render = False

    prepare_bake_settings(
        book,
        objs,
        mp,
        samples=bprops.samples,
        margin=bprops.margin,
        uv_map=bprops.uv_map,
        bake_type="EMIT",
        bake_device=bprops.bake_device,
        margin_type=bprops.margin_type,
    )

    # Create bake nodes
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")

    if mask:
        color = (0, 0, 0, 1)
        color_str = "BLACK"
        colorspace = get_noncolor_name()
    else:
        color = (0, 0, 0, 0)
        color_str = "TRANSPARENT"
        colorspace = get_noncolor_name() if bprops.hdr else get_srgb_name()

    # Use existing image colorspace if available
    if existing_image:
        colorspace = existing_image.colorspace_settings.name

    # Create image
    if bprops.use_udim:
        image = bpy.data.images.new(
            name=bprops.name,
            width=bprops.width,
            height=bprops.height,
            alpha=True,
            float_buffer=bprops.hdr,
            tiled=True,
        )

        # Fill tiles
        for tilenum in tilenums:
            fill_tile(image, tilenum, color, bprops.width, bprops.height)
        initial_pack_udim(image, color)

        # Remember base color
        image.yia.color = color_str
    else:
        image = bpy.data.images.new(
            name=bprops.name,
            width=bprops.width,
            height=bprops.height,
            alpha=True,
            float_buffer=bprops.hdr,
        )

    image.generated_color = color
    image.colorspace_settings.name = colorspace

    # Set bake image
    tex.image = image
    mat.node_tree.nodes.active = tex

    # Bake!
    bpy.ops.object.bake()

    if bprops.blur:
        samples = 4096
        if bprops.blur_type == "NOISE":
            noise_blur_image(
                image,
                False,
                bake_device=bprops.bake_device,
                factor=bprops.blur_factor,
                samples=samples,
            )
        else:
            blur_image(image, filter_type=bprops.blur_type, size=bprops.blur_size)
    if bprops.denoise:
        denoise_image(image)
    if use_fxaa:
        fxaa_image(image, False, bake_device=bprops.bake_device)

    # Remove temp bake nodes
    simple_remove_node(mat.node_tree, tex, remove_data=False)

    # Recover bake settings
    recover_bake_settings(book, mp)

    # Recover modifiers
    for obj in objs:
        # Recover modifiers
        for i, m in enumerate(obj.modifiers):
            if i >= len(ori_mods[obj.name]):
                break
            if ori_mods[obj.name][i] != m.show_render:
                m.show_render = ori_mods[obj.name][i]
            if i >= len(ori_viewport_mods[obj.name]):
                break
            if ori_viewport_mods[obj.name][i] != m.show_render:
                m.show_viewport = ori_viewport_mods[obj.name][i]

    # Recover preview
    mp.active_channel_index = ori_channel_index
    if mp.preview_mode != ori_preview_mode:
        mp.preview_mode = ori_preview_mode
    # Explicitly disable layer preview mode after baking
    if mp.layer_preview_mode:
        mp.layer_preview_mode = False

    if changed_layer_channel_index != -1:
        ch = layer.channels[changed_layer_channel_index]

        if ori_layer_channel_intensity_value != 1.0:
            set_entity_prop_value(
                ch, "intensity_value", ori_layer_channel_intensity_value
            )

        if ori_layer_channel_blend_type != "MIX":
            ch.blend_type = ori_layer_channel_blend_type

        if (
            ori_layer_channel_override is not None
            and ch.override != ori_layer_channel_override
        ):
            ch.override = ori_layer_channel_override

    if ori_layer_intensity_value != 1.0:
        set_entity_prop_value(layer, "intensity_value", ori_layer_intensity_value)

    if ori_layer_enable_masks is not None and layer.enable_masks != ori_layer_enable_masks:
        layer.enable_masks = ori_layer_enable_masks

    if ori_layer_idx != mp.active_layer_index:
        mp.active_layer_index = ori_layer_idx

    if ori_layer_enable != layer.enable:
        layer.enable = ori_layer_enable

    if mask and ori_mask_enable != mask.enable:
        mask.enable = ori_mask_enable

    if modifiers_disabled:
        for mod in ori_enabled_mods:
            mod.enable = True

    if ori_use_baked:
        entity.use_baked = True

    # Set up image atlas segment
    segment = None
    if bprops.use_image_atlas:
        image, segment = put_image_to_image_atlas(mp, image, tilenums)

    if set_image_to_entity:

        layer_tree = get_tree(layer)
        if mask:
            source_tree = get_mask_tree(mask)
        else:
            source_tree = get_source_tree(layer)

        mp.halt_update = True

        # Set bake info to image/segment
        bi = segment.bake_info if segment else image.m_bake_info

        bi.is_baked = True
        bi.is_baked_entity = True
        bi.baked_entity_type = entity.type
        for attr in dir(bi):
            if attr.startswith("__"):
                continue
            if attr.startswith("bl_"):
                continue
            if attr in {"rna_type"}:
                continue
            try:
                setattr(bi, attr, bprops[attr])
            except:
                pass

        # Set bake type for some types
        if entity.type == "EDGE_DETECT":
            bi.bake_type = "BEVEL_MASK"
            bi.bevel_radius = get_entity_prop_value(entity, "edge_detect_radius")
        elif entity.type == "AO":
            source = get_entity_source(entity)
            bi.bake_type = "AO"
            bi.ao_distance = get_entity_prop_value(entity, "ao_distance")
            bi.only_local = source.only_local

        # Get baked source
        overwrite_image = None
        baked_source = source_tree.nodes.get(entity.baked_source)
        if baked_source:
            overwrite_image = baked_source.image

            # Remove old segment
            if entity.baked_segment_name != "":
                if overwrite_image.yia.is_image_atlas:
                    old_segment = overwrite_image.yia.segments.get(
                        entity.baked_segment_name
                    )
                    old_segment.unused = True
                elif overwrite_image.yua.is_udim_atlas:
                    remove_udim_atlas_segment_by_name(
                        overwrite_image, entity.baked_segment_name, mp=mp
                    )

                # Remove baked segment name
                entity.baked_segment_name = ""
        else:
            baked_source = new_node(
                source_tree,
                entity,
                "baked_source",
                "ShaderNodeTexImage",
                "Baked Mask Source",
            )

        # Set image to baked node
        if overwrite_image and not segment:
            replace_image(overwrite_image, image)
        else:
            baked_source.image = image

        height_ch = get_height_channel(layer)
        if height_ch and height_ch.enable:
            baked_source.interpolation = "Cubic"

        # Set entity props
        entity.baked_uv_name = bprops.uv_map
        entity.use_baked = True

        mp.halt_update = False

        if segment:
            # Set up baked mapping
            mapping = check_new_node(
                layer_tree,
                entity,
                "baked_mapping",
                "ShaderNodeMapping",
                "Baked Mapping",
            )
            clear_mapping(entity, use_baked=True)
            set_segment_mapping(entity, segment, image, use_baked=True)

            # Set baked segment name to entity
            entity.baked_segment_name = segment.name
        else:
            remove_node(layer_tree, entity, "baked_mapping")

        # Refresh uv
        refresh_temp_uv(get_active_object(), entity)

        # Refresh Neighbor UV resolution
        set_uv_neighbor_resolution(entity)

        # Update global uv
        check_uv_nodes(mp)

        # Update layer tree inputs
        check_all_layer_channel_io_and_nodes(layer)
        check_start_end_root_ch_nodes(mp.id_data)

    rdict["image"] = image
    rdict["segment"] = segment

    return rdict
