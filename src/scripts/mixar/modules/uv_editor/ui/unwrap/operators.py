# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Unwrap Operator

A single dispatching operator behind the Unwrap button: routes to
`uv.unwrap` for the three classic methods, and `uv.smart_project` when
Smart UV Project is selected. Reads the values shown in the panel from
`wm.operator_properties_last(...)`.
"""

import bpy
from bpy.types import Operator

from mixar.modules.uv_editor.common.uv_utils import (
    poll_mixar_uv_edit_mode,
    with_uv_context,
    get_operator_properties,
)


_UNWRAP_METHODS = {'ANGLE_BASED', 'CONFORMAL', 'MINIMUM_STRETCH'}


class MIXAR_OT_unwrap(Operator):
    """Unwrap using the method and properties shown in the Unwrap panel"""
    bl_idname = "mixar.unwrap"
    bl_label = "Unwrap"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        wm = context.window_manager
        ui = getattr(wm, 'mixar_uv_ui', None)
        if ui is None:
            self.report({'ERROR'}, "Mixar UV UI state not initialized")
            return {'CANCELLED'}

        method = ui.unwrap_method

        if method == 'SMART_PROJECT':
            p = get_operator_properties(context, "uv.smart_project")
            with context.temp_override(area=area):
                bpy.ops.uv.smart_project(
                    'EXEC_DEFAULT',
                    angle_limit=p.angle_limit,
                    margin_method=p.margin_method,
                    rotate_method=p.rotate_method,
                    island_margin=p.island_margin,
                    area_weight=p.area_weight,
                    correct_aspect=p.correct_aspect,
                    scale_to_bounds=p.scale_to_bounds,
                )
            return {'FINISHED'}

        if method not in _UNWRAP_METHODS:
            self.report({'ERROR'}, f"Unknown unwrap method: {method}")
            return {'CANCELLED'}

        p = get_operator_properties(context, "uv.unwrap")
        kwargs = dict(
            method=method,
            fill_holes=p.fill_holes,
            correct_aspect=p.correct_aspect,
            use_subsurf_data=p.use_subsurf_data,
            margin_method=p.margin_method,
            margin=p.margin,
        )
        if method == 'MINIMUM_STRETCH':
            kwargs.update(
                iterations=p.iterations,
                no_flip=p.no_flip,
                use_weights=p.use_weights,
                weight_group=p.weight_group,
                weight_factor=p.weight_factor,
            )

        with context.temp_override(area=area):
            bpy.ops.uv.unwrap('EXEC_DEFAULT', **kwargs)
        return {'FINISHED'}


classes = (
    MIXAR_OT_unwrap,
)
