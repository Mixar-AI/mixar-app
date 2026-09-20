# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Expose a selected viewport mesh as a connectable Moodboard node."""

import bpy
from bpy.types import Operator

from ...core.canvas_context import redraw_moodboard_canvases
from ...core.moodboard_utils import (
    ensure_moodboard_region_visible,
    get_moodboard_viewport_center,
)


def _canvas_center(context):
    """Prefer the current Zen drawer, including while it is still closed."""
    area = getattr(context, "area", None)
    workspace = getattr(context, "workspace", None)
    if (
        getattr(area, "type", None) == 'VIEW_3D'
        and getattr(workspace, "name", None) == "Zen Mode"
    ):
        for region in getattr(area, "regions", ()):
            if region.type == 'TOOL_PROPS' and getattr(region, "view2d", None):
                return region.view2d.region_to_view(
                    region.width * 0.5, region.height * 0.5
                )
    return get_moodboard_viewport_center()


class MIXIE_OT_add_selected_mesh_to_moodboard(Operator):
    """Add the active mesh to Moodboard as a connectable 3D asset node"""

    bl_idname = "mixie.add_selected_mesh_to_moodboard"
    bl_label = "Add Mesh to Moodboard"
    bl_description = (
        "Add the selected mesh to the Moodboard as a 3D node for further connections"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        if obj is None or getattr(obj, "type", None) != 'MESH':
            return False
        if getattr(obj, "mode", None) != 'OBJECT':
            return False
        try:
            return bool(obj.select_get())
        except (AttributeError, RuntimeError):
            return False

    def execute(self, context):
        from ...core.asset_nodes import create_asset_node

        obj = context.active_object
        try:
            node = create_asset_node(
                context.scene,
                obj,
                center=_canvas_center(context),
            )
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

        if (
            getattr(getattr(context, "area", None), "type", None) == 'VIEW_3D'
            and getattr(getattr(context, "workspace", None), "name", None) == "Zen Mode"
        ):
            try:
                bpy.ops.view3d.moodboard_drawer_reveal('EXEC_DEFAULT')
            except RuntimeError:
                pass

        ensure_moodboard_region_visible(
            node.position_x,
            node.position_y,
            node.width,
            node.height,
        )
        redraw_moodboard_canvases()
        if context.area:
            context.area.tag_redraw()
        self.report({'INFO'}, f"Added '{obj.name}' to the Moodboard")
        return {'FINISHED'}


def _draw_object_context_menu(self, context):
    if not MIXIE_OT_add_selected_mesh_to_moodboard.poll(context):
        return
    self.layout.operator(
        MIXIE_OT_add_selected_mesh_to_moodboard.bl_idname,
        icon='OUTLINER_OB_MESH',
    )
    self.layout.separator()


classes = (MIXIE_OT_add_selected_mesh_to_moodboard,)


def register():
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    try:
        bpy.types.VIEW3D_MT_object_context_menu.remove(_draw_object_context_menu)
    except (AttributeError, RuntimeError, ValueError):
        pass
    bpy.types.VIEW3D_MT_object_context_menu.prepend(_draw_object_context_menu)


def unregister():
    try:
        bpy.types.VIEW3D_MT_object_context_menu.remove(_draw_object_context_menu)
    except (AttributeError, RuntimeError, ValueError):
        pass
    for cls in reversed(classes):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
