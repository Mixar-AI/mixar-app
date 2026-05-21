# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Save operations: save image, save all baked, save/pack all"""

import os
import time

import bpy
from bpy.props import BoolProperty, EnumProperty

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.layer.check_layers import is_overlay_normal_empty
from ...core.layer.layer_utils import get_root_height_channel
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import duplicate_image, get_srgb_name, remove_datablock
from ...utils.common import get_addon_title
from .image_ops_operators_helper import (
    pack_image,
    remove_unpacked_image_path,
    save_float_image,
    save_pack_all,
)
from .image_ops_utils import format_extensions


class MSaveImage(bpy.types.Operator):
    """Save Image"""

    bl_idname = "wm.m_save_image"
    bl_label = "Save Image"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            context: The Blender context.

        Returns:
            True if context has an unpacked image with a filepath, False otherwise.
        """
        return (
            hasattr(context, "image")
            and context.image
            and context.image.filepath != ""
            and not context.image.packed_file
        )

    def execute(self, context):
        """Save the active image to its current filepath.

        Args:
            context: The Blender context.

        Returns:
            Set containing 'FINISHED' status.
        """
        ori_colorspace = context.image.colorspace_settings.name
        if context.image.is_float:
            save_float_image(context.image)
        else:
            context.image.save()
        context.image.colorspace_settings.name = ori_colorspace
        return {"FINISHED"}


class MSaveAllBakedImages(bpy.types.Operator):
    """Save All Baked Images to directory"""

    bl_idname = "wm.m_save_all_baked_images"
    bl_label = "Save All Baked Images"
    bl_options = {"REGISTER", "UNDO"}

    # Define this to tell 'fileselect_add' that we want a directoy
    directory: bpy.props.StringProperty(
        name="Outdir Path",
        description="Where I will save my stuff",
    )

    remove_whitespaces: bpy.props.BoolProperty(
        name="Remove Whitespaces",
        description="Remove whitespaces from baked image names",
        default=False,
    )

    file_format: EnumProperty(
        name="File Format",
        items=(
            ("PNG", "PNG", "", "IMAGE_DATA", 0),
            ("TIFF", "TIFF", "", "IMAGE_DATA", 1),
            ("OPEN_EXR", "OpenEXR", "", "IMAGE_DATA", 2),
        ),
        default="PNG",
    )

    copy: BoolProperty(
        name="Copy",
        description="Create a new image file without modifying the current image in Blender",
        default=False,
    )

    force_exr_vdisp: BoolProperty(
        name="Use EXR for Baked VDM",
        description="Always use EXR file format for baked vector displacement image",
        default=True,
    )

    def invoke(self, context, event):
        """Open the directory browser for selecting output directory.

        Args:
            context: The Blender context.
            event: The Blender event that triggered the operator.

        Returns:
            Set containing 'RUNNING_MODAL' to wait for user input.
        """
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        """Draw the operator's UI panel.

        Args:
            context: The Blender context.

        Returns:
            None
        """
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== SAVE OPTIONS ==========
        box = main_col.box()
        col = box.column(align=False)

        # Header
        header_row = col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Save Options", icon="FILE_IMAGE")

        col.separator(factor=1.2)

        # Image Format
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Image Format:")
        split.prop(self, "file_format", text="")

        col.separator(factor=0.4)

        # Copy checkbox
        row = col.row(align=True)
        row.scale_y = 1.2
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Copy:")
        split.prop(self, "copy", text="")

        node = get_active_mpaint_node()
        if node and self.file_format != "OPEN_EXR":
            tree = node.node_tree
            mp = tree.mp
            height_root_ch = get_root_height_channel(mp)
            if height_root_ch:
                baked_vdisp = tree.nodes.get(height_root_ch.baked_vdisp)
                if baked_vdisp and baked_vdisp.image:
                    col.separator(factor=0.4)

                    # Force EXR VDisp checkbox
                    row = col.row(align=True)
                    row.scale_y = 1.2
                    split = row.split(factor=0.25, align=True)
                    label_col = split.column(align=True)
                    label_col.alignment = "RIGHT"
                    label_col.label(text="Use EXR for VDM:")
                    split.prop(self, "force_exr_vdisp", text="")

        col.separator(factor=0.8)
        main_col.separator(factor=0.8)

    def execute(self, context):
        """Save all baked images to the selected directory.

        Args:
            context: The Blender context.

        Returns:
            Set containing 'FINISHED' status.
        """

        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp

        tmpscene = bpy.data.scenes.new("Temp Save As Scene")
        settings = tmpscene.render.image_settings

        # Blender 2.80 has filmic as default color settings, change it to standard
        tmpscene.view_settings.view_transform = "Standard"

        images = []

        height_root_ch = get_root_height_channel(mp)

        # Baked images
        baked_vdisp_image = None
        for ch in mp.channels:
            if ch.no_layer_using:
                continue

            baked = tree.nodes.get(ch.baked)
            if baked and baked.image:
                images.append(baked.image)

            if ch == height_root_ch:

                baked_disp = tree.nodes.get(ch.baked_disp)
                if baked_disp and baked_disp.image:
                    images.append(baked_disp.image)

                baked_vdisp = tree.nodes.get(ch.baked_vdisp)
                if baked_vdisp and baked_vdisp.image:
                    images.append(baked_vdisp.image)
                    baked_vdisp_image = baked_vdisp.image

                if not is_overlay_normal_empty(ch):
                    baked_normal_overlay = tree.nodes.get(ch.baked_normal_overlay)
                    if baked_normal_overlay and baked_normal_overlay.image:
                        images.append(baked_normal_overlay.image)

        # Custom bake target images
        for bt in mp.bake_targets:
            image_node = tree.nodes.get(bt.image_node)
            if image_node and image_node.image not in images:
                images.append(image_node.image)

        original_image_names = []
        original_names = []
        if self.copy:
            copied_images = []
            for image in images:
                ori_name = image.name
                image_copy = duplicate_image(image, ondisk_duplicate=False)
                image.name += "____"
                image_copy.name = ori_name
                original_image_names.append(image.name)
                original_names.append(ori_name)
                copied_images.append(image_copy)

            images = copied_images

        for image in images:

            if image == baked_vdisp_image and self.force_exr_vdisp:
                settings.file_format = "OPEN_EXR"
            else:
                settings.file_format = self.file_format

            settings.color_depth = "8" if settings.file_format != "OPEN_EXR" else "16"
            if image.is_float:
                settings.color_depth = (
                    "16" if settings.file_format != "OPEN_EXR" else "32"
                )
            if settings.file_format == "OPEN_EXR":
                settings.exr_codec = "ZIP"

            if image.filepath == "" or ".<UDIM>." in image.filepath:
                image_name = image.name
                # Remove addon title from the file names
                if image_name.startswith(get_addon_title() + " "):
                    image_name = image_name.replace(get_addon_title() + " ", "")
                filename = image_name
                filename += ".<UDIM>" if ".<UDIM>." in image.filepath else ""
                filename += format_extensions[settings.file_format]
            else:
                filename = bpy.path.basename(image.filepath)
                ext = os.path.splitext(filename)[1]

                if ext != format_extensions[settings.file_format]:
                    filename = filename.replace(
                        ext, format_extensions[settings.file_format]
                    )

            if self.remove_whitespaces:
                filename = filename.replace(" ", "")

            path = os.path.join(self.directory, filename)

            # Need to pack first to save the image
            if image.is_dirty:
                pack_image(image)

            # Some images need to set to srgb when saving
            ori_colorspace = image.colorspace_settings.name
            if not image.is_float and image.colorspace_settings.name != get_srgb_name():
                image.colorspace_settings.name = get_srgb_name()

            # Unpack image if image is packed (Only necessary for Blender 2.80 and lower)
            unpacked_to_disk = False

            # Save image
            image.save_render(path, scene=tmpscene)

            # Set the filepath to the image
            image.filepath = path
            if bpy.data.filepath != "":
                try:
                    image.filepath = bpy.path.relpath(path)
                except:
                    pass

            # Set back colorspace settings
            if image.colorspace_settings.name != ori_colorspace:
                image.colorspace_settings.name = ori_colorspace

            # Remove temporarily unpacked image
            if unpacked_to_disk:
                remove_unpacked_image_path(
                    image,
                    path,
                    default_dir,
                    default_dir_found,
                    default_filepath,
                    temp_path,
                    unpacked_path,
                )

            # Remove packed flag
            if image.packed_file:
                image.unpack(method="REMOVE")

        # Remove copied images
        if self.copy:
            for image in reversed(images):
                remove_datablock(bpy.data.images, image)

        # Recover image names
        for i, ori_image_name in enumerate(original_image_names):
            ori_image = bpy.data.images.get(ori_image_name)
            ori_image.name = original_names[i]

        # Delete temporary scene
        remove_datablock(bpy.data.scenes, tmpscene)

        return {"FINISHED"}


class MSavePackAll(bpy.types.Operator):
    """Save and Pack All Image Layers"""

    bl_idname = "wm.m_save_pack_all"
    bl_label = "Save and Pack All Image Layers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            context: The Blender context.

        Returns:
            True if there is an active MPaint node, False otherwise.
        """
        return get_active_mpaint_node()

    def execute(self, context):
        """Save or pack all image layers in the MPaint node tree.

        Args:
            context: The Blender context.

        Returns:
            Set containing 'FINISHED' status.
        """
        mpui = bpy.context.window_manager.mpui
        mp = get_active_mpaint_node().node_tree.mp
        save_pack_all(mp)
        mpui.refresh_image_hack = False
        return {"FINISHED"}


# Classes for registration
classes = (
    MSaveImage,
    MSaveAllBakedImages,
    MSavePackAll,
)
