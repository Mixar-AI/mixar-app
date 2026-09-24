# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Duplicate the Director keyframes a timeline selection covers.

The selection is the camera's own key selection (`core/native_keys.py`);
the dock hands over the beats sitting on its selected keys. ``indices`` is a
comma-separated string because Blender's ``IntVectorProperty`` is
fixed-size and a selection is not; ``core/selection.py`` parses it.
"""

from bpy.props import StringProperty
from bpy.types import Operator

from ...core.duplicate import duplicate_beats
from ...core.native_keys import select_columns
from ...core.selection import parse_indices
from ...core.shot_api import active_shot


def _editable_shot(context):
    shot = active_shot(context.scene)
    if shot is None or shot.state != 'DRAFT' or not shot.beats:
        return None
    return shot


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
        # The copies become the selection, so a drag started next (Shift+D
        # hands them straight to one) moves them and nothing else.
        select_columns(shot.camera, [int(beat.frame) for beat in created], 'SET')
        self.report({'INFO'}, f"Duplicated {len(created)} keyframe(s)")
        return {'FINISHED'}


classes = (MIXAR_OT_director_duplicate_beats,)
