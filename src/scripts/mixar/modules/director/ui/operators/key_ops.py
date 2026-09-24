# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Cinema dock's gestures on the shot camera's own keys.

Every mark on the dock's strip is a column of the camera's native keys, and
these are what a click, a Shift+click, a box, A / Alt+A, a drag and a delete
do to it (`core/native_keys.py`, `core/key_drag.py`). The selection they
read and write is Blender's own, so the Timeline and the Dope Sheet follow
along. The native layer hit-tests the columns and hands over their frames.
"""

from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import Operator

from ...core import beat_sync
from ...core.key_drag import KeyDrag
from ...core.native_keys import (
    beat_index_at,
    column_selected,
    delete_keys,
    drop_beats_without_keys,
    has_selected_keys,
    key_columns,
    near,
    parse_frames,
    select_columns,
)
from ...core.rotation_curves import repair_rotation_continuity
from ...core.shot_api import active_shot
from ...core.viewport import enter_camera_view

_SELECT_ITEMS = (
    ('SET', "Set", "Make these keys the selection"),
    ('EXTEND', "Extend", "Add these keys to the selection"),
    ('TOGGLE', "Toggle", "Deselect these keys if selected, select them otherwise"),
    ('ALL', "All", "Select every key of the camera"),
    ('NONE', "None", "Deselect every key of the camera"),
)

#: Editors that draw keyframes and must show the new selection at once.
_KEY_EDITORS = {'VIEW_3D', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'NLA_EDITOR'}


def _camera_shot(context):
    state = getattr(context.scene, "mixar_director", None)
    if state is None or not state.is_directing:
        return None
    shot = active_shot(context.scene)
    if shot is None or shot.camera is None:
        return None
    return shot


def _redraw_key_editors(context) -> None:
    window_manager = getattr(context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        for area in getattr(window.screen, "areas", ()):
            if area.type in _KEY_EDITORS:
                area.tag_redraw()


def _view_column(context, shot, frame: float) -> None:
    """Park the playhead on a key and look through the camera, the way
    clicking a keyframe on the dock always has."""
    context.scene.frame_set(int(round(frame)))
    index = beat_index_at(shot, frame)
    if index >= 0:
        shot.active_beat_index = index
    try:
        enter_camera_view(context, shot.camera, remember=False)
    except Exception:
        pass


class MIXAR_OT_director_select_keys(Operator):
    """Select camera keys on the Cinema timeline"""

    bl_idname = "mixar.director_select_keys"
    bl_label = "Select Keyframes"
    bl_options = {'REGISTER', 'UNDO'}

    frames: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    mode: EnumProperty(items=_SELECT_ITEMS, default='SET', options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _camera_shot(context) is not None

    def execute(self, context):
        shot = _camera_shot(context)
        if shot is None:
            return {'CANCELLED'}
        select_columns(shot.camera, parse_frames(self.frames), self.mode)
        _redraw_key_editors(context)
        return {'FINISHED'}


class MIXAR_OT_director_drag_keys(Operator):
    """Click a key to select and view it; drag to move every selected key"""

    bl_idname = "mixar.director_drag_keys"
    bl_label = "Move Keyframes"
    bl_description = "Drag the selected camera keys in time"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    frame: FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})
    #: False when the selection is already what should move (Shift+D).
    use_frame: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    frames_per_pixel: FloatProperty(
        default=1.0,
        min=0.000001,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _camera_shot(context) is not None

    def invoke(self, context, event):
        shot = _camera_shot(context)
        if shot is None:
            return {'CANCELLED'}
        camera = shot.camera
        # The Dope Sheet's click rule: a press on an unselected key makes it
        # THE selection; a press on a selected one keeps the selection for
        # the drag and narrows it to that key only if the press never moves.
        self._narrow_on_click = False
        if self.use_frame:
            if column_selected(camera, self.frame):
                self._narrow_on_click = True
            else:
                select_columns(camera, [self.frame], 'SET')
            _view_column(context, shot, self.frame)
        _redraw_key_editors(context)
        if shot.state != 'DRAFT':
            # A locked take is view-only: select and look, never move.
            return {'FINISHED'}
        self._drag = KeyDrag(context.scene, camera)
        if self._drag.empty:
            return {'FINISHED'}
        self._shot_id = shot.shot_id
        self._start_mouse_x = event.mouse_x
        beat_sync.hold(True)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _release(self, context) -> None:
        beat_sync.hold(False)
        _redraw_key_editors(context)

    def cancel(self, context):
        # Teardown paths (File > New, a window closing) end the modal here.
        try:
            self._drag.cancel()
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        self._release(context)

    def _abort(self, context):
        self.cancel(context)
        return {'CANCELLED'}

    def modal(self, context, event):
        shot = active_shot(context.scene)
        if shot is None or shot.shot_id != self._shot_id:
            return self._abort(context)
        if event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'}:
            if event.value in {'PRESS', 'NOTHING'}:
                if self.use_frame:
                    context.scene.frame_set(int(round(self.frame)))
                return self._abort(context)

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            requested = round(
                (event.mouse_x - self._start_mouse_x) * self.frames_per_pixel
            )
            try:
                applied = self._drag.apply(requested)
            except Exception as exc:
                self.report({'ERROR'}, f"Could not move keyframes: {exc}")
                return self._abort(context)
            if self.use_frame:
                # The playhead rides the grabbed key, so the viewport shows
                # the pose being retimed.
                context.scene.frame_set(int(round(self.frame + applied)))
            _redraw_key_editors(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if not self._drag.delta:
                if self._narrow_on_click:
                    select_columns(shot.camera, [self.frame], 'SET')
                self._release(context)
                return {'FINISHED'}
            try:
                self._drag.finish()
                context.view_layer.update()
            except Exception as exc:
                self.report({'ERROR'}, f"Could not move keyframes: {exc}")
                return self._abort(context)
            self._release(context)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}


class MIXAR_OT_director_delete_keys(Operator):
    """Delete the selected camera keys"""

    bl_idname = "mixar.director_delete_keys"
    bl_label = "Delete Keyframes"
    bl_description = (
        "Delete the selected camera keys; with none selected, the key under "
        "the pointer or the playhead"
    )
    bl_options = {'REGISTER', 'UNDO'}

    frame: FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})
    use_frame: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        shot = _camera_shot(context)
        return shot is not None and shot.state == 'DRAFT'

    def execute(self, context):
        shot = _camera_shot(context)
        if shot is None or shot.state != 'DRAFT':
            return {'CANCELLED'}
        camera = shot.camera
        frames = None
        if not has_selected_keys(camera):
            target = self.frame if self.use_frame else float(context.scene.frame_current)
            if not near(key_columns(camera), target):
                return {'CANCELLED'}
            frames = [target]
        beat_sync.hold(True)
        try:
            deleted = delete_keys(camera, frames)
            drop_beats_without_keys(context.scene, camera)
            repair_rotation_continuity(camera)
        finally:
            beat_sync.hold(False)
        if not deleted:
            return {'CANCELLED'}
        _redraw_key_editors(context)
        self.report({'INFO'}, f"Deleted keys on {len(deleted)} frame(s)")
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_select_keys,
    MIXAR_OT_director_drag_keys,
    MIXAR_OT_director_delete_keys,
)
