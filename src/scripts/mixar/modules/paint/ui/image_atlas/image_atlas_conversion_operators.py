# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators for converting between image atlas and standard images."""

import re

import bpy
from bpy.props import BoolProperty

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.element.update_image import copy_image_pixels, update_image_editor_image
from ...core.element.update_uv import set_uv_neighbor_resolution
from ...core.layer.get_entities import get_mp_entities_images_and_segments
from ...core.layer.layer_utils import get_uv_layers
from ...core.layer.mappings import (
    clear_mapping,
    get_entity_mapping,
    get_udim_segment_mapping_offset,
    update_mapping,
)
from ...core.layer.transformations import is_transformed
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.node.check_nodes import check_mp_linear_nodes
from ...core.node.get_nodes import get_entity_source
from ...core.node.node_utils import copy_id_props, get_active_mpaint_node
from ...utils.blender_commons import (
    get_active_material,
    get_noncolor_name,
    get_srgb_name,
    remove_datablock,
)
from ..udim.udim_operators_helper import fill_tile, remove_udim_atlas_segment_by_name
from ..udim.udim_utils import (
    copy_tiles,
    get_set_udim_atlas_segment,
    get_tile_numbers,
    get_udim_segment_index,
    get_udim_segment_tilenums,
    initial_pack_udim,
)
from .image_atlas_operators_helper import get_entities_with_specific_segment
from .image_atlas_utils import get_set_image_atlas_segment


