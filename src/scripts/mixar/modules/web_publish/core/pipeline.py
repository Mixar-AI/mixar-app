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
so switching scene tabs mid-upload cannot misfile it. An outcome that
arrives after a file load (``load_pre`` bumps ``_load_generation``) is
dropped: the name may now belong to a different file's scene.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Dict, Optional

import bpy
from bpy.app.handlers import persistent

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

# Bumped by ``on_load_pre``: a publish begun under another generation
# belongs to a file that is no longer open.
_load_generation = 0
# The last outcome written onto a scene, re-applied when an undo/redo
# restores the pre-publish props (the timer's write is not an undo step).
_last_applied: Dict[str, Any] = {}


def _refusal(template: str, /, **args) -> Dict[str, Any]:
    return {"ok": False, "error": template, "error_args": args}


def _error_text(exc: BaseException) -> str:
    """Exception text without local paths (it reaches the agent/backend)."""
    try:
        from mixar.modules.space_mixie_chat.core.agent_export import scrub_error
    except Exception:  # noqa: BLE001 - the class name is always safe
        return exc.__class__.__name__
    return scrub_error(exc)


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
    if props is None:  # UI discovery has not run (headless worker)
        from mixar.modules.web_publish.core.registration import ensure_properties

        try:
            ensure_properties()
        except Exception as exc:  # noqa: BLE001 - reported as unavailable
            _logger.warning("web_publish property registration failed: %s", exc)
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
    if visibility not in VISIBILITIES:
        # An agent's new version keeps the site's access: the key is omitted
        # and the backend keeps the stored visibility.
        visibility = "" if (via == "agent" and update_existing) else props.visibility
    if include_animation is None:
        include_animation = bool(props.include_animation)
    from mixar.modules.web_publish.core.publish_api import valid_scene_id

    # The id comes from the .blend: anything but a UUID is no publication.
    existing_id = valid_scene_id(props.published_scene_id) if update_existing else ""
    if update_existing and not (existing_id and props.slug):
        return _refusal(n_("This scene has not been published yet"))
    meshes = glb_export.visible_meshes(scene)
    if not meshes:
        return _refusal(n_("No visible mesh objects to publish"))

    state = get_publish_state()
    publish_id = uuid.uuid4().hex
    if not state.begin(publish_id, scene.name, via, token=_load_generation):
        return _refusal(n_("A publish is already running"))
    _ensure_handlers()
    state.set_status("EXPORTING", n_("Exporting scene…"), 0.01)
    _telemetry("capture_publish_started", via, bool(update_existing), bool(include_animation))

    folder = ""
    try:
        folder, glb_path = workspace.make_export_workspace()
        result = glb_export.export_glb(glb_path, meshes, include_animation, scene)
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
            existing_scene_id=existing_id,
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
        return _fail(state, folder, "{message}", message=_error_text(exc))

    try:
        spawned = spawn(job, folder, service)
    except Exception as exc:  # noqa: BLE001 - a thread that never starts frees the slot
        return _fail(state, folder, n_("Publish failed ({kind})"), kind=exc.__class__.__name__)
    if not spawned:  # reported in the state, never silent
        ensure_timer()
        return _refusal(n_("The publish lost its claim before upload"))
    ensure_timer()
    return {"ok": True, "publish_id": publish_id}


class _TooLarge(Exception):
    def __init__(self, size: int):
        super().__init__(size)
        self.size = size


def _fail(state, folder: str, template: str, /, **args) -> Dict[str, Any]:
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
        _apply_outcome(state.scene_name, state.via, progress, result, state.token)
    _redraw(wm)
    return STATE_POLL_INTERVAL_SECONDS if state.busy else None


