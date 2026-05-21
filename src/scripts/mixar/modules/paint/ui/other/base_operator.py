# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, StringProperty

from ...utils.blender_commons import load_image


class FileSelectOptions:
    # File browser filter
    filter_folder: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})
    filter_image: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})

    display_type: EnumProperty(
        items=(
            ("FILE_DEFAULTDISPLAY", "Default", ""),
            ("FILE_SHORTDISLPAY", "Short List", ""),
            ("FILE_LONGDISPLAY", "Long List", ""),
            ("FILE_IMGDISPLAY", "Thumbnails", ""),
        ),
        default="FILE_IMGDISPLAY",
        options={"HIDDEN", "SKIP_SAVE"},
    )


class OpenImage(FileSelectOptions):

    # File related
    files: CollectionProperty(
        type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"}
    )
    directory: StringProperty(
        maxlen=1024, subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"}
    )

    relative: BoolProperty(
        name="Relative Path", default=True, description="Apply relative paths"
    )

    def running_fileselect_modal(self, context, event):
        """Opens the file browser in modal mode.

        Args:
            context (bpy.types.Context): The current Blender context.
            event (bpy.types.Event): The event that triggered this call.

        Returns:
            set: A set containing 'RUNNING_MODAL' to indicate modal operation.
        """
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def check(self, context):
        """Checks if the operator properties have changed.

        Args:
            context (bpy.types.Context): The current Blender context.

        Returns:
            bool: Always returns True to indicate the operator should update.
        """
        return True

    def generate_paths(self):
        """Generates file paths from the selected files.

        Returns:
            tuple: A tuple containing:
                - generator: Generator of file names from the selected files.
                - str: The directory path where the files are located.
        """
        return (fn.name for fn in self.files), self.directory

    def get_loaded_images(self):
        """Loads all selected images from the file browser.

        Returns:
            tuple: A tuple of loaded bpy.types.Image objects.
        """
        import_list, directory = self.generate_paths()
        loaded_images = tuple(load_image(path, directory) for path in import_list)

        return loaded_images
