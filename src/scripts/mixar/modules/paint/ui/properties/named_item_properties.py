# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Writable names for paint and bake operator search collections."""

import bpy
from bpy.props import StringProperty


class MPaintNamedItem(bpy.types.PropertyGroup):
    # Blender 5.3 makes the inherited PropertyGroup.name read-only.
    name: StringProperty(default="")


classes = (MPaintNamedItem,)
