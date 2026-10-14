# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish orchestration shared by the panel operator and the agent API.

``begin_publish`` runs on Blender's main thread in the caller's context
(the operator's scene, or the scene an agent script runs in): it claims the
single publish slot, exports the GLB through the shared export lane, hashes
it, renders the thumbnail, and hands the upload to the worker thread. A
persistent timer mirrors ``PublishState`` into WindowManager RNA (progress,
for the panel and QA) and, once per outcome, writes the result onto the
scene that was published — resolved by name, never ``bpy.context.scene``,
so switching scene tabs mid-upload cannot misfile it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Dict, Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_
from mixar.modules.web_publish.constants import (
    DESCRIPTION_MAX_LENGTH,
    MAX_SCENE_BYTES,
    STATE_POLL_INTERVAL_SECONDS,
    TITLE_MAX_LENGTH,
    VISIBILITIES,
)
from mixar.modules.web_publish.core import glb_export, thumbnail, workspace
from mixar.modules.web_publish.core.publish_state import (
    STATUS_DONE,
    PublishJob,
    compute_sha256,
    derive_title,
    get_publish_state,
    viewer_config_block,
)

_logger = get_logger(__name__)
_MB = 1024 * 1024


def _refusal(template: str, **args) -> Dict[str, Any]:
    return {"ok": False, "error": template, "error_args": args}


def _telemetry(name: str, *args) -> None:
    """Content-free (``analytics/web_publish_events.py``); never breaks a publish."""
    try:
        from mixar.modules.common.analytics import web_publish_events

        getattr(web_publish_events, name)(*args, context=bpy.context)
    except Exception:  # noqa: BLE001
        pass


def _signed_in() -> bool:
    from mixar.modules.auth.core.auth import get_access_token

    return bool(get_access_token())


def begin_publish(context, *, title: Optional[str] = None, description: Optional[str] = None,
                  visibility: Optional[str] = None, update_existing: bool = False,
                  include_animation: Optional[bool] = None, via: str = "panel") -> Dict[str, Any]:
    """Start a publish. ``{"ok": True, "publish_id"}`` or ``{"ok": False,
    "error": <untranslated template>, "error_args": {...}}``."""
    scene = context.scene
    props = getattr(scene, "mixar_web_publish", None)
    if props is None:
        return _refusal(n_("Publish to Web is not available"))
    if not _signed_in():
        return _refusal(n_("Sign in to Mixar to publish scenes"))

    title = (title if title is not None else props.title).strip() or derive_title(scene.name)
    if len(title) > TITLE_MAX_LENGTH:
        return _refusal(n_("Titles are limited to {limit} characters"), limit=TITLE_MAX_LENGTH)
    description = (description if description is not None else props.description) or ""
    description = description.strip()[:DESCRIPTION_MAX_LENGTH]
    visibility = visibility if visibility in VISIBILITIES else props.visibility
    if include_animation is None:
        include_animation = bool(props.include_animation)
    if update_existing and not (props.published_scene_id and props.slug):
        return _refusal(n_("This scene has not been published yet"))
    meshes = glb_export.visible_meshes(scene)
    if not meshes:
        return _refusal(n_("No visible mesh objects to publish"))

    state = get_publish_state()
    publish_id = uuid.uuid4().hex
    if not state.begin(publish_id, scene.name, via):
        return _refusal(n_("A publish is already running"))
    state.set_status("EXPORTING", n_("Exporting scene…"), 0.01)
    _telemetry("capture_publish_started", via, bool(update_existing), bool(include_animation))

    folder, glb_path = workspace.make_export_workspace()
    try:
        result = glb_export.export_glb(glb_path, meshes, include_animation)
        state.set_warning(result.get("warning") or "")
        sha256, size = compute_sha256(glb_path)
        if size > MAX_SCENE_BYTES:
            raise _TooLarge(size)
        thumb = thumbnail.render_thumbnail(scene, workspace.thumbnail_path(folder))
        job = PublishJob(
            title=title, description=description, visibility=visibility,
            glb_path=glb_path, thumbnail_path=thumb or "", content_sha256=sha256,
            scene_meta=glb_export.collect_scene_meta(scene, meshes),
            viewer_config=viewer_config_block(glb_export.collect_camera_config(scene)),
            existing_scene_id=props.published_scene_id if update_existing else "",
            existing_slug=props.slug if update_existing else "",
        )
        from mixar.modules.web_publish.core.publish_api import ScenePublishService
        from mixar.modules.web_publish.core.upload_worker import spawn

        service = ScenePublishService()
    except _TooLarge as exc:
        return _fail(state, folder, n_("The scene is {size} MB; the publish limit is {limit} MB. "
                                       "Hide heavy objects or reduce texture resolution."),
                     size=exc.size // _MB, limit=MAX_SCENE_BYTES // _MB)
    except Exception as exc:  # noqa: BLE001 - report export problems inline
        _logger.warning("web_publish export failed: %s", exc)
        return _fail(state, folder, "{message}", message=str(exc) or exc.__class__.__name__)

    spawn(job, folder, service)
    ensure_timer()
    return {"ok": True, "publish_id": publish_id}


class _TooLarge(Exception):
    def __init__(self, size: int):
        super().__init__(size)
        self.size = size


def _fail(state, folder: str, template: str, **args) -> Dict[str, Any]:
    workspace.cleanup_workspace(folder)
    state.set_error(template, **args)
    ensure_timer()
    return _refusal(template, **args)


# ---------------------------------------------------------------------------
# State timer: PublishState → WindowManager RNA (+ scene result once) → redraw
# ---------------------------------------------------------------------------


def _mirror() -> Optional[float]:
    state = get_publish_state()
    progress, result = state.snapshot()
    wm = getattr(bpy.context, "window_manager", None)
    if wm is not None and hasattr(wm, "mixar_web_publish_status"):
        try:
            wm.mixar_web_publish_status = progress.status
            wm.mixar_web_publish_progress = progress.progress
            wm.mixar_web_publish_scene = state.scene_name
        except (AttributeError, TypeError, ValueError):
            pass
    if state.mark_applied():
        _apply_outcome(state.scene_name, state.via, progress, result)
    _redraw(wm)
    return STATE_POLL_INTERVAL_SECONDS if state.busy else None


def _apply_outcome(scene_name: str, via: str, progress, result) -> None:
    from mixar.modules.web_publish.core.agent_api import AGENT_STATUS

    _telemetry("capture_publish_finished", via, AGENT_STATUS.get(progress.status, "failed"))
    if progress.status != STATUS_DONE:
        return
    scene = bpy.data.scenes.get(scene_name) if scene_name else None
    props = getattr(scene, "mixar_web_publish", None) if scene else None
    if props is None or not result.slug:
        return
    props.published_scene_id = result.scene_id
    props.slug = result.slug
    props.share_url = result.share_url
    props.viewer_url = result.viewer_url
    props.revision = result.revision
    props.last_published = dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _redraw(wm) -> None:
    try:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:  # noqa: BLE001 - redraw is cosmetic
        pass


def ensure_timer() -> None:
    """(Re)start the mirror; ``is_registered`` survives a file load dropping it."""
    if not bpy.app.timers.is_registered(_mirror):
        bpy.app.timers.register(_mirror, first_interval=STATE_POLL_INTERVAL_SECONDS,
                                persistent=True)


def stop_timer() -> None:
    try:
        if bpy.app.timers.is_registered(_mirror):
            bpy.app.timers.unregister(_mirror)
    except Exception:  # noqa: BLE001
        pass
