# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Aerial mode: the main viewport looks down on the scene from above.

``O`` (the Cinema Mode "Aerial view" hint) toggles it; a click in the stage
places the shot camera at that world XY (the native
``MIXAR_OT_director_place_camera`` modal, whose poll opens up to the whole
stage while ``navigation_mode == 'AERIAL'``); ``O`` again or ``Esc`` returns
to the camera. Every other way back into a camera (shot switch, keyframe
jump, new take) ends the mode through ``enter_camera_view``.
"""

from bpy.types import Operator

from ...core.shot_api import active_shot
from ...core.viewport import enter_aerial_view, enter_camera_view, enter_free_view

AERIAL_ENTER_MESSAGE = "Aerial view — click to place the camera, O to return"
AERIAL_EXIT_MESSAGE = "Back to the camera"


def _leave_aerial(context):
    """Return to the shot camera, or to a plain perspective without one."""
    state = context.scene.mixar_director
    shot = active_shot(context.scene)
    camera = getattr(shot, "camera", None) if shot is not None else None
    if camera is not None:
        # Flips AERIAL back to NAVIGATE itself: it is the single way back
        # into a camera.
        enter_camera_view(context, camera, remember=False)
    else:
        enter_free_view(context)
        state.navigation_mode = 'NAVIGATE'


class MIXAR_OT_director_aerial(Operator):
    """Look down on the scene from above and click to place the camera; press again to return"""

    bl_idname = "mixar.director_aerial"
    bl_label = "Aerial View"
    # View state only: not undoable.
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing)

    def execute(self, context):
        state = context.scene.mixar_director
        try:
            if state.navigation_mode != 'AERIAL':
                enter_aerial_view(context, context.scene)
                self.report({'INFO'}, AERIAL_ENTER_MESSAGE)
            else:
                _leave_aerial(context)
                self.report({'INFO'}, AERIAL_EXIT_MESSAGE)
        except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_director_aerial_exit(Operator):
    """Return from the aerial view to the camera"""

    bl_idname = "mixar.director_aerial_exit"
    bl_label = "Leave Aerial View"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        # Esc must never ENTER the mode: this poll passes only while inside
        # it, so outside Aerial the key falls through untouched.
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing and state.navigation_mode == 'AERIAL')

    def execute(self, context):
        try:
            _leave_aerial(context)
        except Exception as exc:  # noqa: BLE001
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, AERIAL_EXIT_MESSAGE)
        return {'FINISHED'}


classes = (MIXAR_OT_director_aerial, MIXAR_OT_director_aerial_exit)
