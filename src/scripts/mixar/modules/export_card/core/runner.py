# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The card's Export button: validate the destination, then hand the work to
the lane that owns it.

- 3D model → `agent_export.export_to_path` (presets, clip selection,
  material swap, re-import verification) with the card's settings pinned;
- Mixar project / Blender file → `project_save.save_copy`;
- Image / Video → `scene_render.jobs.start` saving to the chosen file (a
  native background render: the app stays live while it runs);
- Publish to Web → the web_publish pipeline (`mixar.web_publish`).

Native exporters must run on the main thread, so a model or project export
is deferred ONE timer tick after the click: the card first paints its busy
pill (state RUNNING), then the export runs and the card lands on DONE or
ERROR. ``begin`` never raises into the operator."""

from __future__ import annotations

import os
import uuid

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from .. import constants as C
from . import destination, project_save, state, targets
from . import spec as card_spec

logger = get_logger(__name__)
DEFER_SECONDS = 0.05


def _redraw():
    """Rebuild the open card: pop-up regions sit outside every area, so an
    ``area.tag_redraw()`` never reaches them and a state flipped from a timer
    stayed invisible until the pointer moved (native `mixar_refresh_popups`)."""
    try:
        from mixar.modules.common.utils.platform_utils import refresh_popup_dialogs
        refresh_popup_dialogs()
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:  # noqa: BLE001
        pass


def output_path(p) -> tuple[str, str, str]:
    """(folder, stem, full path) the card would write now."""
    extension = targets.extension(p.target, p.gltf_file, p.usd_file, p.render_format)
    folder = bpy.path.abspath(p.folder) if p.folder.startswith("//") else p.folder
    stem = destination.clean_stem(p.file_name, extension)
    return folder, stem, destination.full_path(folder, stem, extension)


def _fail(p, msgid, detail="", **args):
    p.state = C.ERROR
    state.set_result(kind="error", error=msgid, error_args=args, detail=detail)
    _redraw()


def begin(context, p, replace=False) -> None:
    """The Export button. Leaves the card in RUNNING, DONE, ERROR or (a file
    of that name exists) CONFIRM."""
    if p.target == C.WEB:
        _publish_web(context)
        return
    folder, stem, path = output_path(p)
    problem = destination.problem(folder, p.file_name)
    if problem:
        _fail(p, problem)
        return
    if not replace and os.path.exists(path):
        p.state = 'CONFIRM'
        state.set_result(kind="confirm", name=os.path.basename(path), folder=folder, path=path)
        return
    try:
        destination.ensure_folder(folder)
    except OSError as exc:
        _fail(p, n_("Could not create the folder ({error})."), error=type(exc).__name__)
        return
    if p.target in C.RENDER_TARGETS:
        _start_render(context, p, path)
        return
    p.state = C.RUNNING
    state.set_result(kind="running", name=os.path.basename(path), folder=folder, path=path)
    window = context.window
    target = p.target

    def _deferred():
        try:
            if window is not None and window in bpy.context.window_manager.windows[:]:
                with bpy.context.temp_override(window=window):
                    _run_export(bpy.context.window_manager.mixar_export_card, target, path)
            else:
                _run_export(bpy.context.window_manager.mixar_export_card, target, path)
        except Exception:  # noqa: BLE001 - the card must never stay busy
            logger.exception("Export card export failed")
            _fail(bpy.context.window_manager.mixar_export_card,
                  n_("The export stopped unexpectedly. Try again."))
        return None

    bpy.app.timers.register(_deferred, first_interval=DEFER_SECONDS)


def _run_export(p, target, path):
    folder, name = os.path.dirname(path), os.path.basename(path)
    if target in C.PROJECT_TARGETS:
        result = project_save.save_copy(path, p.project_strip_chat, p.project_compress)
        _project_telemetry(target, result, p)
        if not result["success"]:
            _fail(p, n_("Could not save the copy."), detail=result["error"])
            return
        state.set_result(kind="file", name=name, folder=folder, path=path,
                         size=result["size"], dropped=result["dropped"])
    else:
        from mixar.modules.space_mixie_chat.core.agent_export import export_to_path
        stem = os.path.splitext(name)[0]
        result = export_to_path(path, card_spec.model_spec(p, stem), via="export_card",
                                tool="export_card", overrides=card_spec.overrides(p))
        if not result.get("success"):
            _fail(p, n_("The export did not finish."), detail=str(result.get("error") or ""))
            return
        verification = result.get("verification") or {}
        state.set_result(kind="file", name=name, folder=folder, path=path,
                         size=int(result.get("file_size_bytes") or 0),
                         meshes=int(result.get("mesh_count") or 0),
                         warning=str(result.get("warning") or ""),
                         checked=bool(verification.get("checked")),
                         passed=bool(verification.get("passed")),
                         non_manifold=int(verification.get("non_manifold_edges") or 0))
    p.state = C.DONE
    _redraw()


def _project_telemetry(target, result, p):
    try:
        from mixar.modules.common.analytics.export_events import capture_export
        capture_export(bpy.context, export_format="MIXAR" if target == C.MIXAR else "BLEND",
                       success=bool(result["success"]), extension=targets.extension(target),
                       extra={"via": "export_card", "tool": "export_card",
                              "chat_removed": bool(p.project_strip_chat),
                              "file_size_kb": int(result.get("size", 0) // 1024)})
    except Exception:  # noqa: BLE001
        pass


def _start_render(context, p, path):
    from mixar.modules.scene_render.core import jobs
    kind = 'video' if p.target == C.VIDEO else 'image'
    value = jobs.start(context, uuid.uuid4().hex, kind, label=os.path.basename(path),
                       destination=path, **card_spec.render_options(p))
    status = value.get("status")
    if status == 'started':
        p.state = C.DONE
        state.set_result(kind="render", name=os.path.basename(path),
                         folder=os.path.dirname(path), path=path, video=kind == 'video',
                         job_id=value.get("job_id", ""))
        return
    errors = {
        "another_render_running": n_("Another render is running. Try again when it finishes."),
        "camera_and_window_required": n_("Add a camera to the scene first."),
        "animation_range_required": n_("Set an end frame after the start frame."),
        "invalid_render_settings": n_("Check the size, frames and frame rate."),
    }
    _fail(p, errors.get(value.get("error"), n_("The render could not start. Try again.")))


def _publish_web(context):
    try:
        if bpy.ops.mixar.web_publish.poll():
            bpy.ops.mixar.web_publish('EXEC_DEFAULT')
    except Exception:  # noqa: BLE001 - the publish reports its own errors
        logger.exception("Publish to Web from the Export card failed")
