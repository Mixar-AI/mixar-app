# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixar Library operators: refresh, install/update, uninstall, launch.

Launch runs a downloaded program, so it is user-only: the Play button
(``mixar.game_library_launch``) refuses under an agent frame and its slug
is never remembered, and an agent's ``launch_library_game`` request is
approved only through ``mixar.game_library_launch_approve`` — the same
one-time-token dialog as publishing. Both are also denied to agent
scripts in ``sandbox_denylist.DENIED_OPS``. The process starts on a thread.
"""

import threading

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.agent_guard import called_from_agent_script
from mixar.modules.common.i18n import iface_, rpt_
from mixar.modules.game_studio.core import agent_api, approvals, library, library_install


def _launch(op, slug: str) -> set:
    root = library.library_root()
    reply = {}

    def work():
        reply.update(library_install.launch_installed(root, slug))
        if not reply.get("ok"):
            try:
                from mixar.modules.common.notifications import get_notification_store
                get_notification_store().push("error", rpt_("The game could not start."),
                                              body=str(reply.get("error") or ""))
            except Exception:
                pass

    thread = threading.Thread(target=work, name="mixar-library-launch", daemon=True)
    thread.start()
    op.report({'INFO'}, rpt_("Starting the game…"))
    return {'FINISHED'}


def _refuse_agents(op) -> bool:
    if bpy.app.background or called_from_agent_script():
        op.report({'ERROR'}, rpt_("Only you can run a game, from the Mixar window."))
        return True
    return False


class MIXAR_OT_game_library_refresh(Operator):
    """Reload your games from the Mixar Store"""
    bl_idname = "mixar.game_library_refresh"
    bl_label = "Refresh Library"

    def execute(self, context):
        agent_api.library_list(refresh=True)
        return {'FINISHED'}


class MIXAR_OT_game_library_install(Operator):
    """Download, check and install this game for this computer"""
    bl_idname = "mixar.game_library_install"
    bl_label = "Install"

    slug: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        # The user's Install also self-tests (runs the game headless), so it
        # is user-only like Play; agents use agent_api.start_library_install,
        # which never executes the download.
        if _refuse_agents(self) or not self.slug:
            return {'CANCELLED'}
        from mixar.config.config import get_community_api_url
        from mixar.modules.game_studio.core import jobs
        if jobs.running("install") is not None:
            self.report({'ERROR'}, rpt_("Another game is installing."))
            return {'CANCELLED'}
        jobs.start("install", library_install.install_by_slug_work(
            library.library_root(), get_community_api_url(), self.slug, library.host_platform(),
            run_selftest=True))
        return {'FINISHED'}


class MIXAR_OT_game_library_uninstall(Operator):
    """Remove this game from this computer"""
    bl_idname = "mixar.game_library_uninstall"
    bl_label = "Uninstall"

    slug: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        agent_api.start_library_uninstall(self.slug)
        return {'FINISHED'}


class MIXAR_OT_game_library_launch(Operator):
    """Play this installed game in its own window"""
    bl_idname = "mixar.game_library_launch"
    bl_label = "Play"

    slug: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        if _refuse_agents(self) or not self.slug:
            return {'CANCELLED'}
        return _launch(self, self.slug)


class MIXAR_OT_game_library_launch_approve(Operator):
    """Approve launching the game Mixie asked to play"""
    bl_idname = "mixar.game_library_launch_approve"
    bl_label = "Play Game"
    bl_options = {'INTERNAL'}

    request_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    token: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        request = (approvals.get(self.request_id) if self.request_id
                   else approvals.pending("launch"))
        if request is None or request["state"] != approvals.AWAITING or request["kind"] != "launch":
            self.report({'WARNING'}, rpt_("No game is waiting to be launched."))
            return {'CANCELLED'}
        self.request_id = request["request_id"]
        self.token = approvals._issue_token(self.request_id)
        return context.window_manager.invoke_confirm(
            self, event, title=iface_("Play \"{title}\"?").format(title=request["summary"]["title"]),
            message=iface_("Mixie asks to start this game from your Library."),
            confirm_text=iface_("Play"), translate=False)

    def execute(self, context):
        if _refuse_agents(self):
            return {'CANCELLED'}
        payload = approvals._claim(self.request_id, self.token, kind="launch")
        if payload is None:
            self.report({'ERROR'}, rpt_("This launch request is no longer waiting for approval."))
            return {'CANCELLED'}
        _dismiss(self.request_id)
        return _launch(self, payload["slug"])


class MIXAR_OT_game_library_launch_decline(Operator):
    """Don't start the game"""
    bl_idname = "mixar.game_library_launch_decline"
    bl_label = "Cancel Launch"
    bl_options = {'INTERNAL'}

    request_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        request = approvals.get(self.request_id) if self.request_id else approvals.pending("launch")
        if request is not None:
            approvals.cancel(request["request_id"], "The user declined the launch.", "user_declined")
            _dismiss(request["request_id"])
        return {'FINISHED'}


def _dismiss(request_id: str) -> None:
    try:
        from mixar.modules.common.notifications import get_notification_store
        get_notification_store().dismiss(f"game-launch-{request_id}")
    except Exception:
        pass


classes = (
    MIXAR_OT_game_library_refresh,
    MIXAR_OT_game_library_install,
    MIXAR_OT_game_library_uninstall,
    MIXAR_OT_game_library_launch,
    MIXAR_OT_game_library_launch_approve,
    MIXAR_OT_game_library_launch_decline,
)
