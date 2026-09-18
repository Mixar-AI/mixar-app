# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Destructive strip editing for the Director timeline: split and delete."""

from bpy.props import IntProperty
from bpy.types import Operator

from ...core.capture import remove_beat
from ...core.shot_api import active_shot, split_shot


def _draft_shot(context):
    shot = active_shot(context.scene)
    if shot is None or shot.state != 'DRAFT':
        return None
    return shot


class MIXAR_OT_director_split_strip(Operator):
    """Split this shot at the playhead into two shots on the same camera"""

    bl_idname = "mixar.director_split_strip"
    bl_label = "Split at Playhead"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        shot = _draft_shot(context)
        return bool(shot and len(shot.beats) >= 2)

    def execute(self, context):
        shot = _draft_shot(context)
        if shot is None:
            return {'CANCELLED'}
        # Read the name before the split: adding the second shot invalidates
        # this reference into the shots collection.
        original_name = shot.name
        try:
            new_shot = split_shot(
                context.scene, shot, int(context.scene.frame_current)
            )
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Split into {original_name} and {new_shot.name}",
        )
        return {'FINISHED'}


class MIXAR_OT_director_clear_strip(Operator):
    """Delete every keyframe of this shot, its camera keys, and its stills"""

    bl_idname = "mixar.director_clear_strip"
    bl_label = "Clear All Keyframes"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        shot = _draft_shot(context)
        return bool(shot and shot.beats)

    def invoke(self, context, _event):
        return context.window_manager.invoke_confirm(self, _event)

    def execute(self, context):
        shot = _draft_shot(context)
        if shot is None:
            return {'CANCELLED'}
        removed = 0
        for index in reversed(range(len(shot.beats))):
            if remove_beat(context.scene, shot, index):
                removed += 1
        self.report({'INFO'}, f"Removed {removed} keyframes from {shot.name}")
        return {'FINISHED'}


class MIXAR_OT_director_strip_menu(Operator):
    """Show split and delete actions for the timeline strip"""

    bl_idname = "mixar.director_strip_menu"
    bl_label = "Strip Actions"
    bl_options = {'REGISTER'}

    index: IntProperty(default=-1, options={'SKIP_SAVE'})

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None:
            return {'CANCELLED'}
        beat_index = self.index
        if beat_index < 0:
            # Right-clicking the strip body still deletes the keyframe the
            # playhead is parked on, when there is one.
            frame = int(context.scene.frame_current)
            beat_index = next(
                (
                    index
                    for index, beat in enumerate(shot.beats)
                    if int(beat.frame) == frame
                ),
                -1,
            )
        draft = shot.state == 'DRAFT'

        def draw(menu, _context):
            layout = menu.layout
            layout.operator_context = 'INVOKE_DEFAULT'
            if draft:
                if beat_index >= 0:
                    delete = layout.operator(
                        "mixar.director_remove_beat",
                        text=f"Delete Keyframe {beat_index + 1}",
                        icon='X',
                    )
                    delete.index = beat_index
                layout.operator(
                    "mixar.director_split_strip",
                    icon='ARROW_LEFTRIGHT',
                )
                layout.separator()
                layout.operator("mixar.director_clear_strip", icon='TRASH')
            layout.operator(
                "mixar.director_remove_shot",
                text="Remove Shot",
                icon='CANCEL',
            )

        context.window_manager.popup_menu(
            draw, title=shot.name, icon='CAMERA_DATA'
        )
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_split_strip,
    MIXAR_OT_director_clear_strip,
    MIXAR_OT_director_strip_menu,
)
