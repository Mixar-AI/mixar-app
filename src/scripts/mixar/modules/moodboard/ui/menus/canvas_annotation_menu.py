# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Settings and history for project-owned moodboard marks."""

from bpy.types import Menu


class MIXIE_MT_canvas_annotations(Menu):
    bl_idname = "MIXIE_MT_canvas_annotations"
    bl_label = "Annotations"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = "INVOKE_DEFAULT"
        layout.operator("mixie.moodboard_annotate_canvas", text=(
            "Exit Annotate" if context.window_manager.mixie_moodboard_annotating else "Annotate"
        ), icon="GREASEPENCIL")
        layout.operator("mixie.moodboard_erase_canvas", text=(
            "Exit Erase" if getattr(context.window_manager, "mixie_moodboard_erasing", False)
            else "Erase"
        ), icon="ERASER")
        state = context.scene.mixie_edit_tool_state
        layout.prop(state, "annotation_color", text="Color")
        layout.prop(state, "annotation_width", text="Width")
        layout.prop(context.scene, "mixie_moodboard_show_annotations")
        layout.separator()
        layout.operator("mixie.moodboard_annotation_undo", text="Undo Last Stroke", icon="LOOP_BACK")
        layout.operator("mixie.moodboard_annotations_clear", text="Clear Annotations", icon="TRASH")


classes = (MIXIE_MT_canvas_annotations,)
