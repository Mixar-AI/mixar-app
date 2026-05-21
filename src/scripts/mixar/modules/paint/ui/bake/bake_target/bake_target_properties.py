# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    PointerProperty,
    StringProperty,
)

from ..utils.bake_utils import normal_type_items, rgba_items


class MBakeTargetChannel(bpy.types.PropertyGroup):

    channel_name: StringProperty(
        name="Channel Source Name",
        description="Channel source name for bake target",
        default="",
    )

    subchannel_index: EnumProperty(
        name="Subchannel",
        description="Channel source RGBA index",
        items=rgba_items,
        default="0",
    )

    default_value: FloatProperty(
        name="Default Value",
        description="Channel default value",
        subtype="FACTOR",
        default=0.0,
        min=0.0,
        max=1.0,
    )

    normal_type: EnumProperty(
        name="Normal Channel Type",
        description="Normal channel source type",
        items=normal_type_items,
        default="COMBINED",
    )

    invert_value: BoolProperty(
        name="Invert Value", description="Invert value", default=False
    )


class MBakeTarget(bpy.types.PropertyGroup):
    name: StringProperty(
        name="Bake Target Name", description="Name of bake target name", default=""
    )

    data_type: EnumProperty(
        name="Bake Target Data Type",
        description="Bake target data type",
        items=(
            ("IMAGE", "Image", "", "IMAGE_DATA", 0),
            ("VCOL", "Vertex Color", "", "GROUP_VCOL", 1),
        ),
        default="IMAGE",
    )

    use_float: BoolProperty(
        name="32-bit Image", description="Use 32-bit float image", default=False
    )

    r: PointerProperty(type=MBakeTargetChannel)
    g: PointerProperty(type=MBakeTargetChannel)
    b: PointerProperty(type=MBakeTargetChannel)
    a: PointerProperty(type=MBakeTargetChannel)

    # Nodes
    image_node: StringProperty(default="")
    image_node_outside: StringProperty(default="")

    # UI
    expand_content: BoolProperty(default=True)
    expand_r: BoolProperty(default=False)
    expand_g: BoolProperty(default=False)
    expand_b: BoolProperty(default=False)
    expand_a: BoolProperty(default=False)


classes = [
    MBakeTargetChannel,
    MBakeTarget,
]


def register():
    """Register MBakeTarget PropertyGroups."""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister MBakeTarget PropertyGroups."""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)