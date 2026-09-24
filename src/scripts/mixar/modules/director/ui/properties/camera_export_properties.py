# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Settings for the camera-first Export to Moodboard surface.

Scene-level, not shot-level: this is the surface a power user reaches when
there is no Director shot at all. The pass/resolution choices mirror the
shot's so the two surfaces read as one feature, and the live render state
carries `SKIP_SAVE` for the same reason a shot's does — a `.blend` must never
open claiming a render is in progress.
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from ...constants import CAMERA_EXPORT_RANGE_ITEMS, SHOT_RENDER_OUTPUT_ITEMS


def _camera_poll(_self, obj):
    return getattr(obj, "type", None) == 'CAMERA'


class MixarCameraExportSettings(PropertyGroup):
    """Which camera, over which frames, rendered how."""

    camera_override: PointerProperty(
        type=bpy.types.Object,
        name="Camera",
        description=(
            "Camera to render. Leave empty to follow the selected or active "
            "camera, then the scene camera"
        ),
        poll=_camera_poll,
    )
    range_source: EnumProperty(
        name="Range",
        description="Which frames the videos cover",
        items=CAMERA_EXPORT_RANGE_ITEMS,
        default="CAMERA_KEYS",
    )
    render_output_types: EnumProperty(
        name="Videos",
        description="Videos of this camera to render into the Moodboard",
        items=SHOT_RENDER_OUTPUT_ITEMS,
        options={'ENUM_FLAG'},
        default={'CLAY'},
    )
    render_resolution_percentage: IntProperty(
        name="Video Size",
        description="Size of the videos, as a percentage of the scene's output size",
        default=50,
        min=25,
        max=100,
        subtype='PERCENTAGE',
    )
    render_is_running: BoolProperty(
        name="Rendering",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    render_progress: FloatProperty(
        name="Render Progress",
        default=0.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    render_status: StringProperty(
        name="Render Status",
        default="",
        maxlen=256,
        options={'SKIP_SAVE', 'HIDDEN'},
    )


classes = (
    MixarCameraExportSettings,
)


def register():
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    bpy.types.Scene.mixar_camera_export = PointerProperty(
        type=MixarCameraExportSettings,
        name="Mixar Camera Export",
        description="Export this scene's camera animation to the Moodboard",
    )


def unregister():
    if hasattr(bpy.types.Scene, "mixar_camera_export"):
        del bpy.types.Scene.mixar_camera_export
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
