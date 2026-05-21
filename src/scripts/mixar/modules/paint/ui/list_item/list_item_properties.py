# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty


class MListItem(bpy.types.PropertyGroup):

    name : StringProperty(default='')
    index : IntProperty(default=0)

    parent_name : StringProperty(default='')
    parent_index : IntProperty(default=-1)

    # To mark normal override
    is_second_member : BoolProperty(default=False)

    type : EnumProperty(
        name = 'Item Type',
        items = (
            ('LAYER', 'Layer', ''),
            ('CHANNEL_OVERRIDE', 'Channel Override', ''),
            ('MASK', 'Mask', '')
        ),
        default = 'LAYER'
    )

classes = (
    MListItem,
)


def register():
    """Register MListItem PropertyGroup."""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister MListItem PropertyGroup."""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)