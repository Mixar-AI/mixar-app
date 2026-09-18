# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Project-owned freehand marks in the moodboard's unbounded canvas space."""

import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, FloatVectorProperty
from bpy.types import PropertyGroup

from ...constants import ANNOTATION_COLOR_DEFAULT, ANNOTATION_WIDTH_DEFAULT


class MixieMoodboardCanvasPoint(PropertyGroup):
    x: FloatProperty(name="X")
    y: FloatProperty(name="Y")


class MixieMoodboardCanvasStroke(PropertyGroup):
    points: CollectionProperty(type=MixieMoodboardCanvasPoint)
    color: FloatVectorProperty(
        name="Color", subtype="COLOR", size=4,
        default=ANNOTATION_COLOR_DEFAULT, min=0.0, max=1.0,
    )
    # Stored in canvas units, so both points and width follow canvas zoom.
    width: FloatProperty(name="Width", default=ANNOTATION_WIDTH_DEFAULT, min=0.001)


classes = (MixieMoodboardCanvasPoint, MixieMoodboardCanvasStroke)


def register():
    # Collections must be attached after their point/stroke RNA types exist.
    for cls in classes:
        if not cls.is_registered:
            bpy.utils.register_class(cls)
    if not hasattr(bpy.types.Scene, "mixie_moodboard_annotations"):
        bpy.types.Scene.mixie_moodboard_annotations = CollectionProperty(
            type=MixieMoodboardCanvasStroke, name="Moodboard Annotations",
        )
        bpy.types.Scene.mixie_moodboard_show_annotations = BoolProperty(
            name="Show Annotations", default=True,
        )
    if not hasattr(bpy.types.WindowManager, "mixie_moodboard_annotating"):
        bpy.types.WindowManager.mixie_moodboard_annotating = BoolProperty(
            name="Annotate", default=False, options={"SKIP_SAVE"},
        )
    if not hasattr(bpy.types.WindowManager, "mixie_moodboard_erasing"):
        bpy.types.WindowManager.mixie_moodboard_erasing = BoolProperty(
            name="Erase", default=False, options={"SKIP_SAVE"},
        )


def unregister():
    for owner, names in (
        (bpy.types.Scene, ("mixie_moodboard_annotations", "mixie_moodboard_show_annotations")),
        (bpy.types.WindowManager, ("mixie_moodboard_annotating", "mixie_moodboard_erasing")),
    ):
        for name in names:
            if hasattr(owner, name):
                delattr(owner, name)
    for cls in reversed(classes):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
