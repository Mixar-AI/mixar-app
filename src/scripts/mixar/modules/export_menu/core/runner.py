# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run the Export sheet's choice through the pipeline each format already has.

* 3D files and the game engines: the agent export lane
  (``agent_export.export_to_path``: use-case presets, clip selection,
  verification, private-extras stripping, telemetry).
* ``.blend`` / ``.mixar``: a copy save of the open file, optionally without
  the agent chat (the same snapshot / strip / restore as File ▸ Export ▸
  "Export .blend without chat history").
* Image and video: a ``scene_render`` job (async native render, user
  settings restored afterwards) delivered to the file instead of Moodboard.

Files go to the user's Downloads folder, never overwriting one that exists.
A model or project export is deferred to a timer so the sheet closes and a
progress toast draws before the main thread is busy writing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from contextlib import nullcontext

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_, rpt_

from ..constants import (
    BY_KEY,
    EXTENSIONS,
    KIND_IMAGE,
    KIND_MODEL,
    KIND_PROJECT,
    KIND_VIDEO,
    KIND_WEB,
    RENDER_QUALITY,
    TOAST_ID,
)

logger = get_logger(__name__)
_last_path = ""


# ---------------------------------------------------------------------------
# Names and paths
# ---------------------------------------------------------------------------

def default_stem(context) -> str:
    """The open file's name, else the scene's."""
    path = bpy.data.filepath
    if path:
        return os.path.splitext(os.path.basename(path))[0]
    scene = getattr(context, "scene", None)
    return scene.name if scene is not None else "export"


def file_format(props) -> str:
    """The file format the current choice writes (an ``EXTENSIONS`` key)."""
    fmt = BY_KEY[props.format]
    if props.format == "GLB":
        return props.gltf_variant
    if fmt.use_case in ("unreal", "unity"):
        return props.engine_format
    if fmt.kind == KIND_IMAGE:
        return props.image_format
    if fmt.kind == KIND_VIDEO:
        return props.video_format
    return props.format


def extension(props) -> str:
    return EXTENSIONS.get(file_format(props), "")


def output_folder() -> str:
    from mixar.modules.space_mixie_chat.core.agent_export import resolve_export_folder
    return resolve_export_folder("downloads")


def stem(props, context) -> str:
    from mixar.modules.space_mixie_chat.core.agent_export import safe_stem
    return safe_stem(props.file_name.strip() or default_stem(context), extension(props))


def unique_path(folder: str, name: str, ext: str) -> str:
    candidate = os.path.join(folder, name + ext)
    index = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{name}_{index}{ext}")
        index += 1
    return candidate


# ---------------------------------------------------------------------------
# Readiness (drawn by the sheet, re-checked before running)
# ---------------------------------------------------------------------------

def blocker(props, context) -> str:
    """Why the current choice cannot export right now (an ``n_`` msgid), or ""."""
    kind = BY_KEY[props.format].kind
    scene = getattr(context, "scene", None)
    if scene is None:
        return n_("Open a scene to export")
    if kind == KIND_MODEL:
        if props.selected_only:
            if not context.selected_objects:
                return n_("Select the objects to export, or turn off Selected objects only")
        elif not any(obj.type == 'MESH' for obj in scene.objects):
            return n_("This scene has no meshes to export")
    if kind in (KIND_IMAGE, KIND_VIDEO):
        if scene.camera is None:
            return n_("Add a camera: images and videos render from the scene camera")
        if kind == KIND_VIDEO and scene.frame_start >= scene.frame_end:
            return n_("Set an animation range of more than one frame to render a video")
        try:
            from mixar.modules.common.render_coordinator import core as slot
            if slot.busy():
                return n_("Another render is running; wait for it to finish")
        except Exception:  # noqa: BLE001 - a missing coordinator never blocks
            pass
    return ""


# ---------------------------------------------------------------------------
# Toasts and reveal
# ---------------------------------------------------------------------------

def _toast(kind, title, body="", ttl_ms=8000, reveal=False):
    try:
        from mixar.modules.common.notifications import get_notification_store
        from mixar.modules.common.notifications.store import NotificationAction
        actions = ([NotificationAction(label=n_("Show in Folder"),
                                       operator="mixar.export_menu_reveal")]
                   if reveal else None)
        get_notification_store().push(kind, title, body=body, id=TOAST_ID, ttl_ms=ttl_ms,
                                      actions=actions)
    except Exception:  # noqa: BLE001 - a toast is cosmetic
        logger.exception("Export toast failed")


def reveal_last() -> bool:
    """Show the last exported file in the system file browser."""
    path = _last_path
    if not path or not os.path.exists(path):
        return False
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except OSError:
        return False
    return True


def _finish(path, ok, error=""):
    global _last_path
    name = os.path.basename(path)
    if ok:
        _last_path = path
        _toast("success", rpt_("Exported {name}").format(name=name),
               rpt_("Saved to {folder}").format(folder=os.path.basename(os.path.dirname(path))),
               reveal=True)
    else:
        _toast("error", rpt_("Could not export {name}").format(name=name), error)


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

