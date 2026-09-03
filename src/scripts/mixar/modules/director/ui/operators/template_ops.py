# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cinema Mode's "Template Style" list and output-resolution tiers.

The designed surface presents one list of named movement styles. Underneath
they are two different kinds of thing, and this dispatcher is the only place
that knows which is which:

* ``HANDHELD`` and ``Z_FIXED`` are STATES — a flag on the shot and a flag on
  the session. Handheld deliberately stays an F-modifier flag rather than
  becoming a camera-move preset (jitter cannot be sparse-keyframed; see
  ``core/handheld.py``), so this operator sets ``shot.handheld`` and never
  routes it through ``apply_camera_move``.
* ``DOLLY_ZOOM`` and ``CRANE`` are one-shot MOVES that key a path through the
  existing ``core/camera_moves`` presets.

``shot.camera_template`` records the choice so the list can highlight it
honestly; it changes no behaviour by itself.
"""

from bpy.props import EnumProperty
from bpy.types import Operator

from ...constants import CAMERA_TEMPLATE_ITEMS, RESOLUTION_PRESETS
from ...core.camera_moves import apply_camera_move
from ...core.shot_api import active_shot

# Templates that key a path, and the existing preset each one runs.
_TEMPLATE_MOVES = {
    "DOLLY_ZOOM": "DOLLY_IN",
    "CRANE": "CRANE_UP",
}


class MIXAR_OT_director_set_template(Operator):
    """Apply a named camera template to the active shot"""

    bl_idname = "mixar.director_set_template"
    bl_label = "Template Style"
    bl_options = {'REGISTER', 'UNDO'}

    template: EnumProperty(
        name="Template",
        items=CAMERA_TEMPLATE_ITEMS,
        default="NONE",
    )

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        shot = active_shot(context.scene) if state else None
        return bool(state and state.is_directing and shot and shot.state == 'DRAFT')

    def execute(self, context):
        state = context.scene.mixar_director
        shot = active_shot(context.scene)
        if shot is None:
            return {'CANCELLED'}

        shot.camera_template = self.template
        # A template is exclusive: choosing one clears the state the previous
        # one left live, so the list always describes the shot it labels.
        shot.handheld = self.template == "HANDHELD"
        state.level_horizon = self.template == "Z_FIXED"

        move = _TEMPLATE_MOVES.get(self.template)
        if move is None:
            return {'FINISHED'}

        if shot.camera is None:
            self.report({'ERROR'}, "The shot has no camera to move")
            return {'CANCELLED'}
        try:
            frames = apply_camera_move(context, shot, state, move)
        except Exception as exc:  # noqa: BLE001 — surfaced, never swallowed
            self.report({'ERROR'}, f"Could not apply the template: {exc}")
            return {'CANCELLED'}
        if not frames:
            return {'CANCELLED'}
        self.report({'INFO'}, f"Added {len(frames)} keyframes through frame {frames[-1]}")
        return {'FINISHED'}


class MIXAR_OT_director_set_resolution(Operator):
    """Set the render resolution tier, keeping the scene's aspect ratio"""

    bl_idname = "mixar.director_set_resolution"
    bl_label = "Resolution"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(
        name="Preset",
        items=tuple(
            (key, label, f"Render at {label}", index)
            for index, (key, (label, _short)) in enumerate(RESOLUTION_PRESETS.items())
        ),
        default="HD1080",
    )

    def execute(self, context):
        render = context.scene.render
        _label, short_side = RESOLUTION_PRESETS[self.preset]
        width = render.resolution_x
        height = render.resolution_y
        if width <= 0 or height <= 0:
            return {'CANCELLED'}
        # Scale the SHORTER side to the tier so portrait and landscape scenes
        # get the same quality rather than the same pixel width.
        scale = short_side / float(min(width, height))
        render.resolution_x = max(1, int(round(width * scale)))
        render.resolution_y = max(1, int(round(height * scale)))
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_set_template,
    MIXAR_OT_director_set_resolution,
)
