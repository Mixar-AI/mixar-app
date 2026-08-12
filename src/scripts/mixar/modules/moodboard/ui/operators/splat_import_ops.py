# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""File > Import operator for local Gaussian splats (.spz / 3DGS .ply).

Agent-drivable: ``bpy.ops.mixie.import_splat(filepath=...)`` imports without
a file browser. Multi-select in the browser imports each file into its own
``Splat_*`` collection.
"""

import os

import bpy
from bpy.props import BoolProperty, CollectionProperty, StringProperty
from bpy.types import Operator, OperatorFileListElement
from bpy_extras.io_utils import ImportHelper

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MIXIE_OT_import_splat(Operator, ImportHelper):
    bl_idname = "mixie.import_splat"
    bl_label = "Import Gaussian Splat"
    bl_description = (
        "Import a Gaussian splat (.spz or 3DGS .ply) as a real-time splat "
        "environment"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".spz"
    filter_glob: StringProperty(default="*.spz;*.ply", options={'HIDDEN'})
    files: CollectionProperty(
        type=OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'},
    )
    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    recenter: BoolProperty(
        name="Ground at Origin",
        description=(
            "Move the splat so its floor sits on Z=0 with its footprint "
            "centre at the origin (same grounding as generated worlds)"
        ),
        default=True,
    )

    def execute(self, context):
        from mixar.modules.moodboard.core.splat_import import import_splat_file

        paths = [
            os.path.join(self.directory, f.name)
            for f in self.files if f.name
        ]
        if not paths and self.filepath:
            paths = [self.filepath]
        if not paths:
            self.report({'ERROR'}, "No splat file selected")
            return {'CANCELLED'}

        imported, errors = [], []
        for path in paths:
            try:
                imported += import_splat_file(path, recenter=self.recenter)
            except Exception as e:  # noqa: BLE001 - surfaced to the user below
                logger.error("[SplatImport] %s failed: %s", path, e)
                errors.append(f"{os.path.basename(path)}: {e}")

        if errors:
            self.report(
                {'ERROR'} if not imported else {'WARNING'},
                "; ".join(errors)[:256],
            )
        if not imported:
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Imported {len(paths) - len(errors)} splat(s): "
            f"{', '.join(imported[:4])}{'…' if len(imported) > 4 else ''}",
        )
        return {'FINISHED'}


def _menu_import(self, context):
    self.layout.operator(
        MIXIE_OT_import_splat.bl_idname, text="Gaussian Splat (.spz/.ply)",
    )


classes = (MIXIE_OT_import_splat,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
