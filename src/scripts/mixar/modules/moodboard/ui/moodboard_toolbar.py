# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Toolbar Panel

Left T-panel toolbar with core moodboard actions:
  • Add Image  — add an existing or new image from disk
  • Add Text   — add a text box to the canvas
  • Crop       — crop the selected image
  • Mask Tools — popover with Box Mask, Lasso, and Magic Select
  • Rotate     — rotate selected image 90° clockwise
  • Send to Chat — send selected image(s) to Mixie Chat
"""

import bpy
from bpy.types import Menu, Panel


from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE


# Icon shown for each mask tool state
_MASK_TOOL_ICONS = {
    'BOX_MASK':    'SELECT_SET',
    'LASSO':       'OUTLINER_DATA_GP_LAYER',
    'MAGIC_SELECT': 'SNAP_FACE',
}
_MASK_ICON_DEFAULT = 'MOD_MASK'


# A Menu (not a popover) so it auto-dismisses the instant an option is
# picked. Both add operators return RUNNING_MODAL from invoke() (a file
# browser / a search popup), and a popover lingers behind those modals
# instead of closing — a menu closes on item-click, before invoke runs.
# NOTE: kept as a comment, not a docstring — a Menu's docstring is shown
# as the button tooltip, and this rationale isn't meant for users.
class MIXIE_MT_add_image_menu(Menu):
    """Dropdown menu with image-adding options."""
    bl_idname = "MIXIE_MT_add_image_menu"
    bl_label = "Add Image"

    def draw(self, context):
        layout = self.layout
        # INVOKE_DEFAULT so each operator's invoke() runs (opening its
        # file browser / search popup) rather than executing headless.
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.operator(
            "mixie.moodboard_add_image",
            text="Open Image",
            icon='FILE_FOLDER',
        )
        layout.operator(
            "mixie.moodboard_add_existing_image",
            text="Add Existing Image",
            icon='IMAGE_DATA',
        )


class MIXIE_PT_mask_tools_popover(Panel):
    """
    Popover panel with all mask selection tools.
    Opened by clicking the single Mask Tools button in the toolbar.
    """
    bl_idname = "MIXIE_PT_mask_tools_popover"
    bl_label = "Mask Tools"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 9
    bl_options = {'INSTANCED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        active_tool = 'NONE'
        if hasattr(scene, 'mixie_edit_tool_state'):
            active_tool = scene.mixie_edit_tool_state.active_tool

        has_selected_image = False
        if hasattr(scene, 'mixie_moodboard_images'):
            has_selected_image = any(
                img.selected and img.image for img in scene.mixie_moodboard_images
            )

        col = layout.column(align=True)
        col.enabled = has_selected_image

        col.operator(
            "mixie.moodboard_box_mask_tool",
            text="Box Mask",
            icon='SELECT_SET',
            depress=(active_tool == 'BOX_MASK'),
        )
        col.operator(
            "mixie.moodboard_magic_select_tool",
            text="Magic Select",
            icon='SNAP_FACE',
            depress=(active_tool == 'MAGIC_SELECT'),
        )

        if not has_selected_image:
            layout.separator(factor=0.3)
            layout.label(text="Select an image first", icon='INFO')


class MIXIE_PT_moodboard_toolbar(Panel):
    """Moodboard tools panel in the T-panel (left toolbar) region"""
    bl_label = ""
    bl_idname = "MIXIE_PT_moodboard_toolbar"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        """Only show in Moodboard mode."""
        if not MIXIE_SPACE_AVAILABLE:
            return False
        smixie = context.space_data
        return smixie and hasattr(smixie, 'mixie_mode') and smixie.mixie_mode == 'MOODBOARD'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        active_tool = 'NONE'
        if hasattr(scene, 'mixie_edit_tool_state'):
            active_tool = scene.mixie_edit_tool_state.active_tool

        has_selected_image = False
        if hasattr(scene, 'mixie_moodboard_images'):
            has_selected_image = any(
                img.selected and img.image
                for img in scene.mixie_moodboard_images
            )

        layout.separator(factor=0.5)

        col = layout.column(align=True)

        # ── Add Image (menu) ──────────────────────────────────────────
        row = col.row(align=True)
        row.scale_x = 1.5
        row.scale_y = 1.5
        row.menu(
            "MIXIE_MT_add_image_menu",
            text="",
            icon='FILE_FOLDER',
        )
        
        col.separator(factor=0.6)

        # ── Mask Tools (single popover) ────────────────────────────────
        # Icon reflects the currently active mask tool for instant feedback.
        mask_icon = _MASK_TOOL_ICONS.get(active_tool, _MASK_ICON_DEFAULT)
        any_mask_active = active_tool in _MASK_TOOL_ICONS

        row = col.row(align=True)
        row.scale_x = 1.5
        row.scale_y = 1.5
        row.enabled = has_selected_image
        row.popover(
            panel="MIXIE_PT_mask_tools_popover",
            text="",
            icon=mask_icon,
        )

        col.separator(factor=0.6)

        # ── Add Text ───────────────────────────────────────────────────
        row = col.row(align=True)
        row.scale_x = 1.5
        row.scale_y = 1.5
        row.operator(
            "mixie.moodboard_add_textbox",
            text="",
            icon='FONT_DATA'
        )

        # "Send to Mixie Chat" toolbar button removed — moodboard
        # selection auto-mirrors into the chat composer's attachments
        # via the polling sync in moodboard.core.chat_sync. The
        # operator and ``P`` keymap remain for muscle memory but the
        # toolbar entry was redundant and confusing.

        layout.separator(factor=0.5)


# Only include panels if MIXIE space is available
classes = (
    MIXIE_MT_add_image_menu,
    MIXIE_PT_mask_tools_popover,
    MIXIE_PT_moodboard_toolbar,
) if MIXIE_SPACE_AVAILABLE else ()
