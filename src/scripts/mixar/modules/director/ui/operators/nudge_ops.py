# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The W/A/S/D and Q/E camera motion the Cinema Mode strip advertises."""

import time

from bpy.props import EnumProperty
from bpy.types import Operator

from ...core.camera_nudge import (
    MAX_STEP_SECONDS,
    NUDGE_DIRECTIONS,
    move_camera,
    nudge_offset,
    step_seconds,
    walk_speed,
)
from ...core.shot_api import active_shot


# Wall-clock of the previous press, shared across the six directions so a
# diagonal (two keys held) travels at walk speed rather than double it. Module
# level, not a class attribute: Blender reads an Operator's annotations to
# find its properties, and a bare one there is not a `bpy.props` definition.
_last_press = None


def _directed_camera(context):
    state = getattr(context.scene, "mixar_director", None)
    if not state or not state.is_directing:
        return None, None
    shot = active_shot(context.scene)
    if shot is None or shot.camera is None:
        return None, None
    return shot, shot.camera


def _in_cinema_viewport(context) -> bool:
    """True while directing, with the cursor in a 3D viewport's main region.

    The poll deliberately does NOT require a camera. It is what decides
    whether the key is ABSORBED, and absorbing has to happen even when the
    take has no camera or is locked — otherwise S falls through to
    `transform.resize` and A to `object.select_all`, which is the behaviour
    the nudge exists to replace. `execute` handles the no-camera and locked
    cases instead.

    The area/region test is load-bearing: the binding also lives in the
    global "User Interface" keymap (the only one Blender dispatches ahead of
    both `UI_OT_eyedropper_depth` on E and our own `director_block_input`
    guard on S), so without it these keys would be claimed app-wide.
    """
    state = getattr(context.scene, "mixar_director", None)
    if not state or not state.is_directing:
        return False
    area = getattr(context, "area", None)
    region = getattr(context, "region", None)
    if area is None or region is None:
        return False
    return area.type == 'VIEW_3D' and region.type == 'WINDOW'


class MIXAR_OT_director_nudge_camera(Operator):
    """Move the shot camera one walk-style step"""

    bl_idname = "mixar.director_nudge_camera"
    bl_label = "Move Camera"
    # UNDO_GROUPED, not UNDO: a held key repeats at the OS rate, and one undo
    # step per repeat would bury whatever the user did before the move.
    bl_options = {'REGISTER', 'UNDO_GROUPED'}

    direction: EnumProperty(
        name="Direction",
        items=tuple(
            (key, label, tooltip, index)
            for index, (key, label, tooltip) in enumerate(NUDGE_DIRECTIONS)
        ),
        default="FORWARD",
    )

    @classmethod
    def poll(cls, context):
        return _in_cinema_viewport(context)

    def execute(self, context):
        shot, camera = _directed_camera(context)
        if camera is None:
            return {'CANCELLED'}
        global _last_press
        now = time.monotonic()
        last = _last_press
        seconds = step_seconds(now, last)
        fresh_press = last is None or (now - last) > MAX_STEP_SECONDS
        _last_press = now

        if shot.state == 'LOCKED':
            # The key is still absorbed — falling through would hand W/A/S/D
            # back to Blender, where A selects everything. Report once per
            # burst so a held key cannot flood the status bar.
            if fresh_press:
                self.report(
                    {'INFO'},
                    "This take is locked; start a new take to move the camera",
                )
            return {'CANCELLED'}

        offset = nudge_offset(camera, self.direction, walk_speed(context) * seconds)
        if offset.length_squared == 0.0:
            return {'CANCELLED'}
        move_camera(camera, offset)
        return {'FINISHED'}


classes = (MIXAR_OT_director_nudge_camera,)
