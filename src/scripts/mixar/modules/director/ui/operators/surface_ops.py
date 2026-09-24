# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mode-level Director surface, navigation, and contextual popovers."""

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from ...core.shot_api import active_shot, adopt_camera
from ...core.viewport import enter_camera_view


def _director_state(context):
    return getattr(context.scene, "mixar_director", None)


def _redraw(context) -> None:
    for area in getattr(context.screen, "areas", ()):
        if area.type in {'VIEW_3D', 'MIXIE'}:
            area.tag_redraw()


def _jump_relative(context, offset: int):
    """Step the playhead to the neighbouring keyframe of the active shot.

    The step is taken from ``scene.frame_current``, NOT from
    ``shot.active_beat_index``. The index is only ever written by a deliberate
    jump, so scrubbing the ruler, dragging a handle, retiming with the Speed
    slider, or playing the shot all leave it pointing somewhere the playhead is
    not — and a "previous keyframe" click then stepped from that stale index or,
    once it had been clamped to an end, reported success and moved nothing.
    That is the arrows "sometimes" doing nothing.

    Beats are searched in FRAME order because the collection keeps insertion
    order, which a retime or a handle drag reorders in time but not in the
    collection.
    """
    shot = active_shot(context.scene)
    if shot is None or not shot.beats:
        return {'CANCELLED'}
    scene = context.scene
    current = int(scene.frame_current)
    ordered = sorted(
        ((int(beat.frame), index) for index, beat in enumerate(shot.beats)),
    )
    if offset < 0:
        candidates = [pair for pair in ordered if pair[0] < current]
        target = candidates[-1] if candidates else None
    else:
        candidates = [pair for pair in ordered if pair[0] > current]
        target = candidates[0] if candidates else None
    if target is None:
        # No keyframe that way — the same answer Blender's own keyframe jump
        # gives at the ends of a channel.
        return {'CANCELLED'}
    frame, index = target
    shot.active_beat_index = index
    scene.frame_set(frame)
    enter_camera_view(context, shot.camera, remember=False)
    return {'FINISHED'}


class MIXAR_OT_director_toggle_timeline(Operator):
    """Expand or collapse the native Director timeline"""

    bl_idname = "mixar.director_toggle_timeline"
    bl_label = "Toggle Timeline"
    bl_options = {'REGISTER'}

    def execute(self, context):
        state = _director_state(context)
        if state is None or not state.is_directing:
            return {'CANCELLED'}
        state.timeline_expanded = not state.timeline_expanded
        _redraw(context)
        return {'FINISHED'}


class MIXAR_OT_director_previous_beat(Operator):
    """Jump to the previous sparse keyframe"""

    bl_idname = "mixar.director_previous_beat"
    bl_label = "Previous Keyframe"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            return _jump_relative(context, -1)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class MIXAR_OT_director_next_beat(Operator):
    """Jump to the next sparse keyframe"""

    bl_idname = "mixar.director_next_beat"
    bl_label = "Next Keyframe"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            return _jump_relative(context, 1)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class MIXAR_OT_director_set_active_shot(Operator):
    """Direct the chosen shot"""

    bl_idname = "mixar.director_set_active_shot"
    bl_label = "Select Shot"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=0, min=0, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        state = _director_state(context)
        return bool(state and state.shots)

    def execute(self, context):
        state = _director_state(context)
        index = min(self.index, len(state.shots) - 1)
        if state.active_shot_index != index:
            # The active-shot update callback syncs the scene camera, the
            # camera view, and the preview range.
            state.active_shot_index = index
        return {'FINISHED'}


class MIXAR_OT_director_pick_camera(Operator):
    """Choose which camera this shot directs"""

    bl_idname = "mixar.director_pick_camera"
    bl_label = "Select Camera"
    bl_options = {'REGISTER', 'UNDO'}

    camera_name: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        scene = context.scene
        state = _director_state(context)
        camera = bpy.data.objects.get(self.camera_name)
        if state is None or camera is None or camera.type != 'CAMERA':
            return {'CANCELLED'}
        # Each camera is its own shot/timeline. `adopt_camera` switches to the
        # shot that already directs this one, or starts a fresh shot for a
        # camera with none — never reassigning, which collapsed every camera
        # onto one strip. Entering Cinema Mode adopts through the same rule.
        adopt_camera(scene, camera)
        return {'FINISHED'}

    def invoke(self, context, _event):
        # A chosen name applies directly; an empty name opens the camera list.
        if self.camera_name:
            return self.execute(context)
        cameras = [obj for obj in context.scene.objects if obj.type == 'CAMERA']

        def draw(menu, _context):
            column = menu.layout.column()
            if not cameras:
                column.label(text="No cameras in scene")
            for obj in cameras:
                column.operator(
                    "mixar.director_pick_camera", text=obj.name, icon='CAMERA_DATA'
                ).camera_name = obj.name

        context.window_manager.popup_menu(draw, title="Camera", icon='CAMERA_DATA')
        return {'FINISHED'}


class MIXAR_OT_director_toggle_immersive(Operator):
    """Toggle Blender's maximized-area presentation for Director"""

    bl_idname = "mixar.director_toggle_immersive"
    bl_label = "Expand Director"
    bl_description = "Toggle an immersive full-window Director viewport"
    bl_options = {'REGISTER'}

    def execute(self, context):
        state = _director_state(context)
        if state is None or not state.is_directing:
            return {'CANCELLED'}
        was_fullscreen = bool(
            getattr(getattr(context, "screen", None), "show_fullscreen", False)
        )
        try:
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        state.is_immersive = not was_fullscreen
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_toggle_timeline,
    MIXAR_OT_director_previous_beat,
    MIXAR_OT_director_next_beat,
    MIXAR_OT_director_set_active_shot,
    MIXAR_OT_director_pick_camera,
    MIXAR_OT_director_toggle_immersive,
)
