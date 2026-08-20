# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Auto-Update Operators

Blender operators for the browser-based update flow: open the downloads
page, skip a version, re-show the update toast, and view changelogs.
Auto-registered by bootstrap via the ``classes`` tuple at module level.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MIXAR_OT_dismiss_update(bpy.types.Operator):
    """Skip this version and dismiss the notification"""

    bl_idname = "mixar.dismiss_update"
    bl_label = "Skip This Version"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..core import trigger
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

        # Dismiss the toast only — update_info/state stay intact so the
        # topbar badge persists until the user is on the latest version.
        get_notification_store().dismiss(UPDATE_NOTIFICATION_ID)
        trigger._tag_topbar_redraw()
        return {"FINISHED"}


class MIXAR_OT_open_downloads_page(bpy.types.Operator):
    """Open the Mixar downloads page in the default browser"""

    bl_idname = "mixar.open_downloads_page"
    bl_label = "Download"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from mixar.config.config import get_config

        from ..constants import DOWNLOADS_PAGE_URL
        from ..core.state import get_update_state

        # Prefer a per-release URL supplied by the backend in the /check
        # response; only trust an explicit https URL, else fall back to the
        # configured downloads page, then the hardcoded constant.
        info = get_update_state().update_info
        backend_url = info.browser_download_url if info else ""

        if backend_url.startswith("https://"):
            url = backend_url
        else:
            url = get_config().get("updates", {}).get("downloads_url") or DOWNLOADS_PAGE_URL

        # Use Blender's native URL opener — webbrowser.open() fails silently
        # under Blender's embedded Python (no browser registry populated).
        bpy.ops.wm.url_open(url=url)
        return {"FINISHED"}


class MIXAR_OT_check_for_updates(bpy.types.Operator):
    """Check whether a newer version of Mixar is available"""

    bl_idname = "mixar.check_for_updates"
    bl_label = "Check for Updates"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..constants import UpdateState
        from ..core.trigger import (
            _push_update_available_toast,
            trigger_update_check,
        )
        from ..core.state import get_update_state

        state = get_update_state()
        info = state.update_info

        # An update is already known — re-show the toast (the user may
        # have skipped it earlier and changed their mind) instead of
        # re-hitting the server.
        if info is not None:
            _push_update_available_toast(info)
            return {"FINISHED"}

        if state.state == UpdateState.CHECKING:
            self.report({"INFO"}, "An update check is already in progress")
            return {"CANCELLED"}

        trigger_update_check(interactive=True)
        self.report({"INFO"}, "Checking for updates…")
        return {"FINISHED"}


class MIXAR_OT_show_update_toast(bpy.types.Operator):
    """Show details for the pending Mixar update"""

    bl_idname = "mixar.show_update_toast"
    bl_label = "Update Available"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..core import trigger
        from ..core.state import get_update_state

        info = get_update_state().update_info
        if info is None:
            return {"CANCELLED"}

        # Re-push the sticky toast — this is the topbar badge's click
        # action, so a user who dismissed the toast can always get back
        # to the Download button.
        trigger._push_update_available_toast(info)
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

        bpy.ops.wm.url_open(url=url)
        return {"FINISHED"}


classes = (
    MIXAR_OT_dismiss_update,
    MIXAR_OT_open_downloads_page,
    MIXAR_OT_check_for_updates,
    MIXAR_OT_show_update_toast,
    MIXAR_OT_open_changelog,
)
