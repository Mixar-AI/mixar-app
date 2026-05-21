# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UIList for displaying custom bake targets in the Export Textures section."""

import bpy
from bpy.types import UIList


class BAKE_UL_bake_target_list(UIList):
    """UIList for displaying custom bake targets.

    Displays each bake target with:
    - Image name if baked (editable), else bake target name
    - Dirty indicator (*) if image.is_dirty
    - Packed indicator (PACKAGE icon) if image.packed_file
    """

    bl_idname = "BAKE_UL_bake_target_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        """Draw a single bake target item.

        Args:
            context: Blender context.
            layout: UI layout to draw into.
            data: The MPaint collection owner.
            item: The MBakeTarget item to draw.
            icon: Default icon.
            active_data: Active data reference (mp).
            active_propname: Active property name (active_bake_target_index).
            index: Index of the item in the collection.
        """
        bt = item  # MBakeTarget

        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)

            # Get the bake target's image (if it has been baked)
            tree = data.id_data  # The node tree owning the MPaint PropertyGroup
            bt_node = tree.nodes.get(bt.image_node)
            has_image = bt_node and bt_node.image

            if has_image:
                image = bt_node.image
                # Show editable image name
                row.prop(image, "name", text="", emboss=False, icon='IMAGE_DATA')

                # Dirty indicator
                if image.is_dirty:
                    row.label(text="*")

                # Packed indicator
                if image.packed_file:
                    row.label(text="", icon='PACKAGE')
            else:
                # Show bake target name (not yet baked)
                row.prop(bt, "name", text="", emboss=False, icon='RENDER_STILL')

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='IMAGE_DATA')

    def filter_items(self, context, data, propname):
        """Filter and order items in the list.

        Args:
            context: Blender context.
            data: Data containing the collection.
            propname: Name of the collection property.

        Returns:
            Tuple of (filter_flags, filter_neworder) lists.
        """
        items = getattr(data, propname)
        filter_flags = [self.bitflag_filter_item] * len(items)
        filter_neworder = []
        return filter_flags, filter_neworder


# Classes for registration (auto-discovered by bootstrap)
classes = (
    BAKE_UL_bake_target_list,
)
