# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dispatcher operator for the Asset Export tab.

Routes to the correct format-specific file-browser operator
(glTF / OBJ / FBX) based on the currently selected tab.
"""

import bpy

from .export_utils import export_poll


class MExportAsset(bpy.types.Operator):
    """Dispatch to the format-specific export file browser"""

    bl_idname = "wm.m_export_asset"
    bl_label = "Export Asset"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return export_poll(context)

    def execute(self, context):
        wm = context.window_manager
        s = getattr(wm, 'mixar_asset_export', None)
        if not s:
            self.report({'ERROR'}, "Asset export settings not found")
            return {'CANCELLED'}

        tab = s.tab
        if tab == 'GLTF':
            return bpy.ops.wm.m_export_gltf('INVOKE_DEFAULT')
        if tab == 'OBJ':
            return bpy.ops.wm.m_export_obj('INVOKE_DEFAULT')
        if tab == 'FBX':
            return bpy.ops.wm.m_export_fbx('INVOKE_DEFAULT')

        self.report({'ERROR'}, f"Unknown export format: {tab}")
        return {'CANCELLED'}


classes = (MExportAsset,)
