# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Help → Export Diagnostics. Writes a JSON support dump, never secrets."""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

from mixar.modules.common.core.diagnostics import diagnostics_text


class MIXAR_OT_export_diagnostics(Operator, ExportHelper):
    """Save a Mixar support dump (version, catalog, queue — no secrets)."""

    bl_idname = "mixar.export_diagnostics"
    bl_label = "Export Diagnostics"
    bl_description = (
        "Save a JSON support dump: Mixar/Blender versions, OS, catalog "
        "version, and queue state. Prompts, files, and tokens are never included"
    )
    bl_options = {"REGISTER"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
    filepath: StringProperty(subtype="FILE_PATH")

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = "mixar-diagnostics.json"
        return super().invoke(context, event)

    def execute(self, context):
        path = bpy.path.abspath(self.filepath)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(diagnostics_text())
                handle.write("\n")
        except OSError as error:
            self.report({"ERROR"}, f"Could not write diagnostics: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Saved diagnostics to {path}")
        return {"FINISHED"}


classes = (MIXAR_OT_export_diagnostics,)
