# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent vector properties for image-attached moodboard annotations."""

from bpy.props import CollectionProperty, FloatProperty, FloatVectorProperty
from bpy.types import PropertyGroup

from mixar.modules.moodboard.constants import (
    ANNOTATION_COLOR_DEFAULT,
    ANNOTATION_WIDTH_DEFAULT,
    ANNOTATION_WIDTH_MAX,
    ANNOTATION_WIDTH_MIN,
)


class MixieMoodboardAnnotationPoint(PropertyGroup):
    """One normalized point in a freehand annotation stroke."""

    x: FloatProperty(name="X", default=0.0, min=0.0, max=1.0)
    y: FloatProperty(name="Y", default=0.0, min=0.0, max=1.0)


class MixieMoodboardAnnotationStroke(PropertyGroup):
    """A persistent freehand stroke attached to one moodboard image."""

    color: FloatVectorProperty(
        name="Color",
        description="Stroke color and opacity",
        subtype="COLOR",
        size=4,
        default=ANNOTATION_COLOR_DEFAULT,
        min=0.0,
        max=1.0,
    )
    width: FloatProperty(
        name="Width",
        description="Stroke width at the image's base display scale",
        default=ANNOTATION_WIDTH_DEFAULT,
        min=ANNOTATION_WIDTH_MIN,
        max=ANNOTATION_WIDTH_MAX,
    )
    points: CollectionProperty(type=MixieMoodboardAnnotationPoint)


classes = (
    MixieMoodboardAnnotationPoint,
    MixieMoodboardAnnotationStroke,
)
