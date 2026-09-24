# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Canvas annotation mode; each pointer gesture is its own native undo step."""

import math

from bpy.types import Operator

from ...constants import ANNOTATION_MAX_POINTS_PER_STROKE, CANVAS_ANNOTATION_SAMPLE_PX
from ...core.annotation_erase import erase_hits, restore_strokes, snapshot_strokes
from ...core.canvas_context import is_moodboard_context, redraw_moodboard_canvases
from ...core.canvas_mark_mode import set_canvas_mark_mode


def _available(context):
    return is_moodboard_context(context) and hasattr(context.scene, "mixie_moodboard_annotations")


def _erasing(context):
    return bool(getattr(context.window_manager, "mixie_moodboard_erasing", False))


def _canvas_xy(region, event):
    return region.view2d.region_to_view(event.mouse_x - region.x, event.mouse_y - region.y)


def _canvas_unit(region):
    view = region.view2d
    return abs(view.region_to_view(1, 0)[0] - view.region_to_view(0, 0)[0])


class MIXIE_OT_moodboard_annotate_canvas(Operator):
    bl_idname = "mixie.moodboard_annotate_canvas"
    bl_label = "Annotate"
    bl_description = "Draw on the moodboard; strokes are saved in the project. Esc exits"

    @classmethod
    def poll(cls, context):
        return _available(context)

    def execute(self, context):
        set_canvas_mark_mode(
            context,
            annotating=not context.window_manager.mixie_moodboard_annotating,
            erasing=False,
        )
        return {"FINISHED"}


class MIXIE_OT_moodboard_erase_canvas(Operator):
    bl_idname = "mixie.moodboard_erase_canvas"
    bl_label = "Erase"
    bl_description = "Erase annotation strokes on the moodboard. Esc exits"

    @classmethod
    def poll(cls, context):
        return _available(context)

    def execute(self, context):
        set_canvas_mark_mode(context, annotating=False, erasing=not _erasing(context))
        return {"FINISHED"}


class MIXIE_OT_moodboard_annotation_exit(Operator):
    bl_idname = "mixie.moodboard_annotation_exit"
    bl_label = "Exit Annotate"

    @classmethod
    def poll(cls, context):
        return _available(context) and (
            context.window_manager.mixie_moodboard_annotating or _erasing(context)
        )

    def execute(self, context):
        set_canvas_mark_mode(context, annotating=False, erasing=False)
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
        coords = _canvas_xy(region, event)
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
        unit = _canvas_unit(self._region)
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


class MIXIE_OT_moodboard_annotation_erase(Operator):
    bl_idname = "mixie.moodboard_annotation_erase"
    bl_label = "Moodboard Annotation Erase"
    bl_options = {"UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return (
            _available(context)
            and context.region.type in {"WINDOW", "TOOL_PROPS"}
            and _erasing(context)
            and bool(context.scene.mixie_moodboard_annotations)
        )

    def _radius(self, context):
        state = self._scene.mixie_edit_tool_state
        return state.annotation_width * context.preferences.system.ui_scale * self._unit

    def _erase_at(self, context, event):
        x, y = _canvas_xy(self._region, event)
        if erase_hits(self._scene.mixie_moodboard_annotations, x, y, self._radius(context)):
            self._changed = True
            redraw_moodboard_canvases()

    def invoke(self, context, event):
        self._region = context.region
        self._scene = context.scene
        self._unit = _canvas_unit(self._region)
        self._snapshot = snapshot_strokes(self._scene.mixie_moodboard_annotations)
        self._changed = False
        self._erase_at(context, event)
        context.window.cursor_modal_set("ERASER")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "WINDOW_DEACTIVATE" or (
            event.value == "PRESS" and event.type in {"ESC", "RIGHTMOUSE"}
        ):
            self.cancel(context)
            return {"CANCELLED"}
        if event.type == "MOUSEMOVE":
            self._erase_at(context, event)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            context.window.cursor_modal_restore()
            redraw_moodboard_canvases()
            return {"FINISHED"} if self._changed else {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        restore_strokes(self._scene.mixie_moodboard_annotations, self._snapshot)
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
    MIXIE_OT_moodboard_annotate_canvas, MIXIE_OT_moodboard_erase_canvas,
    MIXIE_OT_moodboard_annotation_exit, MIXIE_OT_moodboard_annotation_stroke,
    MIXIE_OT_moodboard_annotation_erase, MIXIE_OT_moodboard_annotation_undo,
    MIXIE_OT_moodboard_annotations_clear,
)