class MConvertToImageAtlas(bpy.types.Operator):
    """Operator to convert standard images to image atlas format."""

    bl_idname = "wm.m_convert_to_image_atlas"
    bl_label = "Convert Image to Image Atlas"
    bl_description = (
        "Convert image to image atlas (useful to avoid material texture limit)"
    )
    bl_options = {"REGISTER", "UNDO"}

    all_images: BoolProperty(
        name="All Images",
        description="Convert all images instead of only the active one",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return (
            hasattr(context, "image") and context.image and hasattr(context, "entity")
        )

    def execute(self, context):
        mat = get_active_material()
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        if self.all_images:
            entities, images, segment_names, segment_name_props = (
                get_mp_entities_images_and_segments(mp)
            )
        else:
            mapping = get_entity_mapping(context.entity)
            if is_transformed(mapping, context.entity) and not context.entity.use_baked:
                self.report({"ERROR"}, "Cannot convert transformed image!")
                return {"CANCELLED"}

            images = [context.image]
            entities = [[context.entity]]
            segment_name_prop = (
                "segment_name" if not context.entity.use_baked else "baked_segment_name"
            )
            segment_name_props = [[segment_name_prop]]
            segment_name = getattr(context.entity, segment_name_prop)
            segment_names = [segment_name]

        for i, image in enumerate(images):
            if image.yia.is_image_atlas or image.yua.is_udim_atlas:
                continue

            used_by_masks = False
            valid_entities = []
            for j, entity in enumerate(entities[i]):

                # Check if entity is baked to image atlas
                use_baked = segment_name_props[i][j] == "baked_segment_name"

                # Mask will use different type of image atlas
                m = re.match(
                    r"^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", entity.path_from_id()
                )
                if m:
                    used_by_masks = True

                # Transformed mapping on entity is not valid for conversion
                mapping = get_entity_mapping(entity)
                if use_baked or not is_transformed(mapping, entity):
                    valid_entities.append(entity)

            if not any(valid_entities):
                continue

            # Image used by masks will use black image atlas instead of transparent so it will use linear color by default
            color = "BLACK" if used_by_masks else "TRANSPARENT"
            colorspace = get_noncolor_name() if used_by_masks else get_srgb_name()

            # Get segment
            if image.source == "TILED":

                # Make sure image has filepath
                if image.filepath == "":
                    initial_pack_udim(image)

                objs = get_all_objects_with_same_materials(
                    mat, True, valid_entities[0].uv_name
                )
                tilenums = get_tile_numbers(objs, valid_entities[0].uv_name)
                new_segment = get_set_udim_atlas_segment(
                    tilenums,
                    color=image.yui.base_color,
                    colorspace=colorspace,
                    hdr=image.is_float,
                    mp=mp,
                    source_image=image,
                )
                ia_image = new_segment.id_data
            else:
                new_segment = get_set_image_atlas_segment(
                    image.size[0], image.size[1], color, hdr=image.is_float
                )

                # Copy image to segment
                ia_image = new_segment.id_data
                copy_image_pixels(image, ia_image, new_segment)

            # Copy bake info
            if image.m_bake_info.is_baked:
                copy_id_props(image.m_bake_info, new_segment.bake_info)
                new_segment.bake_info.use_image_atlas = True

            for j, entity in enumerate(valid_entities):
                # Set image atlas to entity
                use_baked = segment_name_props[i][j] == "baked_segment_name"
                source = get_entity_source(entity, get_baked=use_baked)
                source.image = ia_image

                # Set segment name
                # entity.segment_name = new_segment.name
                setattr(entity, segment_name_props[i][j], new_segment.name)

                # Make sure uniform scaling is not used
                if entity.enable_uniform_scale:
                    entity.enable_uniform_scale = False

                # Set image to editor
                if entity == context.entity:
                    update_image_editor_image(bpy.context, ia_image)
                    context.scene.tool_settings.image_paint.canvas = ia_image

                # Update mapping
                update_mapping(entity, use_baked=use_baked)
                set_uv_neighbor_resolution(entity, use_baked=use_baked)

            # Remove image if no one using it
            if image.users == 0:
                remove_datablock(bpy.data.images, image)

        # Refresh linear nodes
        check_mp_linear_nodes(mp)

        return {"FINISHED"}


class MConvertToStandardImage(bpy.types.Operator):
    """Operator to convert image atlas back to standard images."""

    bl_idname = "wm.m_convert_to_standard_image"
    bl_label = "Convert Image Atlas to standard image"
    bl_description = "Convert image atlas to standard image"
    bl_options = {"REGISTER", "UNDO"}

    all_images: BoolProperty(
        name="All Images",
        description="Convert all images instead of only the active one",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return (
            hasattr(context, "image") and context.image and hasattr(context, "entity")
        )

    def execute(self, context):
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        if self.all_images:
            entities, images, segment_names, segment_name_props = (
                get_mp_entities_images_and_segments(mp)
            )
        else:
            images = [context.image]

            segment_name_prop = (
                "segment_name" if not context.entity.use_baked else "baked_segment_name"
            )
            segment_name_props = [[segment_name_prop]]
            segment_name = getattr(context.entity, segment_name_prop)

            if context.image.yia.is_image_atlas:
                segment = context.image.yia.segments.get(segment_name)
            else:
                segment = context.image.yua.segments.get(segment_name)

            entities = [get_entities_with_specific_segment(mp, segment)]
            segment_names = [segment_name]

        image_atlases = []

        for i, image in enumerate(images):
            if not image.yia.is_image_atlas and not image.yua.is_udim_atlas:
                continue

            if image.yia.is_image_atlas:
                segment = image.yia.segments.get(segment_names[i])
            else:
                segment = image.yua.segments.get(segment_names[i])

            if not segment:
                continue

            # Create new image based on image atlas
            if image.yia.is_image_atlas:
                new_image = bpy.data.images.new(
                    name=entities[i][0].name,
                    width=segment.width,
                    height=segment.height,
                    alpha=True,
                    float_buffer=image.is_float,
                )
                if image.is_float:
                    new_image.alpha_mode = "PREMUL"
            else:
                new_image = bpy.data.images.new(
                    name=entities[i][0].name,
                    width=image.size[0],
                    height=image.size[1],
                    alpha=True,
                    float_buffer=image.is_float,
                    tiled=True,
                )

                atlas_tilenums = get_udim_segment_tilenums(segment)
                index = get_udim_segment_index(image, segment)
                offset = get_udim_segment_mapping_offset(segment) * 10
                copy_dict = {}
                tilenums = []
                for atilenum in atlas_tilenums:
                    atile = image.tiles.get(atilenum)
                    tilenum = atilenum - offset
                    tilenums.append(tilenum)
                    copy_dict[atilenum] = tilenum
                    fill_tile(
                        new_image,
                        tilenum,
                        image.yui.base_color,
                        atile.size[0],
                        atile.size[1],
                    )

                initial_pack_udim(new_image)

            new_image.colorspace_settings.name = image.colorspace_settings.name

            # Copy the pixels
            if image.yia.is_image_atlas:
                copy_image_pixels(image, new_image, None, segment)
            else:
                copy_tiles(image, new_image, copy_dict)

                # Pack image
                initial_pack_udim(new_image)

            # Copy bake info
            if segment.bake_info.is_baked:
                copy_id_props(segment.bake_info, new_image.m_bake_info)
                new_image.m_bake_info.use_image_atlas = False

            if image.yia.is_image_atlas:
                # Mark unused to the segment
                segment.unused = True
            else:
                remove_udim_atlas_segment_by_name(image, segment.name, mp)

            for j, entity in enumerate(entities[i]):

                # Set new image to entity
                use_baked = segment_name_props[i][j] == "baked_segment_name"
                source = get_entity_source(entity, get_baked=use_baked)
                source.image = new_image
                clear_mapping(entity, use_baked=use_baked)
                entity.segment_name = ""
                setattr(entity, segment_name_props[i][j], "")

                # Set image to editor
                if entity == context.entity:
                    update_image_editor_image(context, new_image)
                    context.scene.tool_settings.image_paint.canvas = new_image

                # Set UV Neighbor resolution
                set_uv_neighbor_resolution(entity)

            if image not in image_atlases:
                image_atlases.append(image)

        # Remove unused image atlas
        for ia_image in image_atlases:
            still_used = False

            if ia_image.yia.is_image_atlas:
                for segment in ia_image.yia.segments:
                    if not segment.unused:
                        still_used = True
                        break
            else:
                if len(ia_image.yua.segments) > 0:
                    still_used = True

            if not still_used:
                remove_datablock(bpy.data.images, ia_image)

        # Refresh linear nodes
        # check_mp_linear_nodes(mp)

        return {"FINISHED"}


# Classes to be registered
classes = (
    MConvertToImageAtlas,
    MConvertToStandardImage,
)
