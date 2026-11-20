# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Add the EEVEE fit to AxF car paints imported before it existed (no re-import)."""

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator


class MIXIE_OT_axf_add_eevee_fit(Operator):
    bl_idname = "mixie.axf_add_eevee_fit"
    bl_label = "Add EEVEE Fit"
    bl_description = (
        "Car paints imported before the EEVEE fit show a rough preview in EEVEE. Fit the "
        "measured paint for EEVEE from the material's own data, in the background. "
        "Cycles is unchanged"
    )
    bl_options = {'REGISTER'}

    all_materials: BoolProperty(
        name="All Materials",
        description="Every AxF car paint in the file instead of the active material",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        from mixar.modules.axf.core import eevee_upgrade

        if eevee_upgrade.is_running():
            cls.poll_message_set("An EEVEE fit is already running")
            return False
        return True

    def execute(self, context):
        from mixar.modules.axf.core import eevee_upgrade

        if self.all_materials:
            mats = list(bpy.data.materials)
        else:
            obj = context.active_object
            mats = [getattr(context, "material", None) or (obj.active_material if obj else None)]
        queued = eevee_upgrade.schedule(eevee_upgrade.car_paint_nodes_without_fit(mats))
        if not queued:
            self.report({'INFO'}, "Every AxF car paint already has its EEVEE fit")
            return {'CANCELLED'}
        from mixar.modules.common.i18n import rpt_

        self.report({'INFO'}, rpt_("Fitting {count} AxF car paint(s) for EEVEE in the background")
                    .format(count=queued))
        return {'FINISHED'}


classes = (MIXIE_OT_axf_add_eevee_fit,)
