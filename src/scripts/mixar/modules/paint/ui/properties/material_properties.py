# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Paint material property group definitions.

This module contains the MPaintMaterialProps property group
used for material-level paint settings.
"""

import bpy
from bpy.props import IntProperty, StringProperty


class MPaintMaterialProps(bpy.types.PropertyGroup):
    """Property group for material-level paint settings.

    Stores references to original BSDF and active paint node for materials.
    """

    ori_bsdf: StringProperty(default="")
    ori_bsdf_output_index: IntProperty(default=0)
    active_mpaint_node: StringProperty(default="")


# Classes to be registered
classes = [
    MPaintMaterialProps,
]
