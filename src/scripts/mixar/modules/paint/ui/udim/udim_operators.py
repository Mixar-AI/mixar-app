# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
import time

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)
from bpy.props import IntProperty

from ...core.element.update_image import (
    copy_image_pixels,
    replace_image,
    update_image_editor_image,
)
from ...core.layer.get_entities import get_mp_entities_images_and_segments
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_srgb_name,
    set_image_paint_canvas,
)
from .udim_operators_helper import (
    fill_tile,
    remove_udim_atlas_segment_by_index,
)
from ..udim.udim_utils import (
    get_set_udim_atlas_segment,
    get_tile_numbers,
    initial_pack_udim,
    refresh_udim_atlas,
)


class MRefillUDIMTiles(bpy.types.Operator):
    bl_idname = "wm.m_refill_udim_tiles"
    bl_label = "Refill UDIM Tiles"
    bl_description = (
        "Refill all UDIM tiles used by all layers and masks based on their UV"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed.

        Args:
            context: Blender context.

        Returns:
            bool: True if active mpaint node exists, False otherwise.
        """
        return get_active_mpaint_node()

    def execute(self, context):
        """Refill all UDIM tiles used by layers and masks based on UV coordinates.

        Args:
            context: Blender context containing layer data.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} if context has no layer.
        """
        T = time.time()

        if not hasattr(context, "layer"):
            return {"CANCELLED"}

        mp = context.layer.id_data.mp
        entities, images, segment_names, segment_name_props = (
            get_mp_entities_images_and_segments(mp)
        )

        mat = get_active_material()

        refreshed_images = []

        for i, image in enumerate(images):
            if image.source != "TILED":
                continue

            ents = entities[i]
            entity = ents[0]

            if image.yua.is_udim_atlas:
                if image not in refreshed_images:
                    refresh_udim_atlas(image, mp)
                    refreshed_images.append(image)

            else:
                # Get tile numbers based from uv
                uv_name = (
                    entity.uv_name if not entity.use_baked else entity.baked_uv_name
                )
                objs = get_all_objects_with_same_materials(mat, True, uv_name)
                tilenums = get_tile_numbers(objs, uv_name)

                # Get width and height
                width = 1024
                height = 1024
                if image.size[0] != 0:
                    width = image.size[0]
                if image.size[1] != 0:
                    height = image.size[1]

                color = image.yui.base_color

                for tilenum in tilenums:
                    fill_tile(image, tilenum, color, width, height, empty_only=True)

                initial_pack_udim(image)

        logger.info(
            "Refilling UDIM is done in %s ms!",
            "{:0.2f}".format((time.time() - T) * 1000),
        )

        return {"FINISHED"}


class MNewUDIMAtlasSegmentTest(bpy.types.Operator):
    bl_idname = "image.y_new_udim_atlas_segment_test"
    bl_label = "New UDIM Atlas Segment Test"
    bl_description = "New UDIM Atlas segment test"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed.

        Args:
            context: Blender context.

        Returns:
            bool: Always True.
        """
        return True

    def execute(self, context):
        """Create a new UDIM atlas segment for testing purposes.

        Args:
            context: Blender context containing active material and object.

        Returns:
            set: {'FINISHED'} on success.
        """
        mat = get_active_material()
        obj = get_active_object()
        uv_name = obj.data.uv_layers.active.name

        objs = get_all_objects_with_same_materials(mat, True, uv_name)
        tilenums = get_tile_numbers(objs, uv_name)

        new_segment = get_set_udim_atlas_segment(
            tilenums,
            1024,
            1024,
            color=(0, 0, 0, 0),
            colorspace=get_srgb_name(),
            hdr=False,
        )

        image = new_segment.id_data

        area = context.area
        if hasattr(area.spaces[0], "image"):
            area.spaces[0].image = image

        return {"FINISHED"}


