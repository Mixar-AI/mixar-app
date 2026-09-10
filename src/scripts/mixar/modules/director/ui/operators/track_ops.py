# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Top-strip controls: keyframe interpolation and eyedropper object tracking."""

from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator

from ...constants import INTERPOLATION_ITEMS
from ...core.shot_api import active_shot
from ...core.tracking import pick_object_under_cursor


def _editable_shot(context):
    shot = active_shot(context.scene)
    if shot is None or shot.state != 'DRAFT' or shot.camera is None:
        return None
    return shot


class MIXAR_OT_director_set_interpolation(Operator):
    """Choose how the camera eases between this shot's keyframes"""

    bl_idname = "mixar.director_set_interpolation"
    bl_label = "Interpolation"
    bl_options = {'REGISTER', 'UNDO'}

    interpolation: EnumProperty(
        name="Interpolation",
        items=INTERPOLATION_ITEMS,
        default="BEZIER",
    )

    @classmethod
    def poll(cls, context):
        return _editable_shot(context) is not None

    def execute(self, context):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        # The property's update callback re-interpolates the existing keys.
        shot.interpolation = self.interpolation
        return {'FINISHED'}


class MIXAR_OT_director_pick_track_target(Operator):
    """Pick an object in the viewport for the shot camera to keep pointing at"""

    bl_idname = "mixar.director_pick_track_target"
    bl_label = "Track Object"
    bl_description = (
        "Eyedropper: click an object and the shot camera keeps pointing at it "
        "while you move; click again to stop tracking"
    )
    bl_options = {'REGISTER', 'UNDO'}

    clear: BoolProperty(
        name="Clear",
        description="Stop tracking instead of picking",
        default=False,
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _editable_shot(context) is not None

    def invoke(self, context, _event):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        if self.clear:
            shot.track_target = None
            self.report({'INFO'}, "Camera tracking cleared")
            return {'FINISHED'}
        if getattr(context, "region", None) is None or context.region.type != 'WINDOW':
            self.report({'ERROR'}, "Start the eyedropper from the 3D viewport")
            return {'CANCELLED'}
        context.window.cursor_modal_set('EYEDROPPER')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            context.window.cursor_modal_restore()
            return {'CANCELLED'}
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            return {'RUNNING_MODAL'}
        shot = _editable_shot(context)
        region = context.region
        space = getattr(context, "space_data", None)
        region_3d = getattr(space, "region_3d", None)
        if shot is None or region is None or region_3d is None:
            context.window.cursor_modal_restore()
            return {'CANCELLED'}
        coord = (event.mouse_region_x, event.mouse_region_y)
        try:
            target = pick_object_under_cursor(context, region, region_3d, coord)
        except Exception as exc:  # noqa: BLE001 — surfaced, never swallowed
            context.window.cursor_modal_restore()
            self.report({'ERROR'}, f"Could not pick: {exc}")
            return {'CANCELLED'}
        if target is None or target == shot.camera:
            # Keep the eyedropper alive: a miss is not a decision.
            self.report({'WARNING'}, "No object under the cursor")
            return {'RUNNING_MODAL'}
        context.window.cursor_modal_restore()
        shot.track_target = target
        self.report({'INFO'}, f"Camera tracks {target.name}")
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_set_interpolation,
    MIXAR_OT_director_pick_track_target,
)
