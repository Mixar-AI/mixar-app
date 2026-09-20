# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asynchronous verification preview for the agent's ``render_viewport``
tool (``quality="final"``).

``start()`` kicks off Blender's ordinary interactive render job (the F12
machinery, ``INVOKE_DEFAULT``) on the agent's scene and returns at once;
``poll()`` reports the job's state and, once the pixels exist, the PNG as a
data URL. The executor's deferral (``preview_deferral.py``) keeps the tool
call open and polls on a timer, so the chat, the UI and every other agent
script keep running while the render works on its own depsgraph.

Thread rules (docs/render-job-contract.md):

- ``render_complete`` / ``render_cancel`` fire ON the render job thread. The
  handlers here only mark the job and register a one-shot ``bpy.app.timers``
  callback; ``_finish`` does every ``bpy.data`` / RNA write on the main thread
  and waits until the WM job has torn down before reading the Render Result.
- ``poll()`` is cheap: no ``view_layer.update()``; a depsgraph revision counter
  (VIEWPORT updates only) is what decides ``scene_advanced``.
- Lock Interface and Preferences are never written. Every temporary render
  setting is restored on every exit path, each only if it still holds the
  value we applied (a user's own change during the job wins).
- Error codes are fixed strings; no path or exception text leaves this module.
"""

import base64
import re
import tempfile
import time

import bpy
from bpy.app.handlers import persistent

RESULTS_NS = "mixie_agent_preview"
MAX_EDGE_PX = 768
MAX_PNG_BYTES = 4_000_000
MAX_RESULTS = 4
LOST_AFTER_S = 2.0
CYCLES_SAMPLE_CAP = 32
EEVEE_SAMPLE_CAP = 16
_EEVEE_ENGINES = ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT")

_job = None        # the ONE in-flight job dict, main thread only
_revision = 0      # VIEWPORT depsgraph updates seen so far
_records = {}      # key -> terminal result, bounded to MAX_RESULTS


def _scene_session(scene) -> str:
    try:
        return getattr(scene, "mixie_session_id", "") or scene.get("mixie_session_id") or ""
    except Exception:
        return ""


def _render_info(scene) -> dict:
    """Engine / device / samples / size the job runs with (plain values only)."""
    render = scene.render
    engine = str(render.engine)
    info = {"engine": engine, "device": "engine_default", "samples": None,
            "width": int(render.resolution_x), "height": int(render.resolution_y),
            "elapsed_seconds": None}
    if engine == "CYCLES":
        info["device"] = str(getattr(scene.cycles, "device", "CPU"))
        info["samples"] = int(getattr(scene.cycles, "samples", 0))
    elif engine in _EEVEE_ENGINES:
        samples = getattr(getattr(scene, "eevee", None), "taa_render_samples", None)
        info["samples"] = int(samples) if samples is not None else None
    return info


@persistent
def _changed(_scene, depsgraph):
    global _revision
    # The render evaluates its own graph; only viewport changes invalidate it.
    if depsgraph.mode == "VIEWPORT" and depsgraph.updates:
        _revision += 1


def _publish(key, value):
    _records[key] = value
    # Only a few bounded PNGs may remain in client memory.
    while len(_records) > MAX_RESULTS:
        del _records[next(iter(_records))]
    bpy.app.driver_namespace[RESULTS_NS] = _records


def _restore(job):
    for owner, name, original, applied in reversed(job["settings"]):
        try:
            # Preserve a user's new setting if it changed while the job ran.
            if getattr(owner, name) == applied:
                setattr(owner, name, original)
        except (ReferenceError, RuntimeError, AttributeError):
            pass
    # Flush our own writes so they are counted in the revision NOW, before the
    # baseline is taken — otherwise the restore itself reads as a scene change.
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


def _remove_render_handlers():
    for handlers, callback in ((bpy.app.handlers.render_complete, _complete),
                               (bpy.app.handlers.render_cancel, _cancelled)):
        if callback in handlers:
            handlers.remove(callback)


def _read_png(scene) -> bytes:
    image = bpy.data.images.get("Render Result")
    if image is None or not image.has_data:
        raise RuntimeError("missing_pixels")
    with tempfile.TemporaryDirectory(prefix="mixar_preview_") as folder:
        path = folder + "/preview.png"
        fmt = scene.render.image_settings.file_format
        try:
            scene.render.image_settings.file_format = "PNG"
            image.save_render(path, scene=scene)
        finally:
            scene.render.image_settings.file_format = fmt
        with open(path, "rb") as handle:
            pixels = handle.read(MAX_PNG_BYTES + 1)
    if len(pixels) > MAX_PNG_BYTES:
        raise RuntimeError("image_too_large")
    return pixels


def _finish(key, completed, lost=False):
    """Main-thread completion: read pixels, restore settings, publish."""
    global _job
    if _job is None or _job["key"] != key:
        return None
    # render_complete precedes WM job teardown. Do not read Render Result early.
    if not lost and bpy.app.is_job_running("RENDER"):
        return 0.1
    job = _job
    scene = job["scene"]
    result = {"job_id": key, "status": "lost" if lost else "cancelled",
              "render_revision": job["revision"], "scene_session": job["scene_session"]}
    try:
        if completed:
            pixels = _read_png(scene)
            result.update(status="done", scene_advanced=_revision != job["revision"],
                          image_url="data:image/png;base64,"
                          + base64.b64encode(pixels).decode("ascii"))
    except Exception as exc:
        # Errors can embed local temp paths. Only fixed codes leave this module.
        code = "image_too_large" if str(exc) == "image_too_large" else "preview_image_unavailable"
        result.update(status="failed", error=code)
    finally:
        try:
            _restore(job)
        except (ReferenceError, RuntimeError):
            result.update(status="failed", error="scene_unavailable")
            result.pop("image_url", None)
        _job = None
        _remove_render_handlers()
        result["scene_revision"] = _revision
        result["render"] = dict(job["render"],
                                elapsed_seconds=round(time.monotonic() - job["started_at"], 3))
        _publish(key, result)
    return None


def _schedule(completed):
    # Called on Blender's render job thread: touch plain Python state only,
    # then schedule the RNA/image work on a main-loop timer.
    job = _job
    if job is not None:
        job["finishing"] = True
        key = job["key"]
        bpy.app.timers.register(lambda: _finish(key, completed), first_interval=0.1)


@persistent
def _complete(_scene, _depsgraph=None):
    _schedule(True)


@persistent
def _cancelled(_scene, _depsgraph=None):
    _schedule(False)


@persistent
def _before_load(_unused, _extra=None):
    global _job, _revision
    _job = None
    _revision += 1
    _records.clear()
    _remove_render_handlers()


def _install():
    for handlers, callback in ((bpy.app.handlers.depsgraph_update_post, _changed),
                               (bpy.app.handlers.load_pre, _before_load)):
        if callback not in handlers:
            handlers.append(callback)


def poll(key):
    """Read-only state delivery, including changes since render completion."""
    if _job is not None and _job["key"] == key:
        if (not _job["finishing"] and time.monotonic() - _job["started_at"] > LOST_AFTER_S
                and not bpy.app.is_job_running("RENDER")):
            _finish(key, False, lost=True)  # completion was lost: self-heal
        else:
            return {"job_id": key, "status": "running", "render_revision": _job["revision"],
                    "scene_session": _job["scene_session"], "render": dict(_job["render"])}
    value = dict(_records.get(key) or {"job_id": key, "status": "lost"})
    if value.get("status") == "done" and value.get("scene_revision") != _revision:
        value["scene_advanced"] = True
    return value


def _apply_settings(scene, set_value):
    render = scene.render
    scale = min(1.0, MAX_EDGE_PX / max(render.resolution_x, render.resolution_y, 1))
    set_value(render, "resolution_x", max(1, round(render.resolution_x * scale)))
    set_value(render, "resolution_y", max(1, round(render.resolution_y * scale)))
    set_value(render, "resolution_percentage", 100)
    set_value(render.image_settings, "file_format", "PNG")
    engine = str(render.engine)
    if engine == "CYCLES":
        set_value(scene.cycles, "samples", min(scene.cycles.samples, CYCLES_SAMPLE_CAP))
    elif engine in _EEVEE_ENGINES:
        eevee = getattr(scene, "eevee", None)
        samples = getattr(eevee, "taa_render_samples", None)
        if samples is not None:
            set_value(eevee, "taa_render_samples", min(samples, EEVEE_SAMPLE_CAP))


def start(context, key):
    """Start the preview job for ``key``; idempotent for a key already seen."""
    global _job
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key):
        return {"job_id": str(key)[:64], "status": "failed", "error": "invalid_job_id"}
    _install()
    if key in _records or (_job is not None and _job["key"] == key):
        return poll(key)  # never restart a job the backend already has
    if _job is not None:
        poll(_job["key"])  # recover a lost completion before deciding it is busy
    if _job is not None or bpy.app.is_job_running("RENDER"):
        return {"job_id": key, "status": "busy", "error": "another_render_running"}
    scene = context.scene
    if scene is None:
        return {"job_id": key, "status": "failed", "error": "scene_unavailable"}
    session = _scene_session(scene)
    win = context.window or next(iter(context.window_manager.windows), None)
    if scene.camera is None or win is None or bpy.app.background:
        return {"job_id": key, "status": "failed", "error": "camera_and_window_required",
                "scene_session": session, "render": _render_info(scene)}
    settings = []

    def set_value(owner, name, value):
        settings.append((owner, name, getattr(owner, name), value))
        setattr(owner, name, value)

    job = {"key": key, "scene": scene, "settings": settings, "started_at": time.monotonic(),
           "revision": _revision, "finishing": False, "scene_session": session, "render": {}}
    _job = job
    try:
        _apply_settings(scene, set_value)
        job["render"] = _render_info(scene)
        bpy.app.handlers.render_complete.append(_complete)
        bpy.app.handlers.render_cancel.append(_cancelled)
        # The pixels go to the agent; never open an image-editor window.
        view = context.preferences.view
        display = view.render_display_type
        try:
            view.render_display_type = "NONE"
            with bpy.context.temp_override(window=win, scene=scene):
                ret = bpy.ops.render.render("INVOKE_DEFAULT", write_still=False)
        finally:
            view.render_display_type = display
        if "RUNNING_MODAL" not in ret:
            raise RuntimeError("async_render_not_started")
        # Flush our own setting writes before taking the revision baseline.
        bpy.context.view_layer.update()
        job["revision"] = _revision
        return {"job_id": key, "status": "running", "render_revision": _revision,
                "scene_session": session, "render": dict(job["render"])}
    except Exception:
        _remove_render_handlers()
        _restore(job)
        _job = None
        value = {"job_id": key, "status": "failed", "error": "async_render_unavailable",
                 "scene_session": session, "render": job["render"] or _render_info(scene)}
        _publish(key, value)
        return value