class MRefreshUDIMAtlasOffset(bpy.types.Operator):
    bl_idname = "image.y_refresh_udim_atlas_offset"
    bl_label = "Refresh UDIM Atlas Offset"
    bl_description = "Refresh UDIM Atlas offset based on current UV islands"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed.

        Args:
            context: Blender context.

        Returns:
            bool: Always True.
        """
        return True

    def execute(self, context):
        """Refresh UDIM atlas offset based on current UV islands.

        Args:
            context: Blender context containing area with active image.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} if image is not a UDIM atlas.
        """
        mat = get_active_material()
        uv_name = "UVMap"

        area = context.area
        image = area.spaces[0].image
        if not image.yua.is_udim_atlas:
            return {"CANCELLED"}

        refresh_udim_atlas(image)

        return {"FINISHED"}


class MRemoveUDIMAtlasSegment(bpy.types.Operator):
    bl_idname = "image.y_remove_udim_atlas_segment"
    bl_label = "Remove UDIM Atlas Segment"
    bl_description = "Remove UDIM Atlas segment"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(
        name="Segment Index", description="UDIM Atlas Segment Index", default=0
    )

    def invoke(self, context, event):
        """Display property dialog for operator.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Result of invoke_props_dialog.
        """
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        """Draw operator UI in dialog.

        Args:
            context: Blender context.

        Returns:
            None
        """
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== SEGMENT ==========
        box = main_col.box()
        col = box.column(align=False)

        # Header
        header_row = col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Segment", icon="UV")

        col.separator(factor=1.2)

        # Index property
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Index:")
        split.prop(self, 'index', text="")

        col.separator(factor=0.4)

        col.separator(factor=0.8)  # Section end
        main_col.separator(factor=0.8)

    def execute(self, context):
        """Remove UDIM atlas segment by index.

        Args:
            context: Blender context containing area with active image.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} if image is not a UDIM atlas.
        """
        mat = get_active_material()
        uv_name = "UVMap"

        area = context.area
        image = area.spaces[0].image
        if not image.yua.is_udim_atlas:
            return {"CANCELLED"}

        # Remove segment
        remove_udim_atlas_segment_by_index(image, self.index)

        return {"FINISHED"}


class MConvertImageTiled(bpy.types.Operator):
    """Convert non tiled image to tiled image and vice versa"""

    bl_idname = "image.y_convert_image_tiled"
    bl_label = "Convert Image Tiled"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed.

        Args:
            context: Blender context.

        Returns:
            bool: True if context has an image, False otherwise.
        """
        return hasattr(context, "image") and context.image

    def execute(self, context):
        """Convert image between tiled and non-tiled formats.

        Args:
            context: Blender context containing image and optional entity data.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on error.
        """
        image = context.image

        if image.yua.is_udim_atlas or image.yia.is_image_atlas:
            self.report(
                {"ERROR"}, "Converting image atlas to/from UDIM is not supported yet!"
            )
            return {"CANCELLED"}

        # Create new image
        new_image = bpy.data.images.new(
            image.name,
            width=image.size[0],
            height=image.size[1],
            alpha=True,
            float_buffer=image.is_float,
            tiled=not image.source == "TILED",
        )

        if new_image.source == "TILED":

            # Update tile numbers if necessary
            tilenums = [1001]
            color = (0, 0, 0, 0)
            if hasattr(context, "entity") and context.entity:

                # Mask will use only black color for now
                # TODO: Detect if mask is closer to black or white
                match = re.match(
                    r"^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$",
                    context.entity.path_from_id(),
                )
                if match:
                    color = (0, 0, 0, 1)

                uv_name = context.entity.uv_name
                mat = get_active_material()
                objs = get_all_objects_with_same_materials(mat, True, uv_name)
                tilenums = get_tile_numbers(objs, uv_name)

            for tilenum in tilenums:
                fill_tile(new_image, tilenum, color, image.size[0], image.size[1])

            initial_pack_udim(new_image, color)

        # Copy colorspace and alpha mode
        new_image.colorspace_settings.name = image.colorspace_settings.name
        new_image.alpha_mode = image.alpha_mode

        # Copy image pixels
        copy_image_pixels(image, new_image)

        # Replace image
        replace_image(image, new_image)

        # Update image editor by setting active layer index
        node = get_active_mpaint_node()
        if node:
            mp = node.node_tree.mp
            mp.active_layer_index = mp.active_layer_index
        else:
            update_image_editor_image(context, new_image)
            set_image_paint_canvas(new_image)

        return {"FINISHED"}
