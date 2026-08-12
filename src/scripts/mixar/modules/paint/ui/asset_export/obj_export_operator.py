# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""OBJ file-browser export operator.

Opens Blender's native file browser with manually recreated OBJ export
panels (the native OBJ draw is in C++ and cannot be reused directly).
"""

import bpy
from bpy.props import StringProperty

from mixar.config.logging_config import get_logger
from ...core.node.node_utils import get_active_mpaint_node
from ...core.asset_export.bake_and_assign import create_export_material
from ...core.asset_export.revert_material import revert_to_original_material
from .export_utils import export_poll, settings_to_kwargs
from mixar.modules.common.analytics.export_events import (
    capture_export,
    normalized_settings,
    scene_counts,
)

logger = get_logger(__name__)


def _capture_obj_export(context, settings, success, filepath):
    try:
        selected_only = bool(getattr(settings, "export_selected_objects", False))
        capture_export(
            context, export_format="OBJ", success=success, filepath=filepath,
            extra={
                **normalized_settings("OBJ", settings),
                **scene_counts(context, selected_only=selected_only),
            })
    except Exception:
        pass


def draw_obj_export_panels(layout, s, is_file_browser=True):
    """Manually recreate the 5 OBJ export C++ panels.

    Mirrors ``ui_obj_export_settings()`` from ``io_obj.cc``.
    """
    # ---- General ----
    header, body = layout.panel("OBJ_export_general", default_closed=False)
    header.label(text="General")
    if body:
        if is_file_browser:
            body.prop(s, "export_selected_objects")
        body.prop(s, "global_scale")
        body.prop(s, "forward_axis")
        body.prop(s, "up_axis")

    # ---- Geometry ----
    header, body = layout.panel("OBJ_export_geometry", default_closed=False)
    header.label(text="Geometry")
    if body:
        body.prop(s, "export_uv")
        body.prop(s, "export_normals")
        body.prop(s, "export_colors")
        body.prop(s, "export_curves_as_nurbs")
        body.prop(s, "export_triangulated_mesh")
        body.prop(s, "apply_modifiers")
        body.prop(s, "apply_transform")
        body.prop(s, "export_eval_mode")

    # ---- Grouping ----
    header, body = layout.panel("OBJ_export_grouping", default_closed=True)
    header.label(text="Grouping")
    if body:
        body.prop(s, "export_object_groups")
        body.prop(s, "export_material_groups")
        body.prop(s, "export_vertex_groups")
        body.prop(s, "export_smooth_groups")
        sub = body.row()
        sub.enabled = s.export_smooth_groups
        sub.prop(s, "smooth_group_bitflags")

    # ---- Materials ----
    header, body = layout.panel("OBJ_export_materials", default_closed=False)
    header.use_property_split = False
    header.prop(s, "export_materials", text="")
    header.label(text="Materials")
    if body:
        body.enabled = s.export_materials
        body.prop(s, "export_pbr_extensions")
        body.prop(s, "path_mode")

    # ---- Animation ----
    header, body = layout.panel("OBJ_export_animation", default_closed=True)
    header.use_property_split = False
    header.prop(s, "export_animation", text="")
    header.label(text="Animation")
    if body:
        body.enabled = s.export_animation
        body.prop(s, "start_frame")
        body.prop(s, "end_frame")


class MExportObj(bpy.types.Operator):
    """Open a file browser and export the mesh as OBJ"""

    bl_idname = "wm.m_export_obj"
    bl_label = "Export OBJ"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.obj", options={'HIDDEN'})

    _obj_name: str = ""

    @classmethod
    def poll(cls, context):
        return export_poll(context)

    def invoke(self, context, event):
        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp
        obj = context.active_object

        mat = create_export_material(obj, mp, tree)
        if not mat:
            self.report({'ERROR'}, "Failed to create export material")
            return {'CANCELLED'}

        self._obj_name = obj.name
        self.filepath = obj.name + ".obj"

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        os = context.window_manager.mixar_export_obj
        draw_obj_export_panels(layout, os, is_file_browser=True)

    def execute(self, context):
        os = context.window_manager.mixar_export_obj
        kwargs = settings_to_kwargs(os)

        try:
            bpy.ops.wm.obj_export(filepath=self.filepath, **kwargs)
        except Exception as e:
            logger.error("OBJ export failed: %s", e)
            self.report({'ERROR'}, f"Export failed: {e}")
            self._revert(context)
            _capture_obj_export(context, os, False, self.filepath)
            return {'CANCELLED'}

        self._revert(context)
        self.report({'INFO'}, f"Exported OBJ to {self.filepath}")
        _capture_obj_export(context, os, True, self.filepath)
        return {'FINISHED'}

    def cancel(self, context):
        self._revert(context)

    def _revert(self, context):
        obj = bpy.data.objects.get(self._obj_name)
        if obj:
            revert_to_original_material(obj)


classes = (MExportObj,)
