# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mode-level Director surface, navigation, and contextual popovers."""

import bpy
from bpy.types import Operator

from ...core.shot_api import active_shot
from ...core.viewport import enter_camera_view, enter_director_surface


def _director_state(context):
    return getattr(context.scene, "mixar_director", None)


def _redraw(context) -> None:
    for area in getattr(context.screen, "areas", ()):
        if area.type in {'VIEW_3D', 'MIXIE'}:
            area.tag_redraw()


def _jump_relative(context, offset: int):
    shot = active_shot(context.scene)
    if shot is None or not shot.beats:
        return {'CANCELLED'}
    index = min(max(shot.active_beat_index + offset, 0), len(shot.beats) - 1)
    shot.active_beat_index = index
    context.scene.frame_set(shot.beats[index].frame)
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
    """Jump to the previous sparse camera beat"""

    bl_idname = "mixar.director_previous_beat"
    bl_label = "Previous Camera Beat"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            return _jump_relative(context, -1)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class MIXAR_OT_director_next_beat(Operator):
    """Jump to the next sparse camera beat"""

    bl_idname = "mixar.director_next_beat"
    bl_label = "Next Camera Beat"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            return _jump_relative(context, 1)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class MIXAR_OT_director_open_canvas(Operator):
    """Switch the current Director area to the Mixar canvas"""

    bl_idname = "mixar.director_open_canvas"
    bl_label = "Canvas"
    bl_description = "Review camera beats and references on the Moodboard canvas"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        state = _director_state(context)
        return bool(state and state.is_directing and context.area)

    def execute(self, context):
        context.area.type = 'MIXIE'
        space = context.area.spaces.active
        if hasattr(space, "mixie_mode"):
            space.mixie_mode = 'MOODBOARD'
        context.area.tag_redraw()
        return {'FINISHED'}


class MIXAR_OT_director_open_editor(Operator):
    """Return from Canvas to the active Director viewport"""

    bl_idname = "mixar.director_open_editor"
    bl_label = "3D Editor"
    bl_description = "Return to camera directing"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        state = _director_state(context)
        return bool(state and state.is_directing and context.area)

    def execute(self, context):
        context.area.type = 'VIEW_3D'
        try:
            enter_director_surface(context)
            shot = active_shot(context.scene)
            if shot is not None and shot.camera is not None:
                enter_camera_view(context, shot.camera, remember=False)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.area.tag_redraw()
        return {'FINISHED'}


class MIXAR_OT_director_show_shots(Operator):
    """Open the focused shots-and-takes popover"""

    bl_idname = "mixar.director_show_shots"
    bl_label = "Shots"
    bl_options = {'REGISTER'}

    def invoke(self, _context, _event):
        return bpy.ops.wm.call_panel(
            'INVOKE_DEFAULT',
            name="MIXAR_PT_director_shots_popover",
            keep_open=True,
        )


class MIXAR_OT_director_show_camera(Operator):
    """Open the focused camera-and-timing popover"""

    bl_idname = "mixar.director_show_camera"
    bl_label = "Camera Controls"
    bl_options = {'REGISTER'}

    def invoke(self, _context, _event):
        return bpy.ops.wm.call_panel(
            'INVOKE_DEFAULT',
            name="MIXAR_PT_director_camera_popover",
            keep_open=True,
        )


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
    MIXAR_OT_director_open_canvas,
    MIXAR_OT_director_open_editor,
    MIXAR_OT_director_show_shots,
    MIXAR_OT_director_show_camera,
    MIXAR_OT_director_toggle_immersive,
)
