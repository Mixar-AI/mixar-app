# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Create, enter, finish, and lock camera-directing shots."""

import bpy
from bpy.types import Operator

from ...core.shot_api import (
    active_shot,
    create_new_take,
    create_shot,
    lock_shot,
    remove_shot,
)
from ...core.viewport import (
    create_camera_from_view,
    enter_camera_view,
    enter_director_surface,
    restore_view,
)


def _camera_for_start(context, shot):
    if shot is not None and shot.camera is not None:
        return shot.camera
    camera = context.scene.camera
    if camera is not None and camera.type == 'CAMERA':
        return camera
    return create_camera_from_view(context)


def _leave_immersive(context, state) -> None:
    screen = getattr(context, "screen", None)
    if not bool(screen and screen.show_fullscreen):
        state.is_immersive = False
        return
    try:
        bpy.ops.screen.screen_full_area(use_hide_panels=True)
    except Exception:
        pass
    state.is_immersive = False


class MIXAR_OT_director_enter(Operator):
    """Open Director as a clean, mode-level viewport experience"""

    bl_idname = "mixar.director_enter"
    bl_label = "Director"
    bl_description = "Open the cinematic camera-directing workspace"
    bl_options = {'REGISTER'}

    def execute(self, context):
        state = getattr(context.scene, "mixar_director", None)
        if state is None:
            return {'CANCELLED'}
        try:
            enter_director_surface(context)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        state.is_directing = True
        state.timeline_expanded = True
        state.navigation_mode = 'NAVIGATE'
        return {'FINISHED'}


class MIXAR_OT_director_start(Operator):
    """Enter a clean camera view for the selected draft shot"""

    bl_idname = "mixar.director_start"
    bl_label = "Start Directing"
    bl_description = "Direct the active scene camera from the viewport"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        state = scene.mixar_director
        try:
            enter_director_surface(context)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        shot = active_shot(scene)
        if shot is not None and shot.state == 'LOCKED':
            shot = create_new_take(scene, shot)
        camera = _camera_for_start(context, shot)
        if shot is None:
            shot = create_shot(scene, camera)
        elif shot.camera is None:
            shot.camera = camera
        try:
            enter_camera_view(context, shot.camera)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        state.is_directing = True
        state.timeline_expanded = True
        state.navigation_mode = 'NAVIGATE'
        self.report({'INFO'}, f"Directing {shot.name}, take {shot.version}")
        return {'FINISHED'}


class MIXAR_OT_director_new_shot(Operator):
    """Create a new shot camera from the current view"""

    bl_idname = "mixar.director_new_shot"
    bl_label = "New Shot"
    bl_description = "Create a new shot and align its camera to this view"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return state is not None

    def execute(self, context):
        try:
            enter_director_surface(context)
            camera = create_camera_from_view(context)
            shot = create_shot(context.scene, camera)
            enter_camera_view(context, camera)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.mixar_director.is_directing = True
        context.scene.mixar_director.timeline_expanded = True
        self.report({'INFO'}, f"Created {shot.name}")
        return {'FINISHED'}


class MIXAR_OT_director_finish(Operator):
    """Leave directing mode while preserving the camera and keyframes"""

    bl_idname = "mixar.director_finish"
    bl_label = "Finish Directing"
    bl_description = "Leave camera view without deleting this take"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing)

    def execute(self, context):
        state = context.scene.mixar_director
        _leave_immersive(context, state)
        state.is_directing = False
        restore_view(context, context.scene)
        return {'FINISHED'}


class MIXAR_OT_director_lock(Operator):
    """Freeze the current native camera path as an immutable take snapshot"""

    bl_idname = "mixar.director_lock"
    bl_label = "Lock Take"
    bl_description = "Freeze this take's camera path and guidance manifest"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None:
            return {'CANCELLED'}
        try:
            lock_shot(context.scene, shot)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        state = context.scene.mixar_director
        _leave_immersive(context, state)
        state.is_directing = False
        restore_view(context, context.scene)
        self.report({'INFO'}, f"Locked {shot.name}, take {shot.version}")
        return {'FINISHED'}


class MIXAR_OT_director_new_take(Operator):
    """Create an editable child of the selected locked take"""

    bl_idname = "mixar.director_new_take"
    bl_label = "New Take"
    bl_description = "Keep the locked take and begin a new editable take"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None or shot.state != 'LOCKED':
            return {'CANCELLED'}
        new_take = create_new_take(context.scene, shot)
        try:
            enter_director_surface(context)
            enter_camera_view(context, new_take.camera)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.mixar_director.is_directing = True
        self.report({'INFO'}, f"Started take {new_take.version}")
        return {'FINISHED'}


class MIXAR_OT_director_remove_shot(Operator):
    """Remove the selected shot record but preserve its scene data"""

    bl_idname = "mixar.director_remove_shot"
    bl_label = "Remove Shot"
    bl_description = "Remove shot metadata; cameras and moodboard frames stay"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.shots and not state.is_directing)

    def invoke(self, context, _event):
        return context.window_manager.invoke_confirm(self, _event)

    def execute(self, context):
        state = context.scene.mixar_director
        if not remove_shot(context.scene, state.active_shot_index):
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_enter,
    MIXAR_OT_director_start,
    MIXAR_OT_director_new_shot,
    MIXAR_OT_director_finish,
    MIXAR_OT_director_lock,
    MIXAR_OT_director_new_take,
    MIXAR_OT_director_remove_shot,
)
