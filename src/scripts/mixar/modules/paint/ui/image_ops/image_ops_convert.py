# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image bit depth conversion operator"""

import re

import bpy

from ...core.node.check_nodes import check_mp_linear_nodes
from ...core.node.node_utils import get_active_mpaint_node
from .image_ops_utils import toggle_image_bit_depth


class MConvertImageBitDepth(bpy.types.Operator):
    """Convert Image Bit Depth"""

    bl_idname = "image.y_convert_image_bit_depth"
    bl_label = "Convert Image Bit Depth"
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
        """Convert the image between 8-bit and 32-bit float formats.

        Args:
            context: The Blender context.

        Returns:
            Set containing 'FINISHED' on success or 'CANCELLED' on error.
        """
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        # Do not convert colorspace if entity is a mask
        convert_colorspace = False
        m1 = re.match(r"^mp\.layers\[(\d+)\]$", context.entity.path_from_id())
        m2 = re.match(
            r"^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", context.entity.path_from_id()
        )
        m3 = re.match(
            r"^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$", context.entity.path_from_id()
        )
        if m1:
            layer = mp.layers[int(m1.group(1))]
            convert_colorspace = True
        elif m2:
            layer = mp.layers[int(m2.group(1))]
        elif m3:
            layer = mp.layers[int(m3.group(1))]
        else:
            self.report({"ERROR"}, "Wrong context!")
            return {"CANCELLED"}

        image = context.image

        if image.yua.is_udim_atlas or image.yia.is_image_atlas:
            self.report(
                {"ERROR"}, "Cannot convert image atlas segment to different bit depth!"
            )
            return {"CANCELLED"}

        toggle_image_bit_depth(image, convert_colorspace=convert_colorspace)

        # Update image editor by setting active layer index
        mp.active_layer_index = mp.active_layer_index

        # Refresh linear nodes
        check_mp_linear_nodes(mp, specific_layer=layer, reconnect=True)

        return {"FINISHED"}


# Classes for registration
classes = (MConvertImageBitDepth,)