def _apply_outcome(scene_name: str, via: str, progress, result,
                   token: Optional[int] = None) -> None:
    from mixar.modules.web_publish.core.agent_api import AGENT_STATUS

    _telemetry("capture_publish_finished", via, AGENT_STATUS.get(progress.status, "failed"))
    if progress.status != STATUS_DONE:
        return
    if token is not None and token != _load_generation:
        # A file was loaded mid-upload: the scene name now resolves in
        # another file. The site exists; this file never asked for it.
        _logger.info("web_publish outcome dropped: a file was loaded during the upload")
        return
    scene = bpy.data.scenes.get(scene_name) if scene_name else None
    props = getattr(scene, "mixar_web_publish", None) if scene else None
    if props is None or not result.slug:
        return
    from mixar.modules.web_publish.core.links import safe_share_link

    fields = {"published_scene_id": result.scene_id, "slug": result.slug,
              "revision": result.revision,
              "last_published": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    for name in ("share_url", "viewer_url"):
        url = getattr(result, name)
        safe = safe_share_link(url) if url else ""
        if url and not safe:
            _logger.warning("web_publish refused to store an untrusted %s", name)
        fields[name] = safe
    _write_fields(props, fields)
    _last_applied.clear()
    _last_applied.update(scene_name=scene_name, token=token, fields=fields)


def _write_fields(props, fields: Dict[str, Any]) -> None:
    for name, value in fields.items():
        setattr(props, name, value)


def forget_applied() -> None:
    """Unpublish: an undo must never bring the removed site's record back."""
    _last_applied.clear()


def clear_publication(props) -> None:
    """Drop the scene's local site record (id, slug, links, revision)."""
    forget_applied()
    _write_fields(props, {"published_scene_id": "", "slug": "", "share_url": "",
                          "viewer_url": "", "revision": 0, "last_published": ""})


def unpublish(props, service=None):
    """Delete the scene's site and clear its record; returns the
    ``PublishApiError`` to report, or None. An id that is not a UUID (a
    crafted .blend) is never sent: the record is cleared locally."""
    from mixar.modules.web_publish.core.publish_api import (
        PublishApiError,
        ScenePublishService,
        valid_scene_id,
    )

    scene_id = valid_scene_id(props.published_scene_id)
    if scene_id:
        try:
            (service or ScenePublishService()).delete_scene(scene_id)
        except PublishApiError as exc:
            if exc.status_code != 404:  # already gone server-side: clear locally
                return exc
    else:
        _logger.warning("web_publish cleared a record with an invalid scene id")
    clear_publication(props)
    return None


# ---------------------------------------------------------------------------
# File load / undo handlers (registered by ``registration.ensure_handlers``)
# ---------------------------------------------------------------------------


@persistent
def on_load_pre(*_args) -> None:
    global _load_generation
    _load_generation += 1
    _last_applied.clear()


@persistent
def on_undo_redo(*_args) -> None:
    """Undo/redo restores the scene props from before the timer wrote the
    outcome; put the live site's record back (only into a blank record, on
    the same file, for the scene that was published)."""
    if not _last_applied or _last_applied.get("token") != _load_generation:
        return
    try:
        scene = bpy.data.scenes.get(_last_applied.get("scene_name") or "")
        props = getattr(scene, "mixar_web_publish", None) if scene else None
        if props is not None and not props.published_scene_id:
            _write_fields(props, _last_applied["fields"])
    except Exception as exc:  # noqa: BLE001 - a handler must never raise
        _logger.warning("web_publish undo re-apply failed: %s", exc)


def _ensure_handlers() -> None:
    try:
        from mixar.modules.web_publish.core.registration import ensure_handlers

        ensure_handlers()
    except Exception as exc:  # noqa: BLE001 - publishing works without them
        _logger.warning("web_publish handler registration failed: %s", exc)


def _redraw(wm) -> None:
    try:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
            # Popovers live outside areas. Refresh this panel's layout so
            # async progress and completion appear without pointer movement.
            refresh = getattr(window, "mixar_refresh_popover", None)
            if refresh is not None:
                refresh("MIXAR_PT_web_publish")
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
