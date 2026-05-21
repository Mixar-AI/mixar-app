# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Basic image operations: copy path, open folder, invert, refresh, pack"""

import os
import subprocess
import sys
import time

import bpy

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.layer.check_layers import is_overlay_normal_empty
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.common import get_addon_title
from .image_ops_operators_helper import pack_image


class MCopyImagePathToClipboard(bpy.types.Operator):
    bl_idname = "wm.copy_image_path_to_clipboard"
    bl_label = "Copy Image Path To Clipboard"
    bl_description = (
        get_addon_title() + " Copy the image file path to the system clipboard"
    )

    clipboard_text: bpy.props.StringProperty()

    def execute(self, context):
        """Copy the image file path to the system clipboard.

        Args:
            context: The Blender context.

        Returns:
            Set containing 'FINISHED' status.
        """
        context.window_manager.clipboard = self.clipboard_text
        self.report({"INFO"}, "Copied: " + self.clipboard_text)
        return {"FINISHED"}


class MOpenContainingImageFolder(bpy.types.Operator):
    bl_idname = "wm.open_containing_image_folder"
    bl_label = "Open Containing Image Folder"
    bl_description = (
        get_addon_title()
        + " Open the folder containing the image file and highlight it"
    )

    file_path: bpy.props.StringProperty()

    def execute(self, context):
        """Open the folder containing the image file and highlight it.

        Opens the file manager on the current platform (Windows Explorer, macOS Finder,
        or Linux file manager) and highlights the specified image file.

        Args:
            context: The Blender context.

        Returns:
            Set containing 'FINISHED' on success or 'CANCELLED' on error.
        """
        filepath = bpy.path.abspath(self.file_path)
        if not os.path.exists(filepath):
            self.report({"ERROR"}, "File does not exist")
            return {"CANCELLED"}
        try:
            # Add more branches below for different operating systems
            if sys.platform == "win32":  # Windows
                subprocess.call(["explorer", "/select,", filepath])
            elif sys.platform == "darwin":  # Mac
                subprocess.call(["open", "-R", filepath])
            elif sys.platform == "linux":  # Linux
                subprocess.check_call(
                    [
                        "dbus-send",
                        "--session",
                        "--print-reply",
                        "--dest=org.freedesktop.FileManager1",
                        "--type=method_call",
                        "/org/freedesktop/FileManager1",
                        "org.freedesktop.FileManager1.ShowItems",
                        "array:string:file://" + os.path.normpath(filepath),
                        'string:""',
                    ]
                )
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class MInvertImage(bpy.types.Operator):
    """Invert Image"""

    bl_idname = "wm.m_invert_image"
    bl_label = "Invert Image"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            context: The Blender context.

        Returns:
            True if context has an image, False otherwise.
        """
        return hasattr(context, "image") and context.image

    def execute(self, context):
        """Invert the RGB channels of the active image.

        Args:
            context: The Blender context.

        Returns:
            Set containing 'FINISHED' on success or 'CANCELLED' if image is an atlas.
        """

        if context.image.yia.is_image_atlas:
            self.report({"ERROR"}, "Cannot invert image atlas!")
            return {"CANCELLED"}

        # For some reason this no longer works since Blender 2.82, but worked again in Blender 4.2
        override = bpy.context.copy()
        override["edit_image"] = context.image
        with bpy.context.temp_override(**override):
            bpy.ops.image.invert(invert_r=True, invert_g=True, invert_b=True)

        return {"FINISHED"}


class MRefreshImage(bpy.types.Operator):
    """Reload Image"""

    bl_idname = "wm.m_reload_image"
    bl_label = "Reload Image"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            context: The Blender context.

        Returns:
            True if context has an image, False otherwise.
        """
        return hasattr(context, "image") and context.image

    def execute(self, context):
        """Reload the active image from disk and refresh the viewport.

        Args:
            context: The Blender context.

        Returns:
            Set containing 'FINISHED' status.
        """
        # Reload image
        context.image.reload()

        # Refresh viewport and image editor
        for area in context.screen.areas:
            if area.type in ["VIEW_3D", "IMAGE_EDITOR", "NODE_EDITOR"]:
                area.tag_redraw()

        return {"FINISHED"}


class MPackImage(bpy.types.Operator):
    """Pack Image"""

    bl_idname = "wm.m_pack_image"
    bl_label = "Pack Image"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            context: The Blender context.

        Returns:
            True if context has an unpacked image, False otherwise.
        """
        return (
            hasattr(context, "image")
            and context.image
            and not context.image.packed_file
        )

    def execute(self, context):
        """Pack the active image and related baked images into the blend file.

        Args:
            context: The Blender context.

        Returns:
            Set containing 'FINISHED' status.
        """

        T = time.time()

        pack_image(context.image)
        context.image.filepath = ""

        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp

        if mp.use_baked and mp.active_channel_index < len(mp.channels):
            ch = mp.channels[mp.active_channel_index]
            if ch.type == "NORMAL":

                baked_disp = tree.nodes.get(ch.baked_disp)
                if baked_disp and baked_disp.image and not baked_disp.image.packed_file:
                    pack_image(baked_disp.image)
                    baked_disp.image.filepath = ""

                baked_vdisp = tree.nodes.get(ch.baked_vdisp)
                if (
                    baked_vdisp
                    and baked_vdisp.image
                    and not baked_vdisp.image.packed_file
                ):
                    pack_image(baked_vdisp.image)
                    baked_vdisp.image.filepath = ""

                if not is_overlay_normal_empty(ch):
                    baked_normal_overlay = tree.nodes.get(ch.baked_normal_overlay)
                    if (
                        baked_normal_overlay
                        and baked_normal_overlay.image
                        and not baked_normal_overlay.image.packed_file
                    ):
                        pack_image(baked_normal_overlay.image)

                    baked_normal_overlay.image.filepath = ""

        logger.info(
            "%s image is packed in %s ms!",
            context.image.name, "{:0.2f}".format((time.time() - T) * 1000)
        )

        return {"FINISHED"}


# Classes for registration
classes = (
    MCopyImagePathToClipboard,
    MOpenContainingImageFolder,
    MInvertImage,
    MRefreshImage,
    MPackImage,
)
