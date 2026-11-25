# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Place an AxF car paint's flakes and clear coat map by a UV map or by box projection."""

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator


class MIXIE_OT_axf_flake_mapping(Operator):
    bl_idname = "mixie.axf_flake_mapping"
    bl_label = "AxF Flake Mapping"
    bl_description = (
        "Place the car paint's flakes and clear coat texture along the object's UV map, which "
        "follows curved panels and has seams only where the UV map is cut, or back on the box "
        "projection used at import. Flakes keep their measured size"
    )
    bl_options = {'REGISTER', 'UNDO'}

    mapping: EnumProperty(
        name="Mapping",
        items=(
            ('UV', "UV Map", "Along the active object's UV map, scaled to the measured flake size"),
            ('BOX', "Box Projection", "Projected from the dominant axis of the object's surface"),
        ),
        default='UV',
    )
    uv_map: StringProperty(
        name="UV Map",
        description="UV map to use (empty: the active object's active render UV map)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        from mixar.modules.axf.core import flake_mapping

        obj = context.active_object
        mat = getattr(context, "material", None) or (obj.active_material if obj else None)
        if not flake_mapping.has_mapping(mat):
            cls.poll_message_set("The active material is not an AxF car paint with flakes")
            return False
        return True

    def execute(self, context):
        from mixar.modules.axf.core import flake_mapping
        from mixar.modules.common.i18n import rpt_

        obj = context.active_object
        mat = getattr(context, "material", None) or (obj.active_material if obj else None)
        if self.mapping == 'BOX':
            flake_mapping.set_mapping(mat, flake_mapping.MAPPING_BOX)
            self.report({'INFO'}, "AxF flakes placed by box projection")
            return {'FINISHED'}

        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Select the mesh whose UV map should carry the flakes")
            return {'CANCELLED'}
        uv_name = self.uv_map
        if not uv_name:
            active = next((uv for uv in obj.data.uv_layers if uv.active_render), None)
            uv_name = active.name if active else ""
        if not uv_name or obj.data.uv_layers.get(uv_name) is None:
            self.report({'ERROR'}, "The object has no UV map. Unwrap it first")
            return {'CANCELLED'}
        su, sv = flake_mapping.object_uv_scale(obj, context.evaluated_depsgraph_get(), uv_name)
        if su <= 0.0 or sv <= 0.0:
            self.report({'ERROR'}, "The UV map has no area. Unwrap the object first")
            return {'CANCELLED'}
        flake_mapping.set_mapping(mat, flake_mapping.MAPPING_UV, uv_name=uv_name, metres=(su, sv))
        self.report({'INFO'}, rpt_("AxF flakes placed along UV map {uv} ({u:.0f} x {v:.0f} mm per UV unit)")
                    .format(uv=uv_name, u=su * 1000.0, v=sv * 1000.0))
        return {'FINISHED'}


classes = (MIXIE_OT_axf_flake_mapping,)
