# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Paint UV property group definitions.

This module contains the MPaintUV property group
used for UV-related settings in the paint system.
"""

import bpy
from bpy.props import StringProperty


class MPaintUV(bpy.types.PropertyGroup):
    """Property group for UV-related paint settings.

    Stores node references for UV mapping, tangent calculations,
    and parallax mapping.
    """

    name: StringProperty(default="")

    # Nodes
    uv_map: StringProperty(default="")
    tangent: StringProperty(default="")
    tangent_flip: StringProperty(default="")
    bitangent: StringProperty(default="")
    bitangent_flip: StringProperty(default="")
    tangent_process: StringProperty(default="")

    parallax_prep: StringProperty(default="")
    parallax_current_uv_mix: StringProperty(default="")
    parallax_current_uv: StringProperty(default="")
    parallax_delta_uv: StringProperty(default="")
    parallax_mix: StringProperty(default="")

    baked_parallax_current_uv_mix: StringProperty(default="")
    baked_parallax_current_uv: StringProperty(default="")
    baked_parallax_delta_uv: StringProperty(default="")
    baked_parallax_mix: StringProperty(default="")

    # For baking
    temp_tangent: StringProperty(default="")
    temp_bitangent: StringProperty(default="")


# Classes to be registered
classes = [
    MPaintUV,
]
