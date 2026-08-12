# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modal interaction operators owned by the native Director timeline."""

from bpy.props import FloatProperty, IntProperty
from bpy.types import Operator

from ...core.frame_math import clamp_frame_delta
from ...core.shot_api import active_shot, refresh_manifest, scope_preview_range
from ...core.timeline import move_single_beat, shift_camera_beats
from ...core.viewport import enter_camera_view


class MIXAR_OT_director_drag_strip(Operator):
    """Move the complete keyframe strip without changing keyframe spacing"""

    bl_idname = "mixar.director_drag_strip"
    bl_label = "Move Camera Strip"
    bl_description = "Move this shot and all of its native camera keys in time"
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
            and shot.beats
        )

    def _redraw(self, context) -> None:
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def _restore_original(self, context):
        scene = context.scene
        # Re-resolve rather than reusing the reference taken in invoke(): a
        # shot added or removed mid-drag reallocates the shots collection.
        shot = active_shot(scene)
        if shot is None or shot.shot_id != self._shot_id:
            self._redraw(context)
            return {'CANCELLED'}
        try:
            if self._applied_delta:
                shift_camera_beats(
                    scene,
                    shot,
                    -self._applied_delta,
                    rebuild_manifest=False,
                )
            scene.frame_end = self._original_frame_end
            scene.frame_preview_start = self._original_preview_start
            scene.frame_preview_end = self._original_preview_end
            scene.frame_set(self._original_current_frame)
            shot.manifest_json = self._original_manifest
        except (ReferenceError, RuntimeError, ValueError):
            pass
        self._redraw(context)
        return {'CANCELLED'}

    def invoke(self, context, event):
        shot = active_shot(context.scene)
        if shot is None or not shot.beats:
            return {'CANCELLED'}
        scene = context.scene
        self._shot_id = shot.shot_id
        self._start_mouse_x = event.mouse_x
        self._original_frames = tuple(int(beat.frame) for beat in shot.beats)
        self._original_current_frame = int(scene.frame_current)
        self._original_frame_end = int(scene.frame_end)
        self._original_preview_start = int(scene.frame_preview_start)
        self._original_preview_end = int(scene.frame_preview_end)
        self._original_manifest = shot.manifest_json
        self._applied_delta = 0
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        shot = active_shot(context.scene)
        if shot is None or shot.shot_id != self._shot_id:
            return self._restore_original(context)
        if event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'}:
            if event.value in {'PRESS', 'NOTHING'}:
                return self._restore_original(context)

        if event.type == 'MOUSEMOVE':
            requested = round(
                (event.mouse_x - self._start_mouse_x) * self.frames_per_pixel
            )
            requested = clamp_frame_delta(
                self._original_frames,
                requested,
                minimum_frame=context.scene.frame_start,
            )
            step = requested - self._applied_delta
            if step:
                try:
                    actual = shift_camera_beats(
                        context.scene,
                        shot,
                        step,
                        rebuild_manifest=False,
                    )
                except Exception as exc:
                    self.report({'ERROR'}, f"Could not move camera strip: {exc}")
                    return self._restore_original(context)
                self._applied_delta += actual
                self._redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if not self._applied_delta:
                return {'CANCELLED'}
            try:
                context.scene.frame_end = max(
                    self._original_frame_end,
                    max(int(beat.frame) for beat in shot.beats),
                )
                refresh_manifest(context.scene, shot)
                context.view_layer.update()
            except Exception as exc:
                self.report({'ERROR'}, f"Could not move camera strip: {exc}")
                return self._restore_original(context)
            self._redraw(context)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}


class MIXAR_OT_director_drag_beat(Operator):
    """Move a single keyframe along the timeline with its camera keys"""

    bl_idname = "mixar.director_drag_beat"
    bl_label = "Move Keyframe"
    bl_description = "Drag this keyframe and its native camera keys in time"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    index: IntProperty(default=-1, min=0, options={'HIDDEN', 'SKIP_SAVE'})
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
            and shot.beats
        )

    def _redraw(self, context) -> None:
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def _restore(self, context):
        scene = context.scene
        # Re-resolve rather than reusing the invoke() reference: a shot added
        # or removed mid-drag reallocates the shots collection.
        shot = active_shot(scene)
        if shot is None or shot.shot_id != self._shot_id:
            self._redraw(context)
            return {'CANCELLED'}
        try:
            if self._applied_delta and self.index < len(shot.beats):
                move_single_beat(
                    scene,
                    shot,
                    self.index,
                    -self._applied_delta,
                    rebuild_manifest=False,
                )
            scene.frame_end = self._original_frame_end
            scene.frame_preview_start = self._original_preview_start
            scene.frame_preview_end = self._original_preview_end
            scene.frame_set(self._original_current_frame)
            shot.manifest_json = self._original_manifest
        except (ReferenceError, RuntimeError, ValueError):
            pass
        self._redraw(context)
        return {'CANCELLED'}

    def invoke(self, context, event):
        shot = active_shot(context.scene)
        if shot is None or self.index < 0 or self.index >= len(shot.beats):
            return {'CANCELLED'}
        scene = context.scene
        beat = shot.beats[self.index]
        self._shot_id = shot.shot_id
        self._start_mouse_x = event.mouse_x
        self._original_frame = int(beat.frame)
        self._original_current_frame = int(scene.frame_current)
        self._original_frame_end = int(scene.frame_end)
        self._original_preview_start = int(scene.frame_preview_start)
        self._original_preview_end = int(scene.frame_preview_end)
        self._original_manifest = shot.manifest_json
        self._applied_delta = 0
        # A press that never moves is a plain "view this keyframe" click, so
        # jump the playhead into camera view up front (matches jump_beat).
        shot.active_beat_index = self.index
        scene.frame_set(self._original_frame)
        try:
            enter_camera_view(context, shot.camera, remember=False)
        except Exception:
            pass
        self._redraw(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        shot = active_shot(context.scene)
        if (
            shot is None
            or shot.shot_id != self._shot_id
            or self.index >= len(shot.beats)
        ):
            return self._restore(context)
        if event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'}:
            if event.value in {'PRESS', 'NOTHING'}:
                return self._restore(context)

        if event.type == 'MOUSEMOVE':
            requested = round(
                (event.mouse_x - self._start_mouse_x) * self.frames_per_pixel
            )
            step = requested - self._applied_delta
            if step:
                try:
                    actual = move_single_beat(
                        context.scene,
                        shot,
                        self.index,
                        step,
                        rebuild_manifest=False,
                    )
                except Exception as exc:
                    self.report({'ERROR'}, f"Could not move keyframe: {exc}")
                    return self._restore(context)
                if actual:
                    self._applied_delta += actual
                    # The playhead follows the keyframe as it slides.
                    context.scene.frame_set(int(shot.beats[self.index].frame))
                    self._redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if not self._applied_delta:
                # Pure click: keep the jump performed in invoke().
                return {'FINISHED'}
            try:
                context.scene.frame_end = max(
                    self._original_frame_end,
                    max(int(beat.frame) for beat in shot.beats),
                )
                refresh_manifest(context.scene, shot)
                scope_preview_range(context.scene, shot)
                context.view_layer.update()
            except Exception as exc:
                self.report({'ERROR'}, f"Could not move keyframe: {exc}")
                return self._restore(context)
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
    MIXAR_OT_director_drag_beat,
    MIXAR_OT_director_scrub,
)
