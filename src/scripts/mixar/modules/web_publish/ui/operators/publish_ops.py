# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish to Web operators: publish / new version / cancel / copy link /
open / unpublish / dismiss.

``mixar.web_publish`` hands the scene to the shared pipeline
(``core/pipeline.py``), which the agent API uses too; the timer there
mirrors progress into RNA.
"""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import rpt_
from mixar.modules.web_publish.core.publish_state import (
    TERMINAL_STATUSES,
    format_message,
    get_publish_state,
)

_logger = get_logger(__name__)


def _props(context):
    scene = getattr(context, "scene", None)
    return getattr(scene, "mixar_web_publish", None) if scene else None


class MIXAR_OT_web_publish(bpy.types.Operator):
    """Publish this scene as an explorable 3D website"""

    bl_idname = "mixar.web_publish"
    bl_label = "Publish to Web"
    bl_description = "Publish this scene as an explorable 3D website with a shareable link"
    bl_options = {"REGISTER"}

    update_existing: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Update Existing",
        description="Publish a new version at this scene's existing link",
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context) -> bool:
        return _props(context) is not None and not get_publish_state().busy

    def execute(self, context):
        from mixar.modules.web_publish.core.pipeline import begin_publish

        outcome = begin_publish(context, update_existing=self.update_existing, via="panel")
        if not outcome.get("ok"):
            self.report({"WARNING"},
                        format_message(rpt_(outcome["error"]), outcome.get("error_args")))
            return {"CANCELLED"}
        return {"FINISHED"}


class MIXAR_OT_web_publish_cancel(bpy.types.Operator):
    """Cancel the running publish"""

    bl_idname = "mixar.web_publish_cancel"
    bl_label = "Cancel Publish"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context) -> bool:
        return get_publish_state().busy

    def execute(self, context):
        get_publish_state().request_cancel()
        self.report({"INFO"}, "Cancelling publish…")
        return {"FINISHED"}


class MIXAR_OT_web_publish_copy_link(bpy.types.Operator):
    """Copy the public link to this scene's 3D website"""

    bl_idname = "mixar.web_publish_copy_link"
    bl_label = "Copy Link"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context) -> bool:
        props = _props(context)
        return bool(props and props.is_published and props.link)

    def execute(self, context):
        context.window_manager.clipboard = _props(context).link
        self.report({"INFO"}, "Link copied to clipboard")
        return {"FINISHED"}


class MIXAR_OT_web_publish_open(bpy.types.Operator):
    """Open this scene's 3D website in your browser"""

    bl_idname = "mixar.web_publish_open"
    bl_label = "Open in Browser"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context) -> bool:
        props = _props(context)
        return bool(props and props.is_published and props.link)

    def execute(self, context):
        bpy.ops.wm.url_open(url=_props(context).link)
        return {"FINISHED"}


class MIXAR_OT_web_publish_unpublish(bpy.types.Operator):
    """Take this scene's 3D website offline and delete its files"""

    bl_idname = "mixar.web_publish_unpublish"
    bl_label = "Unpublish"
    bl_description = "Remove the published website and its stored files"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context) -> bool:
        props = _props(context)
        return bool(props and props.is_published) and not get_publish_state().busy

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from mixar.modules.web_publish.core.publish_api import (
            PublishApiError,
            ScenePublishService,
        )

        props = _props(context)
        try:
            ScenePublishService().delete_scene(props.published_scene_id)
        except PublishApiError as exc:
            if exc.status_code != 404:  # already gone server-side: clear locally
                self.report({"ERROR"}, format_message(rpt_(exc.message), exc.params))
                return {"CANCELLED"}
        props.published_scene_id = ""
        props.slug = ""
        props.share_url = ""
        props.viewer_url = ""
        props.revision = 0
        props.last_published = ""
        self.report({"INFO"}, "Scene unpublished")
        return {"FINISHED"}


class MIXAR_OT_web_publish_dismiss(bpy.types.Operator):
    """Dismiss the publish outcome"""

    bl_idname = "mixar.web_publish_dismiss"
    bl_label = "Dismiss"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context) -> bool:
        progress, _ = get_publish_state().snapshot()
        return progress.status in TERMINAL_STATUSES

    def execute(self, context):
        get_publish_state().reset()
        wm = context.window_manager
        if hasattr(wm, "mixar_web_publish_status"):
            wm.mixar_web_publish_status = "IDLE"
            wm.mixar_web_publish_progress = 0.0
        return {"FINISHED"}


classes = (
    MIXAR_OT_web_publish,
    MIXAR_OT_web_publish_cancel,
    MIXAR_OT_web_publish_copy_link,
    MIXAR_OT_web_publish_open,
    MIXAR_OT_web_publish_unpublish,
    MIXAR_OT_web_publish_dismiss,
)


def register():
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)


def unregister():
    from mixar.modules.web_publish.core.pipeline import stop_timer

    stop_timer()
    for cls in reversed(classes):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
