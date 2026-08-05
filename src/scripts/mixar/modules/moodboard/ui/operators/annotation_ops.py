# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Freehand annotation operators for moodboard reference images."""

import math

import bpy
from bpy.types import Operator

from mixar.modules.moodboard.constants import (
    ANNOTATION_MAX_POINTS_PER_STROKE,
    ANNOTATION_MIN_DISTANCE,
)
from mixar.modules.moodboard.core.moodboard_utils import mouse_to_image_coords


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


def _remove_active_stroke(scene, state):
    index = state.annotation_active_stroke_index
    if state.target_image_index < 0:
        return False
    if state.target_image_index >= len(scene.mixie_moodboard_images):
        return False
    strokes = scene.mixie_moodboard_images[state.target_image_index].annotations
    if index < 0 or index >= len(strokes):
        return False
    strokes.remove(index)
    state.annotation_active_stroke_index = -1
    state.is_drawing = False
    return True


def _finish_session(context, *, cancel_active=False):
    state = context.scene.mixie_edit_tool_state
    if cancel_active:
        _remove_active_stroke(context.scene, state)
    state.active_tool = "NONE"
    state.target_image_index = -1
    state.annotation_active_stroke_index = -1
    state.is_drawing = False
    context.window.cursor_modal_restore()
    _tag_redraw(context)


class MIXIE_OT_moodboard_annotate_tool(Operator):
    """Draw multiple freehand annotation strokes on one reference image."""

    bl_idname = "mixie.moodboard_annotate_tool"
    bl_label = "Draw Annotations"
    bl_description = "Draw on the selected image; Enter or Esc finishes"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        return (
            hasattr(scene, "mixie_moodboard_images")
            and hasattr(scene, "mixie_edit_tool_state")
            and _selected_image_index(scene) >= 0
        )

    def invoke(self, context, event):
        scene = context.scene
        state = scene.mixie_edit_tool_state
        target_index = _selected_image_index(scene)
        if target_index < 0:
            self.report({"WARNING"}, "Select exactly one image to annotate")
            return {"CANCELLED"}

        state.active_tool = "ANNOTATE"
        state.target_image_index = target_index
        state.annotation_active_stroke_index = -1
        state.is_drawing = False
        scene.mixie_moodboard_images[target_index].show_annotations = True

        context.window.cursor_modal_set("CROSSHAIR")
        context.window_manager.modal_handler_add(self)
        _tag_redraw(context)
        self.report(
            {"INFO"},
            "Draw strokes on the image. Cmd/Ctrl+Z undoes; Enter or Esc finishes.",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        scene = context.scene
        state = scene.mixie_edit_tool_state
        target_index = state.target_image_index

        if target_index < 0 or target_index >= len(scene.mixie_moodboard_images):
            _finish_session(context, cancel_active=True)
            return {"CANCELLED"}

        image_item = scene.mixie_moodboard_images[target_index]

        if event.value == "PRESS" and event.type in {"RET", "NUMPAD_ENTER"}:
            _finish_session(context)
            return {"FINISHED"}

        if event.value == "PRESS" and event.type in {"ESC", "RIGHTMOUSE"}:
            _finish_session(context, cancel_active=state.is_drawing)
            return {"FINISHED"}

        if event.type == "Z" and event.value == "PRESS" and (event.ctrl or event.oskey):
            if not _remove_active_stroke(scene, state) and image_item.annotations:
                image_item.annotations.remove(len(image_item.annotations) - 1)
            _tag_redraw(context)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            coords = mouse_to_image_coords(context, event, target_index)
            if coords is None:
                return {"RUNNING_MODAL"}

            stroke = image_item.annotations.add()
            stroke.color = state.annotation_color[:]
            stroke.width = state.annotation_width
            point = stroke.points.add()
            point.x, point.y = coords
            state.annotation_active_stroke_index = len(image_item.annotations) - 1
            state.is_drawing = True
            _tag_redraw(context)
            return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE" and state.is_drawing:
            index = state.annotation_active_stroke_index
            if index < 0 or index >= len(image_item.annotations):
                return {"RUNNING_MODAL"}
            stroke = image_item.annotations[index]
            if len(stroke.points) >= ANNOTATION_MAX_POINTS_PER_STROKE:
                return {"RUNNING_MODAL"}

            coords = mouse_to_image_coords(context, event, target_index)
            if coords is None:
                return {"RUNNING_MODAL"}
            last = stroke.points[-1]
            if (
                math.hypot(coords[0] - last.x, coords[1] - last.y)
                < ANNOTATION_MIN_DISTANCE
            ):
                return {"RUNNING_MODAL"}

            point = stroke.points.add()
            point.x, point.y = coords
            _tag_redraw(context)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            state.annotation_active_stroke_index = -1
            state.is_drawing = False
            _tag_redraw(context)
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}


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
    MIXIE_OT_moodboard_annotate_tool,
    MIXIE_OT_moodboard_undo_annotation,
    MIXIE_OT_moodboard_clear_annotations,
)
