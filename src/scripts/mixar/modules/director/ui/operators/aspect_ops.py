# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A ratio the presets do not cover."""

from bpy.props import IntProperty
from bpy.types import Operator

from ...core.aspect import (
    apply_ratio,
    normalise_ratio,
    ratio_label,
    remember_camera_ratio,
    scene_ratio,
)
from ...core.shot_api import active_shot, refresh_manifest


def _editable_shot(context):
    shot = active_shot(context.scene)
    if shot is None or shot.state != 'DRAFT' or shot.camera is None:
        return None
    return shot


class MIXAR_OT_director_set_custom_aspect(Operator):
    """Frame this camera for a ratio the presets do not cover"""

    bl_idname = "mixar.director_set_custom_aspect"
    bl_label = "Custom Aspect Ratio"
    bl_description = "Set an aspect ratio of your own for this camera"
    bl_options = {'REGISTER', 'UNDO'}

    # A ratio, not a pixel size — the resolution tier stays the quality. The
    # bound is generous rather than tight: 2048:858 is a real DCI ratio and
    # nobody should have to reduce it by hand first.
    ratio_width: IntProperty(
        name="Width",
        description="Width side of the ratio",
        default=16,
        min=1,
        max=100000,
    )
    ratio_height: IntProperty(
        name="Height",
        description="Height side of the ratio",
        default=9,
        min=1,
        max=100000,
    )

    @classmethod
    def poll(cls, context):
        return _editable_shot(context) is not None

    def _ratio(self, context) -> tuple[int, int]:
        """The ratio to apply: the caller's, else the popup's own fields.

        The surface never sets the properties — it edits
        ``state.custom_aspect_x/y`` as ordinary RNA number fields in the
        aspect popup, and this row just applies what is in them. A script or
        the agent can still pass the ratio directly, and that wins.
        """
        properties = self.properties
        if properties.is_property_set("ratio_width") or properties.is_property_set(
            "ratio_height"
        ):
            return self.ratio_width, self.ratio_height
        state = getattr(context.scene, "mixar_director", None)
        if state is None:
            return scene_ratio(context.scene)
        return int(state.custom_aspect_x), int(state.custom_aspect_y)

    def execute(self, context):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        ratio_w, ratio_h = normalise_ratio(*self._ratio(context))
        remember_camera_ratio(shot.camera, ratio_w, ratio_h)
        width, height = apply_ratio(context.scene, ratio_w, ratio_h)
        if shot.beats:
            refresh_manifest(context.scene, shot)
        self.report(
            {'INFO'},
            f"{ratio_label(ratio_w, ratio_h)} — {width} x {height}",
        )
        return {'FINISHED'}


classes = (MIXAR_OT_director_set_custom_aspect,)
