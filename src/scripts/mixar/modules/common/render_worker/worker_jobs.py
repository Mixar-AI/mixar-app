# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Child side: run one job on a freshly loaded snapshot.

Each job loads its snapshot (``open_mainfile``), so no state of a previous job
(an inspection rig, a temporary export material) can leak into the next. The
job then runs the SAME client code the in-process path runs, with the
snapshot's copy of the user's scene as the context scene:

- ``preview``: ``preview_render.render_in_worker`` (engine, size, samples,
  device, geometry budget and the inspection rig exactly as the native job
  applies them; one synchronous render; the PNG).
- ``export``: ``export_package._export_in_process`` with the user's project
  folder standing in for the snapshot's.

The result is a JSON file in the job folder; the protocol line only names it.
Errors leave as fixed codes or the exporter's own message, as in-process.
"""

import json
import os
import time

import bpy


def restore_images(manifest_path: str) -> int:
    """Put the pixels of the parent's unsaved images back after the load."""
    if not manifest_path or not os.path.isfile(manifest_path):
        return 0
    import numpy as np

    folder = os.path.dirname(manifest_path)
    with open(manifest_path, encoding="utf-8") as handle:
        entries = json.load(handle)
    restored = 0
    for entry in entries:
        image = bpy.data.images.get(entry["name"])
        if image is None:
            continue
        width, height, channels = int(entry["width"]), int(entry["height"]), int(entry["channels"])
        try:
            if tuple(image.size) != (width, height) or not image.has_data or image.channels != channels:
                # The file on disk is missing or another size: hold the pixels as generated.
                image.source = "GENERATED"
                image.generated_width, image.generated_height = width, height
                image.use_generated_float = bool(entry.get("float"))
            buffer = np.fromfile(os.path.join(folder, entry["file"]), dtype=np.float32)
            if buffer.size != width * height * channels or image.channels != channels:
                continue
            image.pixels.foreach_set(buffer)
            image.update()
            restored += 1
        except (RuntimeError, ValueError, TypeError, AttributeError, OSError):
            continue
    return restored


def _crash_now():
    import ctypes
    ctypes.string_at(0)  # SIGSEGV in native code, like the crashes this guards against


def _context(job):
    scene = bpy.data.scenes.get(str(job.get("scene") or ""))
    if scene is None:
        raise LookupError("scene_unavailable")
    view_layer = scene.view_layers.get(str(job.get("view_layer") or "")) or scene.view_layers[0]
    return scene, view_layer


_INSPECTION_CODES = {'inspection_mode_unsupported', 'inspection_view_unsupported',
                     'inspection_focus_not_found', 'inspection_mark_unavailable'}


def render_preview(context, scene, view_layer, key="", width=0, height=0, engine="",
                   max_faces=0, inspection=None, use_gpu=None) -> dict:
    """The preview job on the snapshot: ``preview_render._configure`` (engine,
    size, samples, device, budget, inspection rig) applied to the scene itself
    (the snapshot is disposable: no private copy, nothing to restore), one
    synchronous render, the PNG via ``preview_render._read_png``. Returns the
    keys ``preview_render._finish`` publishes, minus what only the app knows
    (``preview_render._poll_worker`` adds those).

    Only ever in a worker: a synchronous render in the app would hold its main
    thread for the whole render (tests/test_render_job_guard.py)."""
    import base64
    from mixar.modules.space_mixie_chat.core import preview_render as pr

    if not bpy.app.background:
        raise RuntimeError("render_preview runs only in a background worker")
    job = {"inspection": None}

    def set_value(owner, name, value):
        setattr(owner, name, value)

    info = {}
    try:
        scene.render.use_persistent_data = False
        if inspection is not None:
            # As render_scene.create does for an inspection copy: the rig owns the look.
            scene.render.use_compositing = False
            scene.render.use_sequencer = False
        info = pr._configure(context, scene, scene, set_value, job, width, height, engine,
                             max_faces, inspection, use_gpu=use_gpu)
        kwargs = {"write_still": False, "scene": scene.name}
        if scene.render.use_single_layer:
            kwargs["layer"] = view_layer.name
        ret = bpy.ops.render.render(**kwargs)
        if "FINISHED" not in ret:
            raise RuntimeError("async_render_not_started")
        pixels = pr._read_png(scene)
        result = {"job_id": key, "status": "done", "render": info,
                  "image_url": "data:image/png;base64," + base64.b64encode(pixels).decode("ascii")}
    except Exception as exc:
        text = str(exc)
        code = (text if text in _INSPECTION_CODES or text == "image_too_large"
                else "preview_image_unavailable" if text == "missing_pixels"
                else "async_render_unavailable")
        result = {"job_id": key, "status": "failed", "error": code,
                  "render": info or pr._render_info(scene)}
    if job["inspection"] is not None:
        job["inspection"].finish(result)
    return result


def _run_preview(job, scene, view_layer):
    params = dict(job.get("params") or {})
    with bpy.context.temp_override(scene=scene, view_layer=view_layer):
        return render_preview(bpy.context, scene, view_layer, **params)


def _run_export(job, scene, view_layer):
    from mixar.modules.space_mixie_chat.core import export_package
    params = dict(job.get("params") or {})
    kwargs = dict(params.get("kwargs") or {})
    export_package.set_project_folder(params.get("project_dir") or "")
    export_package.set_telemetry_enabled(False)
    with bpy.context.temp_override(scene=scene, view_layer=view_layer):
        try:
            result = export_package._export_in_process(**kwargs)
            result["success"] = True
        except Exception as exc:  # the backend's own wrapper shape
            result = {"success": False, "error": type(exc).__name__ + ": " + str(exc)}
    return result


def run(job: dict) -> dict:
    """Run one job; returns ``{"ok", "out", "error", "seconds"}``."""
    started = time.perf_counter()
    seconds = {}
    out = str(job.get("out") or "")
    try:
        bpy.ops.wm.open_mainfile(filepath=str(job["snapshot"]), load_ui=False)
        restore_images(str(job.get("images") or ""))
        seconds["load"] = round(time.perf_counter() - started, 3)
        scene, view_layer = _context(job)
        if job.get("crash") == "segv":
            _crash_now()
        phase = time.perf_counter()
        if job.get("kind") == "preview":
            result = _run_preview(job, scene, view_layer)
        elif job.get("kind") == "export":
            result = _run_export(job, scene, view_layer)
        else:
            raise ValueError("unknown_job_kind")
        seconds["run"] = round(time.perf_counter() - phase, 3)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(result, handle)
        seconds["total"] = round(time.perf_counter() - started, 3)
        return {"ok": True, "out": out, "seconds": seconds}
    except LookupError:
        return {"ok": False, "error": "scene_unavailable", "seconds": seconds}
    except Exception:
        import traceback
        traceback.print_exc()  # to the worker log only
        return {"ok": False, "error": "worker_job_failed", "seconds": seconds}
