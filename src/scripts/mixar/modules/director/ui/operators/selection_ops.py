# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators over a SELECTION of timeline keyframes.

The selection itself lives in the timeline region's C++ runtime, next to the
view and the hover — it is view state, not something a .blend should carry, and
it is the same place the hit rects it refers to are stored. These operators are
handed the indices in it.

``indices`` is a comma-separated string because Blender's ``IntVectorProperty``
is fixed-size and a selection is not; ``core/selection.py`` parses it.
"""

from bpy.props import FloatProperty, StringProperty
from bpy.types import Operator

from ...core.capture import remove_beat
from ...core.frame_math import write_preview_range
from ...core.duplicate import duplicate_beats
from ...core.selection import parse_indices
from ...core.shot_api import active_shot, refresh_manifest, release_preview_range
from ...core.timeline import move_beats


def _editable_shot(context):
    shot = active_shot(context.scene)
    if shot is None or shot.state != 'DRAFT' or not shot.beats:
        return None
    return shot


class MIXAR_OT_director_drag_beats(Operator):
    """Move every selected keyframe, keeping their spacing"""

    bl_idname = "mixar.director_drag_beats"
    bl_label = "Move Keyframes"
    bl_description = "Drag the selected keyframes and their camera keys in time"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    indices: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    frames_per_pixel: FloatProperty(
        default=1.0,
        min=0.000001,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing and _editable_shot(context))

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
            if self._applied_delta:
                move_beats(
                    scene,
                    shot,
                    self._indices,
                    -self._applied_delta,
                    rebuild_manifest=False,
                )
            scene.frame_end = self._original_frame_end
            write_preview_range(
                scene, self._original_preview_start, self._original_preview_end
            )
            scene.frame_set(self._original_current_frame)
            shot.manifest_json = self._original_manifest
        except (ReferenceError, RuntimeError, ValueError):
            pass
        self._redraw(context)
        return {'CANCELLED'}

    def invoke(self, context, event):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        self._indices = [
            index for index in parse_indices(self.indices) if index < len(shot.beats)
        ]
        if not self._indices:
            return {'CANCELLED'}
        scene = context.scene
        self._shot_id = shot.shot_id
        self._start_mouse_x = event.mouse_x
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
                    actual = move_beats(
                        context.scene,
                        shot,
                        self._indices,
                        step,
                        rebuild_manifest=False,
                    )
                except Exception as exc:
                    self.report({'ERROR'}, f"Could not move keyframes: {exc}")
                    return self._restore(context)
                if actual:
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
                release_preview_range(context.scene)
                context.view_layer.update()
            except Exception as exc:
                self.report({'ERROR'}, f"Could not move keyframes: {exc}")
                return self._restore(context)
            self._redraw(context)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}


class MIXAR_OT_director_remove_beats(Operator):
    """Remove every selected keyframe"""

    bl_idname = "mixar.director_remove_beats"
    bl_label = "Remove Keyframes"
    bl_options = {'REGISTER', 'UNDO'}

    indices: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        # Highest index first: `beats.remove(i)` shifts everything after i, so
        # ascending order removes the wrong keyframes and runs off the end.
        indices = sorted(
            (index for index in parse_indices(self.indices) if index < len(shot.beats)),
            reverse=True,
        )
        if not indices:
            return {'CANCELLED'}
        removed = 0
        for index in indices:
            if remove_beat(context.scene, shot, index):
                removed += 1
        if not removed:
            return {'CANCELLED'}
        self.report({'INFO'}, f"Removed {removed} keyframe(s)")
        return {'FINISHED'}


class MIXAR_OT_director_duplicate_beats(Operator):
    """Copy the selected keyframes to the end of the shot"""

    bl_idname = "mixar.director_duplicate_beats"
    bl_label = "Duplicate Keyframes"
    bl_description = (
        "Repeat the selected camera poses after the shot's last keyframe, "
        "keeping the spacing between them"
    )
    bl_options = {'REGISTER', 'UNDO'}

    indices: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _editable_shot(context) is not None

    def execute(self, context):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        scene = context.scene
        selected = parse_indices(self.indices)
        if not selected:
            # No selection is not an error: the keyframe the director is on
            # is the one they mean, which is what the active index tracks.
            active = int(getattr(shot, "active_beat_index", -1))
            if 0 <= active < len(shot.beats):
                selected = [active]
        if not selected:
            self.report({'ERROR'}, "Select a keyframe to duplicate")
            return {'CANCELLED'}
        state = getattr(scene, "mixar_director", None)
        beat_seconds = getattr(state, "beat_seconds", 1.0) if state else 1.0
        try:
            created = duplicate_beats(scene, shot, selected, beat_seconds)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if not created:
            return {'CANCELLED'}
        self.report({'INFO'}, f"Duplicated {len(created)} keyframe(s)")
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_drag_beats,
    MIXAR_OT_director_duplicate_beats,
    MIXAR_OT_director_remove_beats,
)
