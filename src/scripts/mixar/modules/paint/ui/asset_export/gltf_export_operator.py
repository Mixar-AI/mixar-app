# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""glTF file-browser export operator.

Opens Blender's native file browser with the glTF export panels drawn
from the shared MGltfExportSettings PropertyGroup.
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


def _capture_gltf_export(context, settings, success, filepath):
    try:
        selected_only = bool(getattr(settings, "use_selection", False))
        capture_export(
            context, export_format="GLTF", success=success, filepath=filepath,
            extra={
                **normalized_settings("GLTF", settings),
                **scene_counts(context, selected_only=selected_only),
            })
    except Exception:
        pass

# Properties that should not be forwarded to the native export operator.
_EXCLUDE = {
    'will_save_settings',
    'export_keep_originals',
    'export_texture_dir',
}


class MExportGltf(bpy.types.Operator):
    """Open a file browser and export the mesh as glTF/GLB"""

    bl_idname = "wm.m_export_gltf"
    bl_label = "Export glTF"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.glb;*.gltf", options={'HIDDEN'})

    # Store the object name so we can revert after the modal file browser.
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

        # Default filename based on object name and format.
        gs = context.window_manager.mixar_export_gltf
        ext = ".glb" if gs.export_format == 'GLB' else ".gltf"
        self.filepath = obj.name + ext

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        gs = context.window_manager.mixar_export_gltf
        try:
            from io_scene_gltf2 import (
                export_main,
                export_panel_include,
                export_panel_transform,
                export_panel_data,
                export_panel_animation,
            )
            export_main(layout, gs, True)
            export_panel_include(layout, gs, True)
            export_panel_transform(layout, gs)
            export_panel_data(layout, gs)
            export_panel_animation(layout, gs)
        except ImportError:
            layout.label(text="glTF add-on not available", icon='ERROR')

    def execute(self, context):
        gs = context.window_manager.mixar_export_gltf
        kwargs = settings_to_kwargs(gs, exclude=_EXCLUDE)

        try:
            bpy.ops.export_scene.gltf(filepath=self.filepath, **kwargs)
        except Exception as e:
            logger.error("glTF export failed: %s", e)
            self.report({'ERROR'}, f"Export failed: {e}")
            self._revert(context)
            _capture_gltf_export(context, gs, False, self.filepath)
            return {'CANCELLED'}

        self._revert(context)
        self.report({'INFO'}, f"Exported glTF to {self.filepath}")
        _capture_gltf_export(context, gs, True, self.filepath)
        return {'FINISHED'}

    def cancel(self, context):
        self._revert(context)

    def _revert(self, context):
        obj = bpy.data.objects.get(self._obj_name)
        if obj:
            revert_to_original_material(obj)


classes = (MExportGltf,)
