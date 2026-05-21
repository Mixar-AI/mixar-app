# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""OBJ export settings PropertyGroup.

Property names match WM_OT_obj_export exactly so that our manual draw
functions mirror the C++ panels.
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
)
from bpy.types import PropertyGroup


class MObjExportSettings(PropertyGroup):
    """OBJ export settings with names matching WM_OT_obj_export."""

    # ---- General ----
    export_selected_objects: BoolProperty(
        name='Export Selected Objects', default=False,
    )
    global_scale: FloatProperty(
        name='Scale', default=1.0, min=0.0001, max=10000.0,
    )
    forward_axis: EnumProperty(
        name='Forward Axis',
        items=(
            ('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", ""),
            ('NEGATIVE_X', "-X", ""), ('NEGATIVE_Y', "-Y", ""),
            ('NEGATIVE_Z', "-Z", ""),
        ),
        default='NEGATIVE_Z',
    )
    up_axis: EnumProperty(
        name='Up Axis',
        items=(
            ('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", ""),
            ('NEGATIVE_X', "-X", ""), ('NEGATIVE_Y', "-Y", ""),
            ('NEGATIVE_Z', "-Z", ""),
        ),
        default='Y',
    )

    # ---- Geometry ----
    export_uv: BoolProperty(name='UV Coordinates', default=True)
    export_normals: BoolProperty(name='Normals', default=True)
    export_colors: BoolProperty(name='Vertex Colors', default=False)
    export_curves_as_nurbs: BoolProperty(
        name='Export Curves as NURBS', default=False,
    )
    export_triangulated_mesh: BoolProperty(
        name='Triangulated Mesh', default=False,
    )
    apply_modifiers: BoolProperty(name='Apply Modifiers', default=True)
    apply_transform: BoolProperty(name='Apply Transform', default=True)
    export_eval_mode: EnumProperty(
        name='Object Properties',
        items=(
            ('DAG_EVAL_RENDER', "Render", "Use render properties"),
            ('DAG_EVAL_VIEWPORT', "Viewport", "Use viewport properties"),
        ),
        default='DAG_EVAL_VIEWPORT',
    )

    # ---- Grouping ----
    export_object_groups: BoolProperty(
        name='Export Object Groups', default=False,
    )
    export_material_groups: BoolProperty(
        name='Export Material Groups', default=False,
    )
    export_vertex_groups: BoolProperty(
        name='Export Vertex Groups', default=False,
    )
    export_smooth_groups: BoolProperty(
        name='Smooth Groups', default=False,
    )
    smooth_group_bitflags: BoolProperty(
        name='Bitflags Smooth Groups', default=False,
    )

    # ---- Materials ----
    export_materials: BoolProperty(name='Export Materials', default=True)
    export_pbr_extensions: BoolProperty(
        name='PBR Extensions', default=False,
    )
    path_mode: EnumProperty(
        name='Path Mode',
        items=(
            ('AUTO', "Auto", "Use relative paths with subdirectories only"),
            ('ABSOLUTE', "Absolute", "Always write absolute paths"),
            ('RELATIVE', "Relative", "Always write relative paths"),
            ('MATCH', "Match", "Match the original path reference mode"),
            ('STRIP', "Strip Path", "Only write the filename"),
            ('COPY', "Copy", "Copy the file to the destination path"),
        ),
        default='AUTO',
    )

    # ---- Animation ----
    export_animation: BoolProperty(
        name='Export Animation', default=False,
    )
    start_frame: IntProperty(
        name='Start Frame', default=-2147483648,
    )
    end_frame: IntProperty(
        name='End Frame', default=2147483647,
    )


def register():
    bpy.utils.register_class(MObjExportSettings)
    bpy.types.WindowManager.mixar_export_obj = bpy.props.PointerProperty(
        type=MObjExportSettings,
    )


def unregister():
    if hasattr(bpy.types.WindowManager, 'mixar_export_obj'):
        del bpy.types.WindowManager.mixar_export_obj
    bpy.utils.unregister_class(MObjExportSettings)
