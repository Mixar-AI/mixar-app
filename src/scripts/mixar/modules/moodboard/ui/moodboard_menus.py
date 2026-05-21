# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Context Menus

Right-click context menu for moodboard operations.
"""

import bpy
from bpy.types import Menu

from mixar.modules.common.utils.mixie_space_utils import (
    MIXIE_SPACE_AVAILABLE,
    get_selected_moodboard_items,
)


class MIXIE_MT_moodboard_context_menu(Menu):
    """Right-click context menu for moodboard"""
    bl_label = "Moodboard"
    bl_idname = "MIXIE_MT_moodboard_context_menu"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Check selection state
        selected_images, selected_textboxes, selected_groups = (
            get_selected_moodboard_items(scene)
        )
        total_items_selected = selected_images + selected_textboxes

        # Check if any selected images belong to a group
        has_grouped_selection = any(
            img.selected and img.group_index >= 0
            for img in scene.mixie_moodboard_images
        )

        # Group operations - show contextually
        if selected_groups > 0 or has_grouped_selection:
            layout.operator("mixie.ungroup", text="Ungroup", icon='UGLYPACKAGE')
            layout.separator()
        elif total_items_selected >= 2:
            layout.operator("mixie.create_group", text="Group", icon='GROUP')
            layout.separator()

        # Add content
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.operator("mixie.moodboard_add_existing_image", text="Add Existing Image", icon='TRIA_DOWN')
        layout.operator("mixie.moodboard_add_image", text="Open Image", icon='FILE_FOLDER')
        layout.operator("mixie.moodboard_paste_image", text="Paste from Clipboard", icon='PASTEDOWN')
        layout.operator("mixie.moodboard_add_textbox", text="Add Text", icon='FONT_DATA')

        layout.separator()

        # Text box editing (only shown when exactly one text box is selected)
        if selected_textboxes == 1:
            for i, tb in enumerate(scene.mixie_moodboard_textboxes):
                if tb.selected:
                    layout.operator_context = 'INVOKE_DEFAULT'
                    op = layout.operator(
                        "mixie.moodboard_edit_textbox",
                        text="Edit Text Content",
                        icon='GREASEPENCIL',
                    )
                    op.index = i

                    op2 = layout.operator(
                        "mixie.moodboard_update_textbox_properties",
                        text="Edit Text Properties",
                        icon='PROPERTIES',
                    )
                    op2.index = i
                    break
            layout.separator()

        # Transform operations (only enabled when images are selected)
        row = layout.row()
        row.enabled = selected_images > 0
        row.operator("mixie.moodboard_crop_tool", text="Crop", icon='FULLSCREEN_EXIT')

        row = layout.row()
        row.enabled = selected_images > 0
        row.operator("mixie.rotate_images", text="Rotate 90°", icon='LOOP_FORWARDS').angle = 90.0

        row = layout.row()
        row.enabled = selected_images > 0
        row.operator("mixie.flip_horizontal", text="Flip Horizontal", icon='ARROW_LEFTRIGHT')

        row = layout.row()
        row.enabled = selected_images > 0
        row.operator("mixie.flip_vertical", text="Flip Vertical", icon='EMPTY_SINGLE_ARROW')

        row = layout.row()
        row.enabled = total_items_selected > 0
        row.operator("mixie.moodboard_duplicate", text="Duplicate", icon='DUPLICATE')

        layout.separator()

        # Selection
        layout.operator("mixie.moodboard_select_all", text="Select All", icon='CHECKBOX_HLT')
        layout.operator("mixie.moodboard_deselect_all", text="Deselect All", icon='CHECKBOX_DEHLT')

        layout.separator()

        # Export (only enabled when images are selected)
        row = layout.row()
        row.enabled = selected_images > 0
        row.operator("mixie.moodboard_export_images", text="Export", icon='EXPORT')

        layout.separator()

        # Delete (only enabled when something is selected)
        row = layout.row()
        row.enabled = (total_items_selected + selected_groups) > 0
        row.operator("mixie.moodboard_delete", text="Delete", icon='TRASH')


# Only include menu if MIXIE space is available
classes = (
    MIXIE_MT_moodboard_context_menu,
) if MIXIE_SPACE_AVAILABLE else ()
