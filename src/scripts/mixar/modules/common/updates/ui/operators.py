# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Auto-Update Operators

Blender operators for installing, dismissing, and viewing changelogs
for available updates.  Auto-registered by bootstrap via the ``classes``
tuple at module level.
"""

import webbrowser

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MIXAR_OT_install_update(bpy.types.Operator):
    """Launch the downloaded installer and quit Mixar"""

    bl_idname = "mixar.install_update"
    bl_label = "Install Update"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..core.installer import launch_installer
        from ..core.state import get_update_state
        from ..constants import UPDATE_NOTIFICATION_ID
        from ...notifications.store import get_notification_store

        state = get_update_state()
        path = state.downloaded_path

        if not path:
            self.report({"WARNING"}, "No downloaded installer available")
            return {"CANCELLED"}

        state.set_installing()
        get_notification_store().dismiss(UPDATE_NOTIFICATION_ID)

        if launch_installer(path, quit_blender=True):
            return {"FINISHED"}

        state.set_error("Failed to launch installer")
        self.report({"ERROR"}, "Failed to launch installer")
        return {"CANCELLED"}


class MIXAR_OT_dismiss_update(bpy.types.Operator):
    """Skip this version and dismiss the notification"""

    bl_idname = "mixar.dismiss_update"
    bl_label = "Skip This Version"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..core.state import get_update_state
        from ..core.update_checker import set_skipped_version
        from ..constants import UPDATE_NOTIFICATION_ID
        from ...notifications.store import get_notification_store

        state = get_update_state()
        info = state.update_info

        if info and info.latest_version:
            set_skipped_version(info.latest_version)
            logger.info("User skipped version %s", info.latest_version)

        get_notification_store().dismiss(UPDATE_NOTIFICATION_ID)
        state.set_idle()
        return {"FINISHED"}


class MIXAR_OT_open_changelog(bpy.types.Operator):
    """Open the changelog in the default browser"""

    bl_idname = "mixar.open_changelog"
    bl_label = "View Changelog"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..core.state import get_update_state

        state = get_update_state()
        info = state.update_info
        url = info.changelog_url if info else ""

        if not url:
            self.report({"WARNING"}, "No changelog URL available")
            return {"CANCELLED"}

        webbrowser.open(url)
        return {"FINISHED"}


classes = (
    MIXAR_OT_install_update,
    MIXAR_OT_dismiss_update,
    MIXAR_OT_open_changelog,
)
