# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cinema Mode's "Template Style" list and output-resolution tiers.

The designed surface presents one list of named movement styles. Underneath
they are two different kinds of thing, and this dispatcher is the only place
that knows which is which — but every pick has an effect the director can
SEE at once; a template that merely arms a flag reads as broken:

* ``HANDHELD`` is a STATE (``shot.handheld``): noise F-modifiers on the
  camera curves (``core/handheld.py``; jitter cannot be sparse-keyframed).
  Modifiers need curves, so on a shot with no keyframes the pick captures
  the anchor keyframe first and the drift is live from that moment.
* ``Z_FIXED`` is a STATE (``state.level_horizon``) that Navigate honours —
  and the pick also levels the camera NOW: every captured keyframe is
  re-keyed level, and the live pose too.
* ``DOLLY_ZOOM`` and ``CRANE`` are one-shot MOVES through the
  ``core/camera_moves`` presets. Dolly Zoom is the real thing: the camera
  dollies in while the lens widens so the subject holds its size.

``shot.camera_template`` records the choice so the list can highlight it
honestly; it changes no behaviour by itself.
"""

from bpy.props import EnumProperty
from bpy.types import Operator

from ...constants import CAMERA_TEMPLATE_ITEMS, RESOLUTION_PRESETS
from ...core.camera_moves import apply_camera_move
from ...core.capture import capture_beat
from ...core.rotation_curves import repair_rotation_continuity, rotation_data_path
from ...core.shot_api import active_shot, refresh_manifest
from ...core.viewport import level_camera_horizon

# Templates that key a path, and the existing preset each one runs.
_TEMPLATE_MOVES = {
    "DOLLY_ZOOM": "DOLLY_ZOOM",
    "CRANE": "CRANE_UP",
}


def _apply_handheld(context, shot, state) -> str:
    """Make handheld drift live now; returns the message to report."""
    if shot.beats:
        # The property update already re-attached the noise to the curves.
        return "Handheld drift on this shot's keyframes"
    # No curves yet for the noise to ride on: anchor the shot here, which
    # creates them (capture re-runs the handheld refresh itself).
    beat = capture_beat(context, shot, state.beat_seconds)
    return f"Captured keyframe 1 at frame {beat.frame} with handheld drift"


def _apply_level_horizon(context, shot) -> str:
    """Level the horizon on every keyframe and the live pose; returns the report."""
    camera = shot.camera
    scene = shot.scene_ref or context.scene
    frames = sorted({int(beat.frame) for beat in shot.beats})
    if not frames:
        if level_camera_horizon(camera):
            return "Horizon leveled; Navigate keeps it level"
        return "Camera is already level"
    original = int(scene.frame_current)
    leveled = 0
    try:
        for frame in frames:
            scene.frame_set(frame)
            context.view_layer.update()
            if level_camera_horizon(camera):
                camera.keyframe_insert(
                    data_path=rotation_data_path(camera), frame=frame, group="Director"
                )
                leveled += 1
        if leveled:
            repair_rotation_continuity(camera)
            refresh_manifest(scene, shot)
    finally:
        scene.frame_set(original)
        context.view_layer.update()
    if not leveled:
        return "Every keyframe is already level"
    return f"Leveled the horizon on {leveled} keyframe(s)"


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

        if self.template == "NONE":
            return {'FINISHED'}
        if shot.camera is None:
            self.report({'ERROR'}, "The shot has no camera")
            return {'CANCELLED'}

        try:
            if self.template == "HANDHELD":
                self.report({'INFO'}, _apply_handheld(context, shot, state))
                return {'FINISHED'}
            if self.template == "Z_FIXED":
                self.report({'INFO'}, _apply_level_horizon(context, shot))
                return {'FINISHED'}
            frames = apply_camera_move(context, shot, state, _TEMPLATE_MOVES[self.template])
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
