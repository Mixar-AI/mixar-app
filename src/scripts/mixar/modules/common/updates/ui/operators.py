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
        from ..core.trigger import is_forced
        from ..core.update_checker import set_skipped_version
        from ..constants import UPDATE_NOTIFICATION_ID
        from ...notifications.store import get_notification_store

        state = get_update_state()
        info = state.update_info

        # Forced/unsupported updates cannot be skipped — defence in depth;
        # the toast doesn't offer Skip for these, but nothing else should
        # be able to clear the requirement either.
        if info and is_forced(info):
            self.report({"WARNING"}, "This update is required and cannot be skipped")
            return {"CANCELLED"}

        if info and info.latest_version:
            set_skipped_version(info.latest_version)
            logger.info("User skipped version %s", info.latest_version)

        get_notification_store().dismiss(UPDATE_NOTIFICATION_ID)
        state.set_idle()
        return {"FINISHED"}


class MIXAR_OT_start_update_download(bpy.types.Operator):
    """Download the available update and show live progress"""

    bl_idname = "mixar.start_update_download"
    bl_label = "Update"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..core import trigger
        from ..core.state import get_update_state

        info = get_update_state().update_info
        if info is None:
            self.report({"WARNING"}, "No update information available")
            return {"CANCELLED"}

        trigger.begin_download(info)
        return {"FINISHED"}


class MIXAR_OT_open_downloads_page(bpy.types.Operator):
    """Open the Mixar downloads page in the default browser"""

    bl_idname = "mixar.open_downloads_page"
    bl_label = "Download in Browser"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from mixar.config.config import get_config

        from ..constants import DOWNLOADS_PAGE_URL

        url = get_config().get("updates", {}).get("downloads_url") or DOWNLOADS_PAGE_URL
        webbrowser.open(url)
        return {"FINISHED"}


class MIXAR_OT_cancel_update(bpy.types.Operator):
    """Cancel the in-flight update download"""

    bl_idname = "mixar.cancel_update"
    bl_label = "Cancel"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..constants import UPDATE_NOTIFICATION_ID
        from ..core.state import get_update_state
        from ...notifications.store import get_notification_store

        state = get_update_state()
        # Signal cancel and dismiss the toast, but do NOT set_idle() here:
        # set_idle() clears cancel_requested, which would let the in-flight
        # download thread run to completion and re-show a "ready" toast. The
        # download thread transitions to IDLE once it observes the flag.
        state.request_cancel()
        get_notification_store().dismiss(UPDATE_NOTIFICATION_ID)
        logger.info("User cancelled update download")
        return {"FINISHED"}


class MIXAR_OT_check_for_updates(bpy.types.Operator):
    """Check whether a newer version of Mixar is available"""

    bl_idname = "mixar.check_for_updates"
    bl_label = "Check for Updates"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..constants import UpdateState
        from ..core.state import get_update_state
        from ..core.trigger import _push_update_toast, trigger_update_check

        state = get_update_state()
        current = state.state
        info = state.update_info

        # An installer is already downloaded — re-show the toast (the user
        # may have skipped it earlier and changed their mind).
        if current == UpdateState.READY and info:
            _push_update_toast(info, ready=True)
            return {"FINISHED"}

        if current == UpdateState.DOWNLOADING and info:
            self.report(
                {"INFO"},
                f"Update {info.latest_version} is downloading in the background",
            )
            return {"FINISHED"}

        if current in (UpdateState.CHECKING, UpdateState.INSTALLING):
            self.report({"INFO"}, "An update check is already in progress")
            return {"CANCELLED"}

        trigger_update_check(interactive=True)
        self.report({"INFO"}, "Checking for updates…")
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
    MIXAR_OT_start_update_download,
    MIXAR_OT_open_downloads_page,
    MIXAR_OT_cancel_update,
    MIXAR_OT_check_for_updates,
    MIXAR_OT_open_changelog,
)
