# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Expose a selected viewport mesh as a connectable Moodboard node."""

import bpy
from bpy.types import Operator

from ...core.canvas_context import redraw_moodboard_canvases
from ...core.asset_nodes import add_mesh_references, selected_mesh_objects
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
    """Add selected meshes as live, connectable 3D references"""

    bl_idname = "mixie.add_selected_mesh_to_moodboard"
    bl_label = "Add Mesh to Moodboard"
    bl_description = (
        "Add selected meshes as 3D nodes, or reveal their existing Moodboard references"
    )
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        if not selected_mesh_objects(context):
            cls.poll_message_set("Select a mesh in Object Mode")
            return False
        return True

    def execute(self, context):
        objects = selected_mesh_objects(context)
        before = len(context.scene.mixie_moodboard_asset_nodes)
        try:
            nodes = add_mesh_references(context.scene, objects,
                                        center=_canvas_center(context),
                                        active=context.active_object)
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

        left = min(node.position_x for node in nodes)
        bottom = min(node.position_y for node in nodes)
        right = max(node.position_x + node.width for node in nodes)
        top = max(node.position_y + node.height for node in nodes)
        ensure_moodboard_region_visible(left, bottom, right-left, top-bottom)
        redraw_moodboard_canvases()
        if context.area:
            context.area.tag_redraw()
        added = len(context.scene.mixie_moodboard_asset_nodes) - before
        self.report({'INFO'}, f"Added {added} mesh reference(s); selected {len(nodes)} on the Moodboard")
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
