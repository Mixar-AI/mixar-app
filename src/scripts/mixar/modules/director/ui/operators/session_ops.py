# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Create, enter, finish, and lock camera-directing shots."""

import bpy
from bpy.types import Operator

from ...core.shot_api import (
    active_shot,
    adopt_camera,
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
    select_camera_object,
)


def _existing_camera(context, shot):
    """The camera Cinema Mode should open on: this shot's, else the scene's.

    Never creates one — entering the mode must not add a datablock to the
    file, and the surface's own empty state offers "+ Add Camera".
    """
    if shot is not None and shot.camera is not None:
        return shot.camera
    camera = context.scene.camera
    return camera if camera is not None and camera.type == 'CAMERA' else None


def _start_walking(operator, context) -> None:
    """Hand the camera to Blender's walk as the mode opens.

    Cinema Mode is camera work, so the director should already be flying when
    the surface appears rather than having to reach for the Walk chip first.
    Best effort by design: no camera, a locked take or a viewport that
    refuses the modal all just leave the mode open and not walking, which the
    chip and the hint strip then say.
    """
    if getattr(context.scene.mixar_director, "walk_active", False):
        return
    try:
        bpy.ops.mixar.director_navigate('INVOKE_DEFAULT')
    except Exception as exc:  # noqa: BLE001 — entering must never fail on this
        operator.report({'INFO'}, f"Walk navigation not started: {exc}")


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
    # User-facing name only; the idname stays `director_*` (frozen contract).
    bl_label = "Cinema Mode"
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
        # Directing FIRST, so the adoption below runs with the session live:
        # `_on_active_shot_change` only enters the camera view and selects the
        # camera while `is_directing`.
        state.is_directing = True
        state.timeline_expanded = True
        state.navigation_mode = 'NAVIGATE'
        state.walk_active = False

        # Look through the last active camera, and ADOPT it as the active
        # shot. Looking without adopting left the session with no shot at
        # all, which every shot-gated control reads as "nothing to do" — the
        # Walk chip came up greyed out and the My Cameras row never lit, on a
        # surface that was plainly looking through that very camera.
        #
        # Not a toggle: Cinema Mode is framed work, so the view is put INTO
        # the camera whatever it was showing — `enter_camera_view` writes
        # `view_perspective` directly rather than calling
        # `view3d.view_camera`, which would flip a viewport that already was
        # in camera view back out of it.
        camera = _existing_camera(context, active_shot(context.scene))
        if camera is not None:
            adopt_camera(context.scene, camera)
            try:
                enter_camera_view(context, camera)
            except Exception as exc:
                self.report({'WARNING'}, str(exc))
            else:
                # Gizmos and transform hotkeys follow the selection, so every
                # deliberate switch of the directed camera hands it over.
                select_camera_object(context, camera)
        # Last, so the walk starts on a camera that is already adopted,
        # selected and looked through — its poll needs the shot the adoption
        # above creates.
        _start_walking(self, context)
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
        # The property-update selection is gated on is_directing, which is
        # still False while the session starts — select explicitly here.
        select_camera_object(context, shot.camera)
        state.is_directing = True
        state.timeline_expanded = True
        state.navigation_mode = 'NAVIGATE'
        state.walk_active = False
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
        select_camera_object(context, camera)
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
        # A supervisor that never reached its exit (a file load, an
        # exception) would otherwise leave the strip advertising walk's keys
        # for the rest of the session.
        state.walk_active = False
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
        select_camera_object(context, new_take.camera)
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
        # Also reachable from the timeline strip menu while directing; the
        # empty-state overlay takes over when the last shot goes.
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.shots)

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
