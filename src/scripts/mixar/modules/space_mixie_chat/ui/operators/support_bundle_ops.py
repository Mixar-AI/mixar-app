# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Help -> Report a Bug and Help -> Save Support Bundle.

Report a Bug uploads the support bundle and opens the website's bug-report
form with it attached (``core/bug_report.py``); every Report a Bug entry point
(Help menu, profile menu, a failed queue job) runs this operator. Save Support
Bundle writes the same zip (``core/support_bundle.py``) to a path the user
picks, for offline or emailed reports. Menu entries:
``ui/menus/support_bundle_menu.py`` and ``startup/bl_ui/space_topbar.py``.
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


class MIXIE_CHAT_OT_report_bug(Operator):
    """Open the bug report form with this app's diagnostics attached (logs,
    scene list, app version). You can remove them on the form"""

    bl_idname = "mixie_chat.report_bug"
    bl_label = "Report a Bug"
    bl_options = {'REGISTER'}

    def execute(self, context):
        from ...core.bug_report import start_bug_report

        slog("support.report", getattr(context, "scene", None))
        if start_bug_report():
            self.report({'INFO'}, "Preparing your bug report...")
        return {'FINISHED'}


classes = (MIXIE_CHAT_OT_save_support_bundle, MIXIE_CHAT_OT_report_bug)
