# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""File → Export → "Mixar: Save support bundle…".

Zips the client log file, the ``[SCENES]`` dossiers, the turn-checkpoint
indexes and a dump of the live scene table (``core/support_bundle.py``) to
a user-picked path, for a bug report about scene tabs or the agent. The
bundle never contains a filesystem path other than its own manifest.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

from mixar.config.logging_config import get_logger
from mixar.modules.common.scenes_log import slog

from ...core.support_bundle import build_support_bundle

logger = get_logger(__name__)


class MIXIE_CHAT_OT_save_support_bundle(Operator, ExportHelper):
    """Save a zip of the Mixar client logs, scene ledgers and checkpoint
    indexes for a bug report (no scene data, no file paths)."""

    bl_idname = "mixie_chat.save_support_bundle"
    bl_label = "Save Mixar support bundle"
    bl_options = {'REGISTER'}

    filename_ext = ".zip"
    filter_glob: StringProperty(default="*.zip", options={'HIDDEN'})

    def invoke(self, context, event):
        import time
        self.filepath = time.strftime("mixar-support-%Y%m%d-%H%M%S.zip")
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        # The bundle records the moment it was asked for, as a [SCENES] line
        # in the log it is about to ship.
        slog("support.bundle", getattr(context, "scene", None))
        try:
            manifest = build_support_bundle(self.filepath)
        except Exception as error:  # noqa: BLE001
            logger.error("support bundle failed: %s", error, exc_info=True)
            self.report({'ERROR'}, f"Support bundle failed: {error}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Support bundle saved ({len(manifest['files'])} file(s))")
        return {'FINISHED'}


def _menu_func_export(self, context):
    self.layout.operator(
        MIXIE_CHAT_OT_save_support_bundle.bl_idname,
        text="Mixar: Save support bundle (.zip)",
        icon='HELP',
    )


classes = (MIXIE_CHAT_OT_save_support_bundle,)

_menu_registered = False


def register():
    global _menu_registered
    for cls in classes:
        bpy.utils.register_class(cls)
    if not _menu_registered:
        bpy.types.TOPBAR_MT_file_export.append(_menu_func_export)
        _menu_registered = True


def unregister():
    global _menu_registered
    if _menu_registered:
        try:
            bpy.types.TOPBAR_MT_file_export.remove(_menu_func_export)
        except Exception:  # noqa: BLE001
            pass
        _menu_registered = False
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:  # noqa: BLE001
            pass
