# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remix operators: start a remix that is waiting from the web.

Starting one replaces the open file with a downloaded project, so it is
user-only: it refuses under an agent frame and is denied to agent scripts
(``sandbox_denylist.DENIED_OPS``).
"""

import bpy
from bpy.types import Operator

from mixar.config.agent_guard import called_from_agent_script
from mixar.modules.common.i18n import iface_, rpt_
from mixar.modules.game_studio.core import jobs
from mixar.modules.game_studio.core.jobs import JobError
from mixar.modules.remix.constants import POLL_FIRST_S
from mixar.modules.remix.core import inbox, intake, lineage, opening


def _fail(message: str) -> None:
    try:
        from mixar.modules.common.notifications import get_notification_store
        get_notification_store().push("error", rpt_("The remix could not be opened."), body=message)
    except Exception:  # noqa: BLE001
        pass


def start_remix(intent_id: str) -> str:
    from mixar.config.config import get_community_api_url
    inner = intake.claim_work(intake.remix_root(), get_community_api_url(), intent_id)

    def work(handle):
        try:
            plan = inner(handle)
        except JobError as exc:
            _fail(exc.message)
            raise
        jobs.call_on_main(lambda: opening.open_remix(plan))
        return {"project_path": plan["project_path"], "origin": plan["origin"]}

    return jobs.start("remix", work)


class MIXAR_OT_remix_start(Operator):
    """Open your own copy of the post or game you chose to remix on the web"""
    bl_idname = "mixar.remix_start"
    bl_label = "Start Remix"
    bl_options = {'INTERNAL'}

    def _waiting(self):
        return inbox.get_inbox().newest()

    def invoke(self, context, event):
        item = self._waiting()
        if item is None:
            self.report({'WARNING'}, rpt_("No remix is waiting. Press Remix in Mixar on the web first."))
            return {'CANCELLED'}
        if not bpy.data.is_dirty:
            return self.execute(context)
        origin = lineage.clean_origin(item.get("origin")) or {}
        return context.window_manager.invoke_confirm(
            self, event,
            title=iface_("Remix \"{title}\"?").format(title=origin.get("title") or ""),
            message=iface_("The project you have open has unsaved changes. They will be lost."),
            confirm_text=iface_("Start remix"), translate=False)

    def execute(self, context):
        if bpy.app.background or called_from_agent_script():
            self.report({'ERROR'}, rpt_("Only you can start a remix, from the Mixar window."))
            return {'CANCELLED'}
        item = self._waiting()
        if item is None:
            return {'CANCELLED'}
        inbox.get_inbox().take(item["intent_id"])
        start_remix(item["intent_id"])
        self.report({'INFO'}, rpt_("Getting the remix…"))
        return {'FINISHED'}


class MIXAR_OT_remix_check(Operator):
    """Ask the Mixar Store whether a remix is waiting for you"""
    bl_idname = "mixar.remix_check"
    bl_label = "Check for Remixes"

    def execute(self, context):
        inbox.tick()
        return {'FINISHED'}


classes = (MIXAR_OT_remix_start, MIXAR_OT_remix_check)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.background and not bpy.app.timers.is_registered(inbox.tick):
        bpy.app.timers.register(inbox.tick, first_interval=POLL_FIRST_S, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(inbox.tick):
        bpy.app.timers.unregister(inbox.tick)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
