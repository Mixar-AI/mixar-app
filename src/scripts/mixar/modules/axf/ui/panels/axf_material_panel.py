# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Material Properties > AxF: where an imported AxF material came from, how its model
compares with the device readings in its file, and the EEVEE fit."""

from bpy.types import Panel


def _axf_material(context):
    from mixar.modules.axf import constants as C

    mat = getattr(context, "material", None)
    return mat if mat is not None and mat.get(C.PROP_SOURCE_NAME) is not None else None


class MATERIAL_PT_mixar_axf(Panel):
    bl_label = "AxF"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return _axf_material(context) is not None

    def draw(self, context):
        from mixar.modules.axf import constants as C
        from mixar.modules.axf.core import eevee_upgrade
        from mixar.modules.axf.core.device_text import device_check, reason_text
        from mixar.modules.common.i18n import iface_

        layout = self.layout
        mat = _axf_material(context)
        col = layout.column(align=True)
        col.label(text=iface_("Source: {name}").format(name=mat[C.PROP_SOURCE_NAME]),
                  translate=False, icon='FILE')
        kept = mat.get(C.PROP_ARCHIVE) is not None
        col.label(text=iface_("Original file kept in the .blend") if kept
                  else iface_("Original file not kept"), translate=False)

        check = device_check(mat)
        if check is not None:
            box = layout.box()
            box.label(text="Model vs Device Readings", icon='DRIVER_DISTANCE')
            f = check["file"]
            box.label(text=iface_("File lobes: {mean:.2f} mean, {max:.2f} max dE00 (worst {geo})")
                      .format(mean=f["mean"], max=f["max"], geo=f["worst"]), translate=False)
            fit = check["fit"]
            if fit["requested"]:
                if fit["accepted"]:
                    box.label(text=iface_("Rendering device-fit lobes: {mean:.2f} mean, {max:.2f} max "
                                          "at unseen angles").format(mean=fit["held_out_mean"],
                                                                     max=fit["held_out_max"]),
                              translate=False, icon='CHECKMARK')
                    if fit["worse"]:
                        box.label(text=iface_("Trade-off: worse at {geos}").format(
                            geos=", ".join(fit["worse"])), translate=False)
                else:
                    box.label(text=iface_("Rendering the file's lobes: the refit was not used "
                                          "because {reason}").format(reason=reason_text(fit["reason"])),
                              translate=False)
            sub = box.column(align=True)
            sub.scale_y = 0.8
            sub.label(text=check["convention"], translate=False)

        nodes = [n for n in (mat.node_tree.nodes if mat.node_tree else [])
                 if n.bl_idname == C.NODE_IDNAME]
        if nodes and any(n.get(C.PROP_EEVEE_FIT) is None for n in nodes):
            row = layout.row()
            if eevee_upgrade.is_running():
                row.label(text="Fitting for EEVEE…", icon='SORTTIME')
            else:
                row.operator("mixie.axf_add_eevee_fit", icon='SHADING_RENDERED')


classes = (MATERIAL_PT_mixar_axf,)

