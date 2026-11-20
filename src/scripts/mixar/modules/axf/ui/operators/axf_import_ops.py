# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""File > Import / Export for X-Rite AxF materials (car paints and SVBRDFs).

Agent-drivable: ``bpy.ops.mixie.import_axf(filepath=...)`` imports without a
file browser and assigns the material to the selected meshes.
"""

import os

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _import_message(mat, archive_source: bool) -> str:
    """One line: what was imported, whether the scan was kept, and the device check."""
    from mixar.modules.axf.core.device_text import device_check, reason_text
    from mixar.modules.common.i18n import rpt_

    kept = rpt_("original .axf kept in the .blend") if archive_source else rpt_("original .axf not kept")
    msg = rpt_("Imported {name} ({kept})").format(name=mat.name, kept=kept)
    check = device_check(mat)
    if check is None:
        return msg
    msg += rpt_("; file vs device {mean:.2f} / {max:.2f} dE00").format(
        mean=check["file"]["mean"], max=check["file"]["max"])
    fit = check["fit"]
    if fit["requested"]:
        if fit["accepted"]:
            msg += rpt_("; lobes fit to device (unseen angles {mean:.2f} / {max:.2f})").format(
                mean=fit["held_out_mean"], max=fit["held_out_max"])
        else:
            msg += rpt_("; file lobes kept: {reason}").format(reason=reason_text(fit["reason"]))
    return msg


class MIXIE_OT_import_axf(Operator, ImportHelper):
    bl_idname = "mixie.import_axf"
    bl_label = "Import AxF Material"
    bl_description = (
        "Import an X-Rite AxF material (car paint or SVBRDF) that renders the measured "
        "data exactly in Cycles"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".axf"
    filter_glob: StringProperty(default="*.axf", options={'HIDDEN'})
    archive_source: BoolProperty(
        name="Keep Original File",
        description=(
            "Pack the original .axf into the .blend so it can be exported unchanged. The scan "
            "then travels with every copy of the .blend. Off: renders the same, cannot be "
            "exported back to .axf"
        ),
        default=True,
    )
    fit_to_device: BoolProperty(
        name="Fit Lobes to Device",
        description=(
            "Car paints with device readings in the file: refit the specular lobes to those "
            "readings and render the refit when it predicts unseen angles better than the "
            "file's own lobes. Off: render the file as stored. Export always writes the "
            "original file"
        ),
        default=False,
    )
    assign: BoolProperty(
        name="Assign to Selected",
        description="Assign the material to the selected meshes",
        default=True,
    )

    def execute(self, context):
        from mixar.modules.axf.core.blender_import import import_axf
        from mixar.modules.axf.core.cpa2_reader import AxfFormatError

        try:
            mat = import_axf(self.filepath, archive_source=self.archive_source,
                             fit_to_device=self.fit_to_device)
        except AxfFormatError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except Exception as e:  # noqa: BLE001 - surfaced to the user below
            logger.exception("[AxF] import of %s failed", os.path.basename(self.filepath))
            self.report({'ERROR'}, f"AxF import failed: {e}")
            return {'CANCELLED'}

        if self.assign:
            for obj in context.selected_objects:
                if obj.type == 'MESH':
                    if obj.data.materials:
                        obj.data.materials[0] = mat
                    else:
                        obj.data.materials.append(mat)
        self.report({'INFO'}, _import_message(mat, self.archive_source))
        return {'FINISHED'}


class MIXIE_OT_export_axf(Operator, ExportHelper):
    bl_idname = "mixie.export_axf"
    bl_label = "Export AxF Material"
    bl_description = "Write the active material's original AxF file back out, byte for byte"

    filename_ext = ".axf"
    filter_glob: StringProperty(default="*.axf", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        from mixar.modules.axf import constants as C

        obj = context.active_object
        mat = obj.active_material if obj else None
        if mat is None or mat.get(C.PROP_SOURCE_NAME) is None:
            cls.poll_message_set("The active material is not an imported AxF material")
            return False
        if mat.get(C.PROP_ARCHIVE) is None:
            cls.poll_message_set(
                "This material's original .axf is not in the file; re-import the .axf to export it")
            return False
        return True

    def execute(self, context):
        from mixar.modules.axf.core.blender_import import export_axf

        mat = context.active_object.active_material
        try:
            digest = export_axf(mat, self.filepath)
        except Exception as e:  # noqa: BLE001 - surfaced to the user below
            logger.exception("[AxF] export of %s failed", mat.name)
            self.report({'ERROR'}, f"AxF export failed: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Exported {os.path.basename(self.filepath)} (sha256 {digest[:12]})")
        return {'FINISHED'}


class MIXIE_OT_remove_axf_sources(Operator):
    bl_idname = "mixie.remove_axf_sources"
    bl_label = "Remove Embedded AxF Originals"
    bl_description = (
        "Delete the original .axf scans packed into this .blend (for example before sharing "
        "it). AxF materials keep rendering exactly; they can no longer be exported to .axf"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from mixar.modules.axf.core.blender_import import archived_sources

        if not archived_sources():
            cls.poll_message_set("This file holds no original .axf scans")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Remove embedded AxF originals?",
            message="AxF materials keep rendering; exporting them to .axf will need a re-import.",
            confirm_text="Remove")

    def execute(self, context):
        from mixar.modules.axf.core.blender_import import remove_archived_sources

        n = remove_archived_sources()
        self.report({'INFO'}, f"Removed {n} embedded .axf file{'s' if n != 1 else ''}; save to make it permanent")
        return {'FINISHED'}


def _menu_import(self, context):
    self.layout.operator(MIXIE_OT_import_axf.bl_idname, text="X-Rite AxF Material (.axf)")


def _menu_export(self, context):
    self.layout.operator(MIXIE_OT_export_axf.bl_idname, text="X-Rite AxF Material (.axf)")


def _menu_cleanup(self, context):
    self.layout.separator()
    self.layout.operator(MIXIE_OT_remove_axf_sources.bl_idname)


classes = (MIXIE_OT_import_axf, MIXIE_OT_export_axf, MIXIE_OT_remove_axf_sources)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)
    bpy.types.TOPBAR_MT_file_cleanup.append(_menu_cleanup)


def unregister():
    bpy.types.TOPBAR_MT_file_cleanup.remove(_menu_cleanup)
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
