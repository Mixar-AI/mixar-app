# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pre-frame grouping PropertyGroup, kept only so old boards still load.

Nothing writes this. A ``.blend`` saved before canvas frames carries
``mixie_moodboard_groups`` plus a ``group_index`` on each image, and
``core/frame_migration.py`` converts that to real frames once, on load. The
type has to stay registered for those files to open at all, so it lives here
rather than beside the properties that are actually in use -- which also keeps
``moodboard_properties.py`` under the 500-line rule.

Registration is unchanged: ``moodboard_scene_registration`` imports it from
here instead.
"""

from bpy.props import BoolProperty, FloatVectorProperty, StringProperty
from bpy.types import PropertyGroup


class MixieMoodboardGroup(PropertyGroup):
    """Property group for moodboard image groups"""

    name: StringProperty(
        name="Name",
        description="Group name",
        default="Group",
        maxlen=64
    )
    color: FloatVectorProperty(
        name="Color",
        description="Group color",
        subtype='COLOR',
        size=4,
        default=(0.2, 0.6, 1.0, 1.0),
        min=0.0,
        max=1.0
    )
    visible: BoolProperty(
        name="Visible",
        description="Whether group is visible",
        default=True
    )
    locked: BoolProperty(
        name="Locked",
        description="Whether group is locked (cannot select children)",
        default=False
    )
    selected: BoolProperty(
        name="Selected",
        description="Whether this group is currently selected",
        default=False
    )
