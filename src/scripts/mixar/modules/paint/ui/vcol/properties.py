# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vertex color editor property groups.

This module contains the property group classes for the vertex color
editor, storing editor state and configuration.
"""

import bpy
from bpy.props import StringProperty, FloatVectorProperty, BoolProperty


class MVcolEditorProps(bpy.types.PropertyGroup):
    """Property group for vertex color editor settings."""

    color: FloatVectorProperty(
        name='Color',
        size=4,
        subtype='COLOR',
        default=(1.0, 1.0, 1.0, 1.0),
        min=0.0,
        max=1.0
    )

    show_vcol_list: BoolProperty(
        name='Show Vertex Color List',
        description='Show vertex color list',
        default=True
    )

    ori_blending_mode: StringProperty(default='')
    ori_brush: StringProperty(default='')

    ori_texpaint_blending_mode: StringProperty(default='')
    ori_texpaint_brush: StringProperty(default='')
    ori_texpaint_builtin_brush: StringProperty(default='')

    ori_sculpt_blending_mode: StringProperty(default='')
    ori_sculpt_brush: StringProperty(default='')
    ori_sculpt_tool: StringProperty(default='')
