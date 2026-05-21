# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Edit State Properties

Defines PropertyGroups for tracking image editing tool state.
"""

from bpy.types import PropertyGroup
from bpy.props import (
    FloatProperty,
    IntProperty,
    BoolProperty,
    EnumProperty,
    CollectionProperty,
)
from mixar.modules.moodboard.constants import EDIT_TOOL_TYPES


class LassoPoint(PropertyGroup):
    """A single point in a lasso selection"""
    x: FloatProperty(name="X", default=0.0)
    y: FloatProperty(name="Y", default=0.0)


class MoodboardEditToolState(PropertyGroup):
    """State for moodboard image editing tools"""
    active_tool: EnumProperty(
        name="Active Tool",
        items=EDIT_TOOL_TYPES,
        default='NONE'
    )

    # Target image index
    target_image_index: IntProperty(name="Target Image Index", default=-1)

    # Box selection/crop coordinates (in image space, 0-1)
    box_start_x: FloatProperty(name="Box Start X", default=0.0)
    box_start_y: FloatProperty(name="Box Start Y", default=0.0)
    box_end_x: FloatProperty(name="Box End X", default=1.0)
    box_end_y: FloatProperty(name="Box End Y", default=1.0)

    # Is currently drawing a selection
    is_drawing: BoolProperty(name="Is Drawing", default=False, options={'SKIP_SAVE'})

    # Active crop handle being dragged (-1 = none, 0-7 = handle index)
    # Corners: 0=bottom-left, 1=bottom-right, 2=top-right, 3=top-left
    # Edges: 4=bottom, 5=right, 6=top, 7=left
    active_handle: IntProperty(name="Active Handle", default=-1)

    # Lasso points collection
    lasso_points: CollectionProperty(type=LassoPoint)

    # Magic Select state
    magic_select_pending: BoolProperty(
        name="Magic Select Pending",
        description="Whether a segmentation request is in progress",
        default=False,
        options={'SKIP_SAVE'},
    )

    # Box Select SAM state
    box_select_pending: BoolProperty(
        name="Box Select SAM Pending",
        description="Whether a box segmentation API request is in progress",
        default=False,
        options={'SKIP_SAVE'},
    )
    box_select_has_selection: BoolProperty(
        name="Box Select Has Selection",
        description="Whether a valid box selection exists for SAM processing",
        default=False,
        options={'SKIP_SAVE'},
    )

    # Lasso Select SAM state
    lasso_select_pending: BoolProperty(
        name="Lasso Select SAM Pending",
        description="Whether a lasso/mask segmentation API request is in progress",
        default=False,
        options={'SKIP_SAVE'},
    )
    lasso_select_has_selection: BoolProperty(
        name="Lasso Select Has Selection",
        description="Whether a valid lasso selection exists for SAM refinement",
        default=False,
        options={'SKIP_SAVE'},
    )


classes = (
    LassoPoint,
    MoodboardEditToolState,
)
