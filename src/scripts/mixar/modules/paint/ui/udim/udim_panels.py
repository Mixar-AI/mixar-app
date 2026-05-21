# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy

from ...core.lib.lib_operations import get_icon


class M_PT_UDIM_Atlas_menu(bpy.types.Panel):
    bl_label = "UDIM Atlas"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Image"

    @classmethod
    def poll(cls, context):
        """Check if panel should be displayed.

        Args:
            context: Blender context.

        Returns:
            bool: Always True.
        """
        return True

    def draw(self, context):
        """Draw panel UI in Image Editor.

        Args:
            context: Blender context.

        Returns:
            None
        """
        c = self.layout.column()
        c.operator("image.y_new_udim_atlas_segment_test", icon_value=get_icon("image"))
        c.operator("image.y_refresh_udim_atlas_offset", icon_value=get_icon("image"))
        c.operator("image.y_remove_udim_atlas_segment", icon_value=get_icon("image"))
