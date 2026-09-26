# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish the active add-on to Mixar Community.

No dialog: props dialogs can open behind the always-on-top Agent Bubble
window (see workspace_ops.py). The add-on is checked and zipped here, uploaded
off-thread, and the resulting draft opens in the browser, where the author
sets the price and license and publishes. Every version is reviewed by a
moderator before anyone else can download it.
"""

import threading

import bpy
from bpy.types import Operator

from ..errors import AddonProjectError
from ..service import get_addon_project_service

_TOAST_ID = "addon_project_publish"
_in_flight = threading.Event()


def _toast(level: str, title: str, body: str = "", url: str = None) -> None:
    try:
        from mixar.modules.common.notifications import get_notification_store

        get_notification_store().push(level, title, body, id=_TOAST_ID, action_url=url, ttl_ms=8000)
    except Exception:
        pass


def _finish_on_main_thread(project_id, package, result, error) -> None:
    """Timer callback: all bpy / storage writes happen here, never on the worker."""

    def _apply():
        _in_flight.clear()
        if error is not None:
            _toast("error", "Couldn't publish the add-on", str(error))
            return None
        try:
            get_addon_project_service().remember_community_post(project_id, package, result.post_id)
        except Exception:
            pass  # only costs a duplicate post next time
        verb = "Draft created" if result.created else "New version uploaded"
        _toast("success", f"{verb} on Mixar Community", "Finish the listing in your browser", result.web_url)
        try:
            bpy.ops.wm.url_open(url=result.web_url)
        except Exception:
            pass
        return None

    bpy.app.timers.register(_apply)


class MIXAR_OT_addon_project_publish(Operator):
    bl_idname = "mixar.addon_project_publish"
    bl_label = "Publish to Community"
    bl_description = (
        "Check the active add-on, upload it to Mixar Community as a draft and "
        "open it in your browser to set a price and publish. A moderator "
        "reviews every version before others can download it"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if _in_flight.is_set():
            cls.poll_message_set("An upload is already running")
            return False
        return getattr(context, "scene", None) is not None

    def execute(self, context):
        service = get_addon_project_service()
        project_id = str(getattr(context.scene, "mixie_addon_project_id", "") or "")
        try:
            if not project_id:
                # Reached from File ▸ Add-on Projects without a linked scene:
                # link the saved projects folder, as a project-mode Send does.
                if service.get_workspace_root() is None:
                    raise AddonProjectError("no_workspace", "Create an add-on first (File ▸ Add-on Projects ▸ New Add-on)")
                project_id = service.link_workspace_root()["project_id"]
                context.scene.mixie_addon_project_id = project_id
            packaged = service.package_for_publish(project_id)
        except AddonProjectError as exc:
            self.report({'ERROR'}, exc.message)
            return {'CANCELLED'}
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, never swallowed
            self.report({'ERROR'}, f"Couldn't package the add-on: {exc}")
            return {'CANCELLED'}

        existing = service.community_post_id(project_id, packaged.package)
        _in_flight.set()

        def _work():
            result = error = None
            try:
                from mixar.modules.common.api.services.community_service import CommunityService

                result = CommunityService().publish_addon(
                    packaged.filename,
                    packaged.data,
                    title=packaged.title,
                    description=packaged.description,
                    existing_post_id=existing,
                )
            except Exception as exc:  # noqa: BLE001 - reported via toast on the main thread
                error = exc
            _finish_on_main_thread(project_id, packaged.package, result, error)

        threading.Thread(target=_work, name="mixar-addon-publish", daemon=True).start()
        self.report({'INFO'}, f"Uploading {packaged.title} to Mixar Community…")
        _toast("info", f"Uploading {packaged.title}…")
        return {'FINISHED'}


classes = (MIXAR_OT_addon_project_publish,)
