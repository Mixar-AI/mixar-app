# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modal interaction operators owned by the native Director timeline."""

from bpy.props import FloatProperty
from bpy.types import Operator

from ...core import beat_sync
from ...core.key_drag import KeyDrag
from ...core.shot_api import active_shot


class MIXAR_OT_director_drag_strip(Operator):
    """Move every key of the camera in time, keeping their spacing"""

    bl_idname = "mixar.director_drag_strip"
    bl_label = "Move Camera Strip"
    bl_description = "Move this camera's whole animation in time"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    frames_per_pixel: FloatProperty(
        default=1.0,
        min=0.000001,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        shot = active_shot(context.scene) if state else None
        return bool(
            state
            and state.is_directing
            and shot
            and shot.state == 'DRAFT'
            and shot.camera is not None
        )

    def _redraw(self, context) -> None:
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def invoke(self, context, event):
        shot = active_shot(context.scene)
        if shot is None or shot.camera is None:
            return {'CANCELLED'}
        scene = context.scene
        # The bar spans every key the camera carries — a recorded take's
        # samples as well as its beats — so the drag moves all of them.
        drag = KeyDrag(scene, shot.camera, everything=True)
        if drag.empty:
            return {'CANCELLED'}
        self._drag = drag
        self._shot_id = shot.shot_id
        self._start_mouse_x = event.mouse_x
        self._original_current_frame = int(scene.frame_current)
        # The playhead rides along when it sits on the animation, so the
        # viewport keeps showing the pose it showed at the press.
        self._carry_playhead = (
            drag.columns[0] <= scene.frame_current <= drag.columns[-1]
        )
        beat_sync.hold(True)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        try:
            self._drag.cancel()
            context.scene.frame_set(self._original_current_frame)
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        beat_sync.hold(False)
        self._redraw(context)

    def _abort(self, context):
        self.cancel(context)
        return {'CANCELLED'}

    def modal(self, context, event):
        shot = active_shot(context.scene)
        if shot is None or shot.shot_id != self._shot_id:
            return self._abort(context)
        if event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'}:
            if event.value in {'PRESS', 'NOTHING'}:
                return self._abort(context)

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            requested = round(
                (event.mouse_x - self._start_mouse_x) * self.frames_per_pixel
            )
            try:
                applied = self._drag.apply(requested)
            except Exception as exc:
                self.report({'ERROR'}, f"Could not move camera strip: {exc}")
                return self._abort(context)
            if self._carry_playhead:
                context.scene.frame_set(self._original_current_frame + applied)
            self._redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if not self._drag.delta:
                beat_sync.hold(False)
                return {'CANCELLED'}
            try:
                self._drag.finish()
                context.view_layer.update()
            except Exception as exc:
                self.report({'ERROR'}, f"Could not move camera strip: {exc}")
                return self._abort(context)
            beat_sync.hold(False)
            self._redraw(context)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}


class MIXAR_OT_director_scrub(Operator):
    """Drag the playhead across the timeline ruler to set the current frame"""

    bl_idname = "mixar.director_scrub"
    bl_label = "Scrub Timeline"
    bl_description = "Move the playhead to pick the frame for the next keyframe"
    bl_options = {'REGISTER', 'BLOCKING'}

    frames_per_pixel: FloatProperty(
        default=1.0,
        min=0.000001,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    origin_px: FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})
    start_frame: FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})

    def _apply(self, context, event):
        scene = context.scene
        frame = self.start_frame + (event.mouse_x - self.origin_px) * self.frames_per_pixel
        frame = max(scene.frame_start, round(frame))
        if frame != scene.frame_current:
            scene.frame_set(frame)
            area = getattr(context, "area", None)
            if area is not None:
                area.tag_redraw()

    def invoke(self, context, event):
        self._original_frame = int(context.scene.frame_current)
        self._apply(context, event)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self._apply(context, event)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            context.scene.frame_set(self._original_frame)
            area = getattr(context, "area", None)
            if area is not None:
                area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


classes = (
    MIXAR_OT_director_drag_strip,
    MIXAR_OT_director_scrub,
)
