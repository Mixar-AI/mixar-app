# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Export Operators

Operators for UV export operations in the Mixar UV Editor.
"""

import bpy
from bpy.types import Operator

from mixar.modules.uv_editor.common.uv_utils import (
    poll_mixar_uv_edit_mode,
    with_uv_context,
    get_operator_properties,
)
from mixar.modules.common.analytics.export_events import capture_export


class MIXAR_OT_export_uv_layout(Operator):
    """Export UV layout using stored properties"""
    bl_idname = "mixar.export_uv_layout"
    bl_label = "Export UV Layout"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        # Get stored operator properties
        op_props = get_operator_properties(context, "uv.export_layout")

        with context.temp_override(area=area):
            # Invoke with stored properties to open file browser
            bpy.ops.uv.export_layout(
                'INVOKE_DEFAULT',
                mode=op_props.mode,
                size=op_props.size,
                opacity=op_props.opacity,
                export_all=op_props.export_all,
                modified=op_props.modified,
                export_tiles=op_props.export_tiles,
            )
        try:
            size = getattr(op_props, "size", ())
            capture_export(context, export_format="UV_LAYOUT", success=True, extra={
                "mode": getattr(op_props, "mode", ""),
                "size_x": int(size[0]), "size_y": int(size[1]),
                "opacity": float(getattr(op_props, "opacity", 0.0)),
                "export_all": bool(getattr(op_props, "export_all", False)),
                "modified": bool(getattr(op_props, "modified", False)),
                "export_tiles": getattr(op_props, "export_tiles", ""),
            })
        except Exception:
            pass
        return {'FINISHED'}


classes = (
    MIXAR_OT_export_uv_layout,
)
