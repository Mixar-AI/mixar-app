# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared canvas tools and their native media/mask/annotation menus."""

import bpy
from bpy.types import Menu, Panel


from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE


def draw_moodboard_add_tools(layout, context):
    """One neutral, token-styled rail in both canvas hosts."""
    surface = layout.mixar_surface(theme="ZEN", density="COMPACT")
    surface.operator_context = "INVOKE_DEFAULT"
    col = surface.column()
    col.scale_x = 1.6
    col.scale_y = 1.6

    def action(op, icon, **kwargs):
        row = col.row()
        row.operator(op, text="", icon=icon, **kwargs)
        row.mixar_style(component="ACTION", variant="SECONDARY")

    row = col.row()
    row.menu("MIXIE_MT_add_image_menu", text="", icon="FILE_FOLDER")
    row.mixar_style(component="ACTION", variant="SECONDARY")
    action("mixie.moodboard_add_textbox", "FONT_DATA")
    action("mixie.moodboard_annotate_canvas", "GREASEPENCIL",
           depress=context.window_manager.mixie_moodboard_annotating)
    erasing = bool(getattr(context.window_manager, "mixie_moodboard_erasing", False))
    if erasing or getattr(context.scene, "mixie_moodboard_annotations", None):
        action("mixie.moodboard_erase_canvas", "X", depress=erasing)
    row = col.row()
    row.enabled = any(item.selected and item.image and item.image.source != 'MOVIE'
                      for item in context.scene.mixie_moodboard_images)
    row.popover(panel="MIXIE_PT_mask_tools_popover", text="", icon="MOD_MASK")
    row.mixar_style(component="ACTION", variant="SECONDARY")
    if row.enabled:
        row = col.row()
        row.popover(panel="MIXIE_PT_annotation_tools_popover", text="", icon="BRUSH_DATA")
        row.mixar_style(component="ACTION", variant="SECONDARY")
    row = col.row()
    row.menu("MIXIE_MT_canvas_board", text="", icon="DOWNARROW_HLT")
    row.mixar_style(component="ACTION", variant="SECONDARY")


# A Menu (not a popover) so it auto-dismisses the instant an option is
# picked. Both add operators return RUNNING_MODAL from invoke() (a file
# browser / a search popup), and a popover lingers behind those modals
# instead of closing — a menu closes on item-click, before invoke runs.
# NOTE: kept as a comment, not a docstring — a Menu's docstring is shown
# as the button tooltip, and this rationale isn't meant for users.
class MIXIE_MT_add_image_menu(Menu):
    """Add media or selected scene meshes"""

    bl_idname = "MIXIE_MT_add_image_menu"
    bl_label = "Add References"

    def draw(self, context):
        layout = self.layout.mixar_surface(theme="ZEN", density="COMPACT")
        # INVOKE_DEFAULT so each operator's invoke() runs (opening its
        # file browser / search popup) rather than executing headless.
        layout.operator_context = "INVOKE_DEFAULT"
        layout.operator(
            "mixie.moodboard_add_image",
            text="Open Image or Video",
            icon='FILE_FOLDER',
        )
        layout.operator(
            "mixie.moodboard_add_existing_image",
            text="Add Existing Media",
            icon='IMAGE_DATA',
        )
        layout.separator()
        layout.operator("mixie.add_selected_mesh_to_moodboard",
                        text="Add Selected Meshes", icon='OUTLINER_OB_MESH')


class MIXIE_PT_mask_tools_popover(Panel):
    """
    Popover panel with all mask selection tools.
    Opened by clicking the single Mask Tools button in the toolbar.
    """

    bl_idname = "MIXIE_PT_mask_tools_popover"
    bl_label = "Mask Tools"
    bl_space_type = "MIXIE" if MIXIE_SPACE_AVAILABLE else "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 9
    bl_options = {"INSTANCED"}

    def draw(self, context):
        layout = self.layout.mixar_surface(theme="ZEN", density="COMPACT")
        scene = context.scene

        active_tool = "NONE"
        if hasattr(scene, "mixie_edit_tool_state"):
            active_tool = scene.mixie_edit_tool_state.active_tool

        has_selected_image = False
        if hasattr(scene, "mixie_moodboard_images"):
            has_selected_image = any(
                img.selected and img.image and img.image.source != 'MOVIE'
                for img in scene.mixie_moodboard_images
            )

        col = layout.column(align=True)
        col.enabled = has_selected_image

        col.operator(
            "mixie.moodboard_box_mask_tool",
            text="Box Mask",
            icon="SELECT_SET",
            depress=(active_tool == "BOX_MASK"),
        )
        col.operator(
            "mixie.moodboard_lasso_tool",
            text="Multi-Lasso Mask",
            icon="OUTLINER_DATA_GP_LAYER",
            depress=(active_tool == "LASSO"),
        )
        if active_tool == "LASSO":
            hint = col.column()
            hint.scale_y = 0.8
            hint.label(text="Draw loops, release, repeat", icon="INFO")
            hint.label(text="Press Enter to finish", icon="EVENT_RETURN")
        col.operator(
            "mixie.moodboard_magic_select_tool",
            text="Magic Select",
            icon="SNAP_FACE",
            depress=(active_tool == "MAGIC_SELECT"),
        )

        if not has_selected_image:
            layout.separator(factor=0.3)
            layout.label(text="Select an image first", icon="INFO")


class MIXIE_PT_annotation_tools_popover(Panel):
    """Freehand annotation settings and actions for one selected image."""

    bl_idname = "MIXIE_PT_annotation_tools_popover"
    bl_label = "Annotate"
    bl_space_type = "MIXIE" if MIXIE_SPACE_AVAILABLE else "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 10
    bl_options = {"INSTANCED"}

    def draw(self, context):
        layout = self.layout.mixar_surface(theme="ZEN", density="COMPACT")
        scene = context.scene
        state = scene.mixie_edit_tool_state
        selected = [
            item
            for item in scene.mixie_moodboard_images
            if item.selected and item.image
        ]
        image_item = selected[0] if len(selected) == 1 else None

        col = layout.column(align=True)
        col.enabled = image_item is not None
        col.operator(
            "mixie.moodboard_annotate_tool",
            text="Draw Stroke",
            icon="BRUSH_DATA",
            depress=(state.active_tool == "ANNOTATE"),
        )
        col.separator(factor=0.4)
        col.prop(state, "annotation_color", text="Color")
        col.prop(state, "annotation_width", text="Width", slider=True)

        if image_item is not None:
            col.separator(factor=0.4)
            col.prop(image_item, "show_annotations", text="Show Annotations")
            row = col.row(align=True)
            row.enabled = bool(image_item.annotations)
            row.operator(
                "mixie.moodboard_undo_annotation",
                text="Undo Last",
                icon="LOOP_BACK",
            )
            row.operator(
                "mixie.moodboard_clear_annotations",
                text="Clear",
                icon="TRASH",
            )
            col.label(
                text=f"{len(image_item.annotations)} stroke(s)",
                icon="INFO",
            )
        else:
            layout.separator(factor=0.3)
            layout.label(text="Select exactly one image", icon="INFO")

        if state.active_tool == "ANNOTATE":
            layout.separator(factor=0.3)
            layout.label(text="Drag once; release to finish", icon="MOUSE_LMB")
            layout.label(text="Esc cancels the active stroke", icon="EVENT_ESC")


classes = (
    MIXIE_MT_add_image_menu,
    MIXIE_PT_mask_tools_popover,
    MIXIE_PT_annotation_tools_popover,
) if MIXIE_SPACE_AVAILABLE else ()
