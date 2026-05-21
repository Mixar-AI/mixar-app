# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Decal object properties for Mixar paint system.

This module contains the MPaintDecalObjectProps PropertyGroup which is
registered on bpy.types.Object to provide shrinkwrap constraint functionality
for decal empty objects.
"""

import bpy
from bpy.props import BoolProperty, StringProperty


def get_decal_shrinkwrap_constraint(decal_obj):
    """Get the shrinkwrap constraint on a decal object.

    Args:
        decal_obj: The decal empty object.

    Returns:
        bpy.types.Constraint: The shrinkwrap constraint, or None if not found.
    """
    if not decal_obj or not hasattr(decal_obj, 'constraints'):
        return None
    cs = [c for c in decal_obj.constraints if c.type == 'SHRINKWRAP']
    if len(cs) > 0:
        return cs[0]
    return None


def update_enable_decal_shrinkwrap(self, context):
    """Update callback when shrinkwrap is toggled.

    Creates or removes a shrinkwrap constraint on the decal empty object.

    Args:
        self: The MPaintDecalObjectProps instance.
        context: Blender context.
    """
    obj = context.object
    decal_obj = self.id_data
    decal_const = get_decal_shrinkwrap_constraint(decal_obj)

    if self.enable_shrinkwrap:
        if not decal_const and obj:
            c = decal_obj.constraints.new('SHRINKWRAP')
            c.target = obj
            c.use_track_normal = True
            c.track_axis = 'TRACK_Z'
    else:
        if decal_const:
            decal_obj.constraints.remove(decal_const)


class MPaintDecalObjectProps(bpy.types.PropertyGroup):
    """Property group for decal empty object settings.

    Attached to bpy.types.Object as 'mp_decal' to provide shrinkwrap
    constraint functionality for decal projections.
    """

    enable_shrinkwrap: BoolProperty(
        name='Enable Decal Shrinkwrap Constraint',
        description='Keep decal stuck to mesh surface during transforms',
        default=False,
        update=update_enable_decal_shrinkwrap,
    )

    # Used by depsgraph handler to detect transform operations
    last_operator: StringProperty(
        name='Last Operator',
        default='',
    )

    last_operator_pointer: StringProperty(
        name='Last Operator Pointer',
        default='',
    )


# Classes for registration
classes = (
    MPaintDecalObjectProps,
)
