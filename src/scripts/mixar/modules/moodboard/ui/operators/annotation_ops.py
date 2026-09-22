# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cleanup operators for image-attached annotations saved by older projects."""

from bpy.types import Operator

def _selected_image_index(scene):
    selected = [
        index
        for index, item in enumerate(scene.mixie_moodboard_images)
        if item.selected and item.image
    ]
    return selected[0] if len(selected) == 1 else -1


def _tag_redraw(context):
    if context.area:
        context.area.tag_redraw()


class MIXIE_OT_moodboard_undo_annotation(Operator):
    """Remove the most recent annotation stroke from the selected image."""

    bl_idname = "mixie.moodboard_undo_annotation"
    bl_label = "Undo Last Stroke"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        index = _selected_image_index(context.scene)
        return index >= 0 and bool(
            context.scene.mixie_moodboard_images[index].annotations
        )

    def execute(self, context):
        index = _selected_image_index(context.scene)
        strokes = context.scene.mixie_moodboard_images[index].annotations
        strokes.remove(len(strokes) - 1)
        _tag_redraw(context)
        return {"FINISHED"}


class MIXIE_OT_moodboard_clear_annotations(Operator):
    """Remove every annotation stroke from the selected image."""

    bl_idname = "mixie.moodboard_clear_annotations"
    bl_label = "Clear Annotations"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        index = _selected_image_index(context.scene)
        return index >= 0 and bool(
            context.scene.mixie_moodboard_images[index].annotations
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        index = _selected_image_index(context.scene)
        context.scene.mixie_moodboard_images[index].annotations.clear()
        _tag_redraw(context)
        return {"FINISHED"}


classes = (
    MIXIE_OT_moodboard_undo_annotation,
    MIXIE_OT_moodboard_clear_annotations,
)
