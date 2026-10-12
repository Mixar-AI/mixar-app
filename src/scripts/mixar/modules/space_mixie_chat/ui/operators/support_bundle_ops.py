# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Help -> Save Support Bundle.

Zips the client log files, the ``[SCENES]`` dossiers, the turn-checkpoint
indexes and the scene table (``core/support_bundle.py``) to a path the user
picks, for attaching to a bug report. The Help menu entry is
``ui/menus/support_bundle_menu.py``.
"""

import time

from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import rpt_
from mixar.modules.common.scenes_log import slog

from ...core.support_bundle import build_support_bundle

logger = get_logger(__name__)


class MIXIE_CHAT_OT_save_support_bundle(Operator, ExportHelper):
    """Save a zip of Mixar's logs, scene ledgers and checkpoint indexes to
    attach to a bug report (no scene geometry, images or chat transcripts)"""

    bl_idname = "mixie_chat.save_support_bundle"
    bl_label = "Save Support Bundle"
    bl_options = {'REGISTER'}

    filename_ext = ".zip"
    filter_glob: StringProperty(default="*.zip", options={'HIDDEN'})

    def invoke(self, context, event):
        self.filepath = time.strftime("mixar-support-%Y%m%d-%H%M%S.zip")
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        # Mark the moment in the log the bundle is about to ship.
        slog("support.bundle", getattr(context, "scene", None))
        try:
            manifest = build_support_bundle(self.filepath)
        except Exception as error:  # noqa: BLE001
            logger.error("support bundle failed: %s", error, exc_info=True)
            self.report({'ERROR'}, rpt_("Support bundle failed: {error}").format(error=error))
            return {'CANCELLED'}
        self.report({'INFO'}, rpt_("Support bundle saved ({count} file(s))").format(
            count=len(manifest["files"])))
        return {'FINISHED'}


classes = (MIXIE_CHAT_OT_save_support_bundle,)
