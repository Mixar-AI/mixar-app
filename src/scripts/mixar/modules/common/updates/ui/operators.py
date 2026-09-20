# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Auto-Update Operators

Blender operators for the update flow: restart-to-update, cancel a
download, open the downloads page, skip a version, re-show the update
toast, and view changelogs.  Auto-registered by bootstrap via the
``classes`` tuple at module level.

The operators stay thin on purpose — every decision they make lives in
``core/install_flow.py`` where it can be unit-tested; under the test
suite's ``bpy`` mock an operator body never runs.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MIXAR_OT_restart_to_update(bpy.types.Operator):
    """Restart Mixar and install the downloaded update"""

    bl_idname = "mixar.restart_to_update"
    bl_label = "Restart & Update"
    bl_options = {"INTERNAL"}

    save_first: bpy.props.BoolProperty(
        name="Save Changes",
        description="Save the current file before restarting",
        default=True,
    )

    def invoke(self, context, event):
        routed = self._route(context)
        if routed is not None:
            return routed

        # Same operator instance runs execute() when the dialog is
        # confirmed, so this flag marks "the user saw the dialog".
        self._confirmed_via_dialog = True
        self.save_first = self._can_save()
        return context.window_manager.invoke_props_dialog(self, width=380)

    def _route(self, context):
        """Shared pre-flight for invoke() and a dialog-less execute().

        Returns an operator result to bounce out with, or ``None`` when
        the installer is ready and the caller should continue to the
        confirmation / install step.
        """
        from ..core.install_flow import plan_restart

        plan = plan_restart()

        if plan == "browser":
            # Nothing staged and nothing we can stage — the downloads page
            # is the honest answer, not a spinner that never resolves.
            return bpy.ops.mixar.open_downloads_page()

        if plan == "waiting":
            from ..core.toasts import refresh_update_toast

            refresh_update_toast()
            self.report({"INFO"}, "Downloading update — Mixar will restart when it's ready")
            return {"FINISHED"}

        return None

    @staticmethod
    def _can_save() -> bool:
        """True when a plain save would work (a modified, already-saved file)."""
        return bool(bpy.data.is_dirty and bpy.data.filepath)

    def draw(self, context):
        from ..core.state import get_update_state

        info = get_update_state().update_info
        version = info.latest_version if info else ""

        layout = self.layout
        layout.label(text=f"Mixar will close and update to {version}.", icon="FILE_REFRESH")
        layout.label(text="It reopens automatically when the update is done.")

        if self._can_save():
            layout.separator()
            layout.prop(self, "save_first", text="Save changes to the current file")
        elif bpy.data.is_dirty:
            layout.separator()
            row = layout.row()
            row.alert = True
            row.label(text="Unsaved work will be lost — cancel and save first.",
                      icon="ERROR")

    def execute(self, context):
        from ..core.install_flow import apply_and_restart

        # Reached without the dialog: an EXEC-dispatched click or a script.
        # Route exactly like invoke() would have, and never quit over work
        # that cannot be saved silently — without a dialog there is no way
        # to ask.
        if not getattr(self, "_confirmed_via_dialog", False):
            routed = self._route(context)
            if routed is not None:
                return routed
            if bpy.data.is_dirty and not bpy.data.filepath:
                self.report(
                    {"WARNING"}, "Save your work first, then click Restart & Update",
                )
                return {"CANCELLED"}
            self.save_first = self._can_save()

        if self.save_first and self._can_save():
            try:
                bpy.ops.wm.save_mainfile()
            except RuntimeError as e:
                # Never quit over a file we failed to save.
                logger.error("Save before update failed: %s", e)
                self.report({"ERROR"}, "Could not save the file — update cancelled")
                return {"CANCELLED"}

        started, message = apply_and_restart()
        if not started:
            from ..core.toasts import refresh_update_toast

            refresh_update_toast()
            self.report({"ERROR"}, message or "Could not start the update")
            return {"CANCELLED"}

        self.report({"INFO"}, "Installing update…")
        return {"FINISHED"}


class MIXAR_OT_cancel_update_download(bpy.types.Operator):
    """Stop downloading the update"""

    bl_idname = "mixar.cancel_update_download"
    bl_label = "Cancel"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..core.install_flow import cancel_download
        from ..core.state import get_update_state
        from ..core.toasts import refresh_update_toast
        from ..core.update_checker import is_forced

        info = get_update_state().update_info

        # Defence in depth, matching Skip: the forced toast offers no
        # Cancel, and nothing else should be able to clear the requirement.
        if info and is_forced(info):
            self.report({"WARNING"}, "This update is required and cannot be cancelled")
            return {"CANCELLED"}

        cancel_download()
        if info is not None:
            # Back to the plain "update available" toast — cancelling the
            # download must not also throw the update away.
            from ..core.toasts import push_update_available_toast

            push_update_available_toast(info)
        else:
            refresh_update_toast()
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
        from ..core.state import get_update_state
        from ..core.toasts import push_update_available_toast
        from ..core.trigger import trigger_update_check

        state = get_update_state()
        info = state.update_info

        # An update is already known — re-show the toast (the user may
        # have skipped it earlier and changed their mind) instead of
        # re-hitting the server.
        if info is not None:
            push_update_available_toast(info)
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
        from ..core.state import get_update_state
        from ..core.toasts import push_update_available_toast

        info = get_update_state().update_info
        if info is None:
            return {"CANCELLED"}

        # Re-push the sticky toast — this is the topbar badge's click
        # action, so a user who dismissed the toast can always get back
        # to the update button.
        push_update_available_toast(info)
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
    MIXAR_OT_restart_to_update,
    MIXAR_OT_cancel_update_download,
    MIXAR_OT_open_downloads_page,
    MIXAR_OT_check_for_updates,
    MIXAR_OT_show_update_toast,
    MIXAR_OT_open_changelog,
)
