# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish operators: publish / update / unpublish / share / open.

The publish operator owns the main-thread half (validation, GLB export,
thumbnail, hashing) and hands off to the worker thread. A registered timer
mirrors PublishState into scene RNA so the panel can draw progress without
ever blocking redraws.
"""

from __future__ import annotations

import datetime as dt
import os

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.web_publish.constants import (
    ANALYTICS_EVENT_PUBLISH,
    ANALYTICS_EVENT_PUBLISH_FAIL,
    ANALYTICS_EVENT_PUBLISH_OK,
    DESCRIPTION_MAX_LENGTH,
    MAX_SCENE_BYTES,
    STATE_POLL_INTERVAL_SECONDS,
    TITLE_MAX_LENGTH,
)
from mixar.modules.web_publish.core import glb_export
from mixar.modules.web_publish.core.publish_api import (
    PublishApiError,
    ScenePublishClient,
)
from mixar.modules.web_publish.core.publish_state import (
    STATUS_DONE,
    STATUS_ERROR,
    PublishJob,
    compute_sha256,
    derive_title,
    get_publish_state,
    viewer_config_block,
)
from mixar.modules.web_publish.core.upload_worker import start_publish

_logger = get_logger(__name__)

_timer_registered = False


def _scene_props(context):
    props = getattr(context.scene, "mixar_web_publish", None)
    return props


def _track_event(event: str, props=None) -> None:
    """Content-free analytics: names and counts only, never titles/paths."""
    try:
        from mixar.modules.common.analytics import track_event

        track_event(event)
    except Exception:  # noqa: BLE001 - analytics must never break publishing
        pass


class MIXAR_OT_web_publish(bpy.types.Operator):
    """Publish this scene as an explorable 3D website"""

    bl_idname = "mixar.web_publish"
    bl_label = "Publish to Web"
    bl_description = (
        "Publish this scene as an explorable 3D website and copy a public link"
    )
    bl_options = {"REGISTER"}

    update_existing: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Update Existing",
        description="Publish a new revision of the scene already linked here",
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context) -> bool:
        props = _scene_props(context)
        if props is None:
            return False
        if props.is_busy or get_publish_state().busy:
            return False
        return any(obj.type == "MESH" and obj.visible_get() for obj in context.scene.objects)

    def execute(self, context):
        props = _scene_props(context)
        if props is None:  # pragma: no cover - poll guards this
            return {"CANCELLED"}

        # Lazy import: auth pulls keyring/OAuth machinery that must not load
        # with the UI (bootstrap time-budget), and the check runs per click.
        from mixar.modules.auth.core.auth import get_access_token

        if not get_access_token():
            self.report({"WARNING"}, "Sign in to Mixar to publish scenes")
            return {"CANCELLED"}

        title = (props.title or derive_title(context.scene.name)).strip()
        if len(title) > TITLE_MAX_LENGTH:
            self.report({"WARNING"}, f"Title is limited to {TITLE_MAX_LENGTH} characters")
            return {"CANCELLED"}
        description = (props.description or "").strip()[:DESCRIPTION_MAX_LENGTH]

        # 1. Export + thumbnail + hash (main thread — Blender operators).
        state = get_publish_state()
        state.start()
        state.set_status("EXPORTING", "Exporting scene…", 0.01)
        _track_event(ANALYTICS_EVENT_PUBLISH)

        workspace, glb_path = glb_export.make_export_workspace()
        try:
            glb_export.export_glb(
                context, glb_path, include_animation=props.include_animation
            )
            sha256, size = compute_sha256(glb_path)
            if size > MAX_SCENE_BYTES:
                raise glb_export.ExportError(
                    f"Scene is {size // (1024 * 1024)} MB — the publish limit "
                    f"is {MAX_SCENE_BYTES // (1024 * 1024)} MB. Hide heavy "
                    "objects or reduce texture resolution and try again."
                )
            thumbnail_path = glb_export.render_thumbnail(
                context, os.path.join(workspace, glb_export.THUMBNAIL_FILENAME)
            )
            scene_meta = glb_export.collect_scene_meta(context)
            camera_config = glb_export.collect_camera_config(context)

            job = PublishJob(
                title=title,
                description=description,
                visibility=props.visibility,
                glb_path=glb_path,
                thumbnail_path=thumbnail_path or "",
                content_sha256=sha256,
                scene_meta=scene_meta,
                viewer_config=viewer_config_block(camera_config),
                existing_scene_id=props.published_scene_id if self.update_existing else "",
                existing_slug=props.slug if self.update_existing else "",
            )
        except Exception as exc:  # noqa: BLE001 - report export problems inline
            glb_export.cleanup_workspace(workspace)
            state.set_error(str(exc))
            _track_event(ANALYTICS_EVENT_PUBLISH_FAIL)
            self.report({"ERROR"}, f"Publish failed: {exc}")
            return {"CANCELLED"}

        # 2. Background thread: upload + finalize; timer mirrors state → RNA.
        if not start_publish(job, workspace):
            glb_export.cleanup_workspace(workspace)
            state.set_error("A publish is already running")
            return {"CANCELLED"}

        _ensure_timer()
        return {"FINISHED"}

    def invoke(self, context, event):
        if self.update_existing:
            return self.execute(context)
        return self.execute(context)


class MIXAR_OT_web_cancel(bpy.types.Operator):
    """Cancel the running publish"""

    bl_idname = "mixar.web_publish_cancel"
    bl_label = "Cancel Publish"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context) -> bool:
        return get_publish_state().busy

    def execute(self, context):
        get_publish_state().request_cancel()
        self.report({"INFO"}, "Cancelling publish…")
        return {"FINISHED"}


class MIXAR_OT_web_copy_link(bpy.types.Operator):
    """Copy the public link to this scene's 3D website"""

    bl_idname = "mixar.web_publish_copy_link"
    bl_label = "Copy Link"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context) -> bool:
        props = _scene_props(context)
        return bool(props and props.is_published)

    def execute(self, context):
        props = _scene_props(context)
        context.window_manager.clipboard = props.viewer_url or props.share_url
        self.report({"INFO"}, "Link copied to clipboard")
        return {"FINISHED"}


