# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Canvas annotation mode; each pointer gesture is its own native undo step."""

import math

from bpy.types import Operator

from ...constants import ANNOTATION_MAX_POINTS_PER_STROKE, CANVAS_ANNOTATION_SAMPLE_PX
from ...core.canvas_context import is_moodboard_context, redraw_moodboard_canvases


def _available(context):
    return is_moodboard_context(context) and hasattr(context.scene, "mixie_moodboard_annotations")


class MIXIE_OT_moodboard_annotate_canvas(Operator):
    bl_idname = "mixie.moodboard_annotate_canvas"
    bl_label = "Annotate"
    bl_description = "Draw on the moodboard; strokes are saved in the project. Esc exits"

    @classmethod
    def poll(cls, context):
        return _available(context)

    def execute(self, context):
        wm = context.window_manager
        wm.mixie_moodboard_annotating = not wm.mixie_moodboard_annotating
        if wm.mixie_moodboard_annotating:
            context.scene.mixie_moodboard_show_annotations = True
        redraw_moodboard_canvases()
        return {"FINISHED"}


class MIXIE_OT_moodboard_annotation_exit(Operator):
    bl_idname = "mixie.moodboard_annotation_exit"
    bl_label = "Exit Annotate"

    @classmethod
    def poll(cls, context):
        return _available(context) and context.window_manager.mixie_moodboard_annotating

    def execute(self, context):
        context.window_manager.mixie_moodboard_annotating = False
        redraw_moodboard_canvases()
        return {"FINISHED"}


class MIXIE_OT_moodboard_annotation_stroke(Operator):
    bl_idname = "mixie.moodboard_annotation_stroke"
    bl_label = "Moodboard Annotation Stroke"
    bl_options = {"UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return (
            _available(context)
            and context.region.type in {"WINDOW", "TOOL_PROPS"}
            and context.window_manager.mixie_moodboard_annotating
        )

    def _append(self, event, *, force=False):
        region = self._region
        coords = region.view2d.region_to_view(event.mouse_x - region.x, event.mouse_y - region.y)
        points = self._stroke.points
        if len(points) >= ANNOTATION_MAX_POINTS_PER_STROKE:
            return
        if points:
            last = points[-1]
            distance = math.hypot(coords[0] - last.x, coords[1] - last.y)
            if distance == 0 or (not force and distance < self._sample_distance):
                return
        point = points.add()
        point.x, point.y = coords
        redraw_moodboard_canvases()

    def invoke(self, context, event):
        # The native canvas keymap's hit-test already excludes the drawer grip
        # and overlapping UI. Window coordinates also work when released outside.
        self._region = context.region
        self._scene = context.scene
        self._index = len(self._scene.mixie_moodboard_annotations)
        self._stroke = self._scene.mixie_moodboard_annotations.add()
        self._scene.mixie_moodboard_show_annotations = True
        state = self._scene.mixie_edit_tool_state
        self._stroke.color = state.annotation_color[:]
        view = self._region.view2d
        unit = abs(view.region_to_view(1, 0)[0] - view.region_to_view(0, 0)[0])
        self._stroke.width = state.annotation_width * context.preferences.system.ui_scale * unit
        self._sample_distance = CANVAS_ANNOTATION_SAMPLE_PX * unit
        self._append(event, force=True)
        context.window.cursor_modal_set("CROSSHAIR")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "WINDOW_DEACTIVATE" or (
            event.value == "PRESS" and event.type in {"ESC", "RIGHTMOUSE"}
        ):
            self.cancel(context)
            return {"CANCELLED"}
        if event.type == "MOUSEMOVE":
            self._append(event)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self._append(event, force=True)
            context.window.cursor_modal_restore()
            redraw_moodboard_canvases()
            return {"FINISHED"}
        # A stroke consumes navigation and history keys until release/cancel.
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        self._scene.mixie_moodboard_annotations.remove(self._index)
        context.window.cursor_modal_restore()
        redraw_moodboard_canvases()


class MIXIE_OT_moodboard_annotation_undo(Operator):
    bl_idname = "mixie.moodboard_annotation_undo"
    bl_label = "Undo Last Moodboard Stroke"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return _available(context) and bool(context.scene.mixie_moodboard_annotations)

    def execute(self, context):
        strokes = context.scene.mixie_moodboard_annotations
        strokes.remove(len(strokes) - 1)
        redraw_moodboard_canvases()
        return {"FINISHED"}


class MIXIE_OT_moodboard_annotations_clear(Operator):
    bl_idname = "mixie.moodboard_annotations_clear"
    bl_label = "Clear Moodboard Annotations"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return _available(context) and bool(context.scene.mixie_moodboard_annotations)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        context.scene.mixie_moodboard_annotations.clear()
        redraw_moodboard_canvases()
        return {"FINISHED"}


classes = (
    MIXIE_OT_moodboard_annotate_canvas, MIXIE_OT_moodboard_annotation_exit,
    MIXIE_OT_moodboard_annotation_stroke, MIXIE_OT_moodboard_annotation_undo,
    MIXIE_OT_moodboard_annotations_clear,
)
