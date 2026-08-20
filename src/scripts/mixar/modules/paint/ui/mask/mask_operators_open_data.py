# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Open available data as mask operator.

This module contains the operator for opening available data (images, vertex colors)
as layer masks.
"""

import bpy
from bpy.props import (
    CollectionProperty,
    EnumProperty,
    StringProperty,
)

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.create_vcol import new_vertex_color
from ...core.element.get_elements import (
    get_default_uv_name,
    get_vcol_data_type_and_domain_by_name,
    get_vertex_color_names,
)
from ...core.element.update_vcol import set_active_vertex_color
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.layer.get_entities import get_all_baked_channel_images
from ...core.layer.layer_utils import get_active_layer, get_height_channel
from ...core.node.check_nodes import check_mp_linear_nodes
from ...core.node.get_nodes import get_layer_source, get_mask_source
from ...core.node.node_utils import get_active_mpaint_node, get_vertex_colors
from ...utils.blender_commons import (
    get_active_object,
    get_noncolor_name,
    get_scene_objects,
    is_image_available_to_open,
)
from ...utils.constants import (
    TEMP_UV,
    interpolation_type_items,
    mask_texcoord_type_items,
)
from ...utils.statics import mask_blend_type_items
from ..mask.mask_creation import add_new_mask
from ..utils.image_preview_enum import build_image_enum_items


def _open_data_image_items(self, context):
    """EnumProperty items (with preview thumbnails) for the mask image picker."""
    names = [item.name for item in self.image_coll]
    return build_image_enum_items(names, cache_key="mask_open_data_image")


class MOpenAvailableDataAsMask(bpy.types.Operator):
    bl_idname = "wm.m_open_available_data_as_mask"
    bl_label = "Open available data as Layer Mask"
    bl_description = "Open available data as Layer Mask"
    bl_options = {"REGISTER", "UNDO"}

    type: EnumProperty(
        name="Layer Type",
        items=(("IMAGE", "Image", ""), ("VCOL", "Vertex Color", "")),
        default="IMAGE",
    )

    interpolation: EnumProperty(
        name="Image Interpolation Type",
        description="image interpolation type",
        items=interpolation_type_items,
        default="Linear",
    )

    texcoord_type: EnumProperty(
        name="Mask Coordinate Type",
        description="Mask Coordinate Type",
        items=mask_texcoord_type_items,
        default="UV",
    )

    source_input: EnumProperty(
        name="Source Input",
        description="Source data for mask input",
        items=(("RGB", "Color", ""), ("ALPHA", "Alpha", "")),
        default="RGB",
    )

    uv_map: StringProperty(default="")
    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    image_name: StringProperty(name="Image")
    image_coll: CollectionProperty(type=bpy.types.PropertyGroup)
    image_enum: EnumProperty(name="Image", items=_open_data_image_items)

    vcol_name: StringProperty(name="Vertex Color")
    vcol_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    blend_type: EnumProperty(
        name="Blend", description="Blend type", items=mask_blend_type_items, default=3
    )

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        obj = get_active_object()
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        layer = get_active_layer(mp)

        self.auto_cancel = False
        if not layer:
            self.auto_cancel = True
            return self.execute(context)

        if obj.type != "MESH":
            self.texcoord_type = "Object"

        # Set the default source input first
        self.source_input = "RGB"

        # Use active uv layer name by default
        if obj.type == "MESH" and len(obj.data.uv_layers) > 0:

            self.uv_map = get_default_uv_name(obj, mp)

            # UV Map collections update
            self.uv_map_coll.clear()
            for uv in obj.data.uv_layers:
                if not uv.name.startswith(TEMP_UV):
                    self.uv_map_coll.add().name = uv.name

        if self.type == "IMAGE":

            layer_image = None
            if layer.type == "IMAGE":
                source = get_layer_source(layer)
                layer_image = source.image

            mask_images = []
            for mask in layer.masks:
                if mask.type == "IMAGE":
                    source = get_mask_source(mask)
                    if source.image:
                        mask_images.append(source.image)

            # Update image names
            self.image_coll.clear()
            imgs = bpy.data.images
            baked_channel_images = get_all_baked_channel_images(layer.id_data) or []

            logger.debug("MASK: Filtering images for mask selection:")
            logger.debug("MASK: Total images in bpy.data.images: %d", len(imgs))
            logger.debug("MASK: Baked channel images: %s", [i.name for i in baked_channel_images])
            logger.debug("MASK: Layer image to exclude: %s", layer_image.name if layer_image else None)
            logger.debug("MASK: Mask images already used: %s", [i.name for i in mask_images])

            for img in imgs:
                available = is_image_available_to_open(img)
                not_baked = img not in baked_channel_images
                not_layer = img != layer_image
                not_mask = img not in mask_images

                if not available:
                    logger.debug("MASK: Filtered '%s': is_image_available_to_open=False (yia.is_image_atlas=%s, yua.is_udim_atlas=%s)",
                                img.name, img.yia.is_image_atlas, img.yua.is_udim_atlas)
                elif not not_baked:
                    logger.debug("MASK: Filtered '%s': is baked channel image", img.name)
                elif not not_layer:
                    logger.debug("MASK: Filtered '%s': is layer image", img.name)
                elif not not_mask:
                    logger.debug("MASK: Filtered '%s': already used as mask", img.name)

                if available and not_baked and not_layer and not_mask:
                    self.image_coll.add().name = img.name
                    logger.debug("MASK: Added '%s' to available images", img.name)

            logger.debug("MASK: Final available images count: %d", len(self.image_coll))

            # Make sure default image is available in the collection
            # and update the source input based on the default name
            if self.image_name not in self.image_coll:
                self.image_name = ""
            else:
                self.image_name = self.image_name

            # Check if there's height channel and use cubic interpolation if there is one
            height_ch = get_height_channel(layer)
            if height_ch and height_ch.enable:
                self.interpolation = "Cubic"
            elif layer.type == "IMAGE":
                source = get_layer_source(layer)
                if source and source.image:
                    self.interpolation = source.interpolation

        elif self.type == "VCOL":

            layer_vcol_name = None
            if layer.type == "VCOL":
                source = get_layer_source(layer)
                layer_vcol_name = source.attribute_name

            mask_vcol_names = []
            for mask in layer.masks:
                if mask.type == "VCOL":
                    source = get_mask_source(mask)
                    mask_vcol_names.append(source.attribute_name)

            self.vcol_coll.clear()
            for vcol_name in get_vertex_color_names(obj):
                if vcol_name != layer_vcol_name and vcol_name not in mask_vcol_names:
                    self.vcol_coll.add().name = vcol_name

            # Make sure default vcol is available in the collection
            # and update the source input based on the default name
            if self.vcol_name not in self.vcol_coll:
                self.vcol_name = ""
            else:
                self.vcol_name = self.vcol_name

        # The default blend type for mask is multiply
        if len(layer.masks) == 0:
            self.blend_type = "MULTIPLY"

        return context.window_manager.invoke_props_dialog(self)

    def check(self, context):
        return True

    def draw(self, context):
        obj = get_active_object()
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        layer = get_active_layer(mp)

        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== SOURCE SELECTION SECTION ==========
        source_box = main_col.box()
        source_col = source_box.column(align=False)

        # Header
        header_row = source_col.row(align=True)
        header_row.scale_y = 1.4
        if self.type == "IMAGE":
            header_row.label(text="Select Image", icon="IMAGE_DATA")
        else:
            header_row.label(text="Select Vertex Color", icon="GROUP_VCOL")

        source_col.separator(factor=1.2)

        # Source selection
        source_row = source_col.row(align=True)
        source_row.scale_y = 1.4
        if self.type == "IMAGE":
            source_row.prop(self, "image_enum", text="")
        elif self.type == "VCOL":
            source_row.prop_search(
                self, "vcol_name", self, "vcol_coll", icon="GROUP_VCOL", text=""
            )

        source_col.separator(factor=0.4)

        source_col.separator(factor=0.8)

        main_col.separator(factor=0.8)

        # ========== MASK PROPERTIES SECTION ==========
        props_box = main_col.box()
        props_col = props_box.column(align=False)

        # Header
        props_header = props_col.row(align=True)
        props_header.scale_y = 1.4
        props_header.label(text="Mask Properties", icon="PROPERTIES")

        props_col.separator(factor=1.2)

        # IMAGE type properties
        if self.type == "IMAGE":
            # Interpolation
            interp_row = props_col.row(align=True)
            interp_row.scale_y = 1.4
            interp_split = interp_row.split(factor=0.25, align=True)
            label_col = interp_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Interpolation:")
            interp_split.prop(self, "interpolation", text="")

            props_col.separator(factor=0.4)

            # Vector/Texcoord
            vector_row = props_col.row(align=True)
            vector_row.scale_y = 1.4
            vector_split = vector_row.split(factor=0.25, align=True)
            label_col = vector_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Vector:")
            vector_value_col = vector_split.column(align=True)
            crow = vector_value_col.row(align=True)
            crow.prop(self, "texcoord_type", text="")
            if obj.type == "MESH" and self.texcoord_type == "UV":
                crow.prop_search(
                    self, "uv_map", self, "uv_map_coll", text="", icon="GROUP_UVS"
                )

            props_col.separator(factor=0.4)

        # Blend (if layer has masks)
        if len(layer.masks) > 0:
            blend_row = props_col.row(align=True)
            blend_row.scale_y = 1.4
            blend_split = blend_row.split(factor=0.25, align=True)
            label_col = blend_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Blend:")
            blend_split.prop(self, "blend_type", text="")

            props_col.separator(factor=0.4)

        # Source input (Image Channel or Vertex Color Data)
        channel_row = props_col.row(align=True)
        channel_row.scale_y = 1.4
        channel_split = channel_row.split(factor=0.25, align=True)
        label_col = channel_split.column(align=True)
        label_col.alignment = "RIGHT"
        if self.type == "IMAGE":
            label_col.label(text="Image Channel:")
        elif self.type == "VCOL":
            label_col.label(text="Vertex Color Data:")
        channel_value_col = channel_split.column(align=True)
        crow = channel_value_col.row(align=True)
        crow.prop(self, "source_input", expand=True)

        props_col.separator(factor=0.4)

        props_col.separator(factor=0.8)

    def execute(self, context):
        if self.auto_cancel:
            return {"CANCELLED"}

        obj = get_active_object()
        mat = obj.active_material

        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        layer = get_active_layer(mp)
        mpui = context.window_manager.mpui

        if self.type == "IMAGE":
            self.image_name = "" if self.image_enum in {"", "NONE"} else self.image_enum

        if self.type == "IMAGE" and self.image_name == "":
            self.report({"ERROR"}, "No image selected!")
            return {"CANCELLED"}
        elif self.type == "VCOL" and self.vcol_name == "":
            self.report({"ERROR"}, "No vertex color selected!")
            return {"CANCELLED"}

        image = None
        vcol = None
        if self.type == "IMAGE":
            image = bpy.data.images.get(self.image_name)
            name = image.name

            if (
                self.source_input == "RGB"
                and image.colorspace_settings.name != get_noncolor_name()
                and not image.is_dirty
            ):
                image.colorspace_settings.name = get_noncolor_name()
        elif self.type == "VCOL":
            name = self.vcol_name

            objs = [obj] if obj.type == "MESH" else []
            if mat.users > 1:
                for o in get_scene_objects():
                    if o.type != "MESH":
                        continue
                    if mat.name in o.data.materials and o not in objs:
                        objs.append(o)

            for o in objs:
                if self.vcol_name not in get_vertex_colors(o):
                    data_type, domain = get_vcol_data_type_and_domain_by_name(
                        o, self.vcol_name, objs
                    )
                    other_v = new_vertex_color(
                        o,
                        self.vcol_name,
                        data_type,
                        domain,
                        color_fill=(1.0, 1.0, 1.0, 1.0),
                    )
                    set_active_vertex_color(o, other_v)

        # Add new mask
        mask = add_new_mask(
            layer,
            name,
            self.type,
            self.texcoord_type,
            self.uv_map,
            image,
            self.vcol_name,
            blend_type=self.blend_type,
            source_input=self.source_input,
            interpolation=self.interpolation,
        )

        # Enable edit mask
        if self.type in {"IMAGE", "VCOL"} and self.source_input == "RGB":
            mask.active_edit = True

        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        reconnect_mp_nodes(layer.id_data)
        rearrange_mp_nodes(layer.id_data)

        # Make sure all layers which used the opened image is using correct linear color
        if self.type == "IMAGE":
            check_mp_linear_nodes(mp)

        mpui.layer_ui.expand_masks = True
        mpui.need_update = True
        if self.texcoord_type == "Decal":
            mask.expand_content = True
            mask.expand_vector = True

        return {"FINISHED"}


# Classes for auto-registration by bootstrap
classes = (MOpenAvailableDataAsMask,)