class MIXAR_OT_web_open(bpy.types.Operator):
    """Open this scene's 3D website in your browser"""

    bl_idname = "mixar.web_publish_open"
    bl_label = "Open in Browser"
    bl_options = {"REGISTER"}

    url: bpy.props.StringProperty(options={"SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context) -> bool:
        props = _scene_props(context)
        return bool(props and props.is_published)

    def execute(self, context):
        props = _scene_props(context)
        url = self.url or props.viewer_url or props.share_url
        if not url:
            self.report({"WARNING"}, "Nothing to open yet")
            return {"CANCELLED"}
        bpy.ops.wm.url_open(url=url)
        return {"FINISHED"}


class MIXAR_OT_web_unpublish(bpy.types.Operator):
    """Take this scene's 3D website offline and delete its files"""

    bl_idname = "mixar.web_publish_unpublish"
    bl_label = "Unpublish"
    bl_description = "Remove the published website and its stored files"

    @classmethod
    def poll(cls, context) -> bool:
        props = _scene_props(context)
        if not props or not props.is_published:
            return False
        return not get_publish_state().busy

    def execute(self, context):
        props = _scene_props(context)
        try:
            ScenePublishClient().delete_scene(props.published_scene_id)
        except PublishApiError as exc:
            if exc.status_code == 404:
                _logger.info("web_publish scene already gone server-side")
            else:
                self.report({"ERROR"}, f"Could not unpublish: {exc.message}")
                return {"CANCELLED"}
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not unpublish: {exc}")
            return {"CANCELLED"}

        props.published_scene_id = ""
        props.slug = ""
        props.share_url = ""
        props.viewer_url = ""
        props.revision = 0
        props.last_published = ""
        self.report({"INFO"}, "Scene unpublished")
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)


class MIXAR_OT_web_clear_error(bpy.types.Operator):
    """Clear the publish error"""

    bl_idname = "mixar.web_publish_clear_error"
    bl_label = "Dismiss"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context) -> bool:
        props = _scene_props(context)
        return bool(props and props.status == STATUS_ERROR)

    def execute(self, context):
        get_publish_state().reset()
        props = _scene_props(context)
        if props:
            props.status = "IDLE"
            props.error_message = ""
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# State timer: PublishState → scene RNA → redraw
# ---------------------------------------------------------------------------


def _state_timer():
    global _timer_registered
    context = bpy.context
    props = getattr(context.scene, "mixar_web_publish", None) if context.scene else None
    state = get_publish_state()
    progress, result = state.snapshot()

    if props is not None:
        props.status = progress.status
        props.progress = progress.progress
        props.status_detail = progress.detail
        if progress.status == STATUS_ERROR:
            props.error_message = progress.error

        if progress.status == STATUS_DONE and result.slug:
            props.published_scene_id = result.scene_id
            props.slug = result.slug
            props.share_url = result.share_url
            props.viewer_url = result.viewer_url
            props.revision = result.revision
            props.last_published = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
            _track_event(ANALYTICS_EVENT_PUBLISH_OK)
            state.reset()
        elif progress.status == STATUS_ERROR:
            _track_event(ANALYTICS_EVENT_PUBLISH_FAIL)

    _redraw_view3d(context)

    if state.busy:
        return STATE_POLL_INTERVAL_SECONDS

    _timer_registered = False
    return None


def _redraw_view3d(context) -> None:
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:  # noqa: BLE001
        pass


def _ensure_timer() -> None:
    global _timer_registered
    if not _timer_registered:
        bpy.app.timers.register(_state_timer, first_interval=STATE_POLL_INTERVAL_SECONDS)
        _timer_registered = True


classes = (
    MIXAR_OT_web_publish,
    MIXAR_OT_web_cancel,
    MIXAR_OT_web_copy_link,
    MIXAR_OT_web_open,
    MIXAR_OT_web_unpublish,
    MIXAR_OT_web_clear_error,
)


def unregister():
    global _timer_registered
    try:
        if _timer_registered and bpy.app.timers.is_registered(_state_timer):
            bpy.app.timers.unregister(_state_timer)
    except Exception:  # noqa: BLE001
        pass
    _timer_registered = False
