# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Color space utilities for Mixar modules."""

import bpy


def remove_datablock(blocks, block, user=None, user_prop=""):
    """Remove a datablock from a Blender data collection.

    Args:
        blocks: The Blender data collection (e.g., bpy.data.images, bpy.data.materials).
        block: The datablock to remove.
        user: Optional object that uses this datablock.
        user_prop (str): Optional property name on user to clear.

    Returns:
        None
    """
    if user and user_prop:
        setattr(user, user_prop, None)
    blocks.remove(block)


def get_noncolor_name():
    """Get the correct non-color/raw colorspace name for the current Blender version.

    Checks for "Non-Color" colorspace name, tries "raw" alternative, or creates
    a temporary float image to determine the default non-color colorspace name.

    Returns:
        str: The non-color colorspace name (e.g., "Non-Color" or "Raw").
    """
    names = (
        bpy.types.Image.bl_rna.properties["colorspace_settings"]
        .fixed_type.properties["name"]
        .enum_items.keys()
    )
    if "Non-Color" not in names:

        # Try 'raw' name
        for name in names:
            if name.lower() == "raw":
                return name

        # Check non-color name by creating new float image
        # The paint module's WM property group may be unregistered (add-on
        # load order, paint-only uninstall) — compute the name fresh in that
        # case instead of raising AttributeError.
        mpprops = getattr(bpy.context.window_manager, "mpprops", None)

        if mpprops is None:
            temp_image = bpy.data.images.new(
                "temmmmp", width=1, height=1, alpha=False, float_buffer=True
            )
            name = temp_image.colorspace_settings.name
            remove_datablock(bpy.data.images, temp_image)
            return name

        if mpprops.custom_noncolor_name == "":
            temp_image = bpy.data.images.new(
                "temmmmp", width=1, height=1, alpha=False, float_buffer=True
            )
            mpprops.custom_noncolor_name = temp_image.colorspace_settings.name
            remove_datablock(bpy.data.images, temp_image)

        return mpprops.custom_noncolor_name

    return "Non-Color"