def _model_spec(props, context, fmt_key):
    from mixar.modules.space_mixie_chat.core.export_preflight import resolve_targets
    fmt = BY_KEY[props.format]
    scope = "selected" if props.selected_only else "scene"
    # Resolve now and carry the names: the lane would otherwise reuse a
    # mesh list remembered from an earlier export of the same scope.
    meshes = resolve_targets(scope)
    spec = {
        "format": fmt_key.lower(),
        "use_case": fmt.use_case,
        "target_scope": scope,
        "mesh_names": [obj.name for obj in meshes],
    }
    if not props.include_animation:
        spec["animations"] = []
    return spec


def _export_model(path, spec):
    from mixar.modules.space_mixie_chat.core.agent_export import export_to_path
    result = export_to_path(path, spec, via="export_menu", tool="export_menu")
    if not result.get("success"):
        return False, str(result.get("error") or "")
    return True, ""


def _export_project(path, strip_chat):
    try:
        from mixar.modules.agent_bubble.core.bubble_lifecycle import keep_windows_for_snapshot
    except Exception:  # noqa: BLE001 - without the island there is nothing to keep
        keep_windows_for_snapshot = nullcontext
    snapshot = None
    scenes = list(bpy.data.scenes)
    try:
        if strip_chat:
            from mixar.modules.space_mixie_chat.ui.operators.export_ops import (
                _snapshot_chat, _strip_chat,
            )
            snapshot = _snapshot_chat(scenes)
            _strip_chat(scenes)
        # A copy keeps the island open (its windows are never written) and
        # skips the EEVEE thumbnail render, which held saves for seconds.
        kwargs = {"filepath": path, "copy": True, "compress": True}
        with keep_windows_for_snapshot():
            try:
                bpy.ops.wm.save_as_mainfile(thumbnail=False, **kwargs)
            except TypeError:
                bpy.ops.wm.save_as_mainfile(**kwargs)
    except Exception as exc:  # noqa: BLE001 - reported in the toast
        return False, str(exc)
    finally:
        if snapshot is not None:
            from mixar.modules.space_mixie_chat.ui.operators.export_ops import _restore_chat
            _restore_chat(snapshot)
    return True, ""


def render_options(props, context, kind):
    quality = RENDER_QUALITY[props.quality]
    r = context.scene.render
    scale = quality["scale"]
    samples = quality.get("video_samples", quality["samples"]) if kind == KIND_VIDEO \
        else quality["samples"]
    pct = r.resolution_percentage / 100.0
    # Even sizes: H.264 refuses odd frame dimensions.
    width = max(2, int(r.resolution_x * pct * scale) // 2 * 2)
    height = max(2, int(r.resolution_y * pct * scale) // 2 * 2)
    return {"engine": quality["engine"], "samples": samples, "width": width, "height": height}


def _start_render(props, context, path, kind):
    from mixar.modules.scene_render.core import jobs
    container = {"PNG": "PNG", "WEBP": "WEBP", "MP4": "MPEG4", "WEBM": "WEBM"}[file_format(props)]
    value = jobs.start(context, uuid.uuid4().hex, kind="video" if kind == KIND_VIDEO else "image",
                       label=os.path.basename(path), destination=path, container=container,
                       **render_options(props, context, kind))
    if value.get("status") == "started":
        global _last_path
        _last_path = path
        return True, ""
    return False, str(value.get("error") or "")


def _deferred(job):
    """Timer body: the sheet has closed and the toast has drawn."""
    path, kind = job["path"], job["kind"]
    try:
        if kind == KIND_PROJECT:
            ok, error = _export_project(path, job["strip_chat"])
        else:
            ok, error = _export_model(path, job["spec"])
    except Exception as exc:  # noqa: BLE001 - never leave the toast spinning
        logger.exception("Export sheet run failed")
        ok, error = False, str(exc)
    _finish(path, ok, error)
    return None


def start(props, context):
    """Run the current choice; returns ``(ok, message)`` for the operator's
    report. Web is not run here (the sheet publishes in place)."""
    kind = BY_KEY[props.format].kind
    if kind == KIND_WEB:
        return False, n_("Publish to Web runs from its own button")
    reason = blocker(props, context)
    if reason:
        return False, reason
    folder = output_folder()
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return False, n_("The Downloads folder is not writable")
    path = unique_path(folder, stem(props, context), extension(props))
    if kind in (KIND_IMAGE, KIND_VIDEO):
        ok, error = _start_render(props, context, path, kind)
        if not ok:
            _toast("error", rpt_("Could not export {name}").format(name=os.path.basename(path)),
                   error)
        return ok, error
    job = {"path": path, "kind": kind, "strip_chat": props.strip_chat}
    if kind == KIND_MODEL:
        try:
            job["spec"] = _model_spec(props, context, file_format(props))
        except ValueError as exc:
            return False, str(exc)
    _toast("info", rpt_("Exporting {name}…").format(name=os.path.basename(path)), ttl_ms=0)
    bpy.app.timers.register(lambda: _deferred(job), first_interval=0.05)
    return True, ""
