# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operator: build a layered material from a manifest JSON string."""

import json

import bpy
from bpy.props import StringProperty

from ...layered_build.builder import build_layered_material
from mixar.modules.common.i18n import rpt_


class LAYERS_OT_BuildLayeredMaterial(bpy.types.Operator):
    bl_idname = "paint.build_layered_material"
    bl_label = "Build Layered Material"
    bl_description = "Build a Mixar paint material from a layered-material manifest"
    bl_options = {'REGISTER', 'UNDO'}

    manifest_json: StringProperty(name="Manifest JSON", default="")

    def execute(self, context):
        if not self.manifest_json:
            self.report({'ERROR'}, "manifest_json is empty")
            return {'CANCELLED'}
        try:
            manifest = json.loads(self.manifest_json)
        except json.JSONDecodeError as e:
            self.report({'ERROR'}, rpt_("Invalid manifest JSON: {error}").format(error=e))
            return {'CANCELLED'}
        try:
            result = build_layered_material(manifest, context.view_layer.objects.active)
        except Exception as e:
            self.report({'ERROR'}, rpt_("Build failed: {error}").format(error=e))
            return {'CANCELLED'}
        self.report({'INFO'}, rpt_("Built {count} layer(s)").format(count=result['layers_built']))
        print("\n__RESULT__" + json.dumps({"success": True, **result}))
        return {'FINISHED'}


# Classes for registration
classes = (LAYERS_OT_BuildLayeredMaterial,)
