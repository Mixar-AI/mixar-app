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
- The job renders a private copy of the scene (``render_scene.py``): a
  Rendered viewport follows the scene engine and went black on every switch.
- Undo settles the job in ``undo_pre`` (``_before_undo``), never later.
- The engine and the size come from the CALL (the backend's
  ``render_viewport(quality="final", engine=..., width=..., height=...)``);
  the DEVICE never does. ``scene.cycles.device`` is set to ``'GPU'`` for the
  job only when ``render_device.use_gpu()`` says the user's
  ``default_render_device`` preference allows it AND a compute device is
  actually enabled — the enabling itself happens once at startup in
  ``bootstrap/render_device_module.py``, never here.
- Error codes are fixed strings; no path or exception text leaves this module.
"""

import base64
import re
import tempfile
import time

import bpy
from bpy.app.handlers import persistent

from . import render_device, render_scene
from mixar.modules.common.render_coordinator import core as render_slot

RESULTS_NS = "mixie_agent_preview"
# The preview cap: a call that names no size keeps the scene's aspect scaled
# under this. A call that DOES name one is a final render and gets the size it
# asked for, up to FINAL_MAX_EDGE_PX.
MAX_EDGE_PX = 768
FINAL_MAX_EDGE_PX = 1920
# Bound encoded results independently of dimensions: noisy frames can be much
# larger than typical previews. Base64 still fits under the 16 MiB WS limit.
MAX_PNG_BYTES = 8_000_000
# save_render runs on the UI thread after the native render job finishes.
# Use Blender's fast default: maximum compression can stall a large preview
# for seconds. Compression changes file size, never the decoded pixels.
PNG_COMPRESSION = 15
MAX_RESULTS = 4
LOST_AFTER_S = 2.0
CYCLES_SAMPLE_CAP = 32
# An explicitly requested Cycles final is the one render the user asked to be
# slow; it still may not run away, so the scene's own samples are capped here.
CYCLES_FINAL_SAMPLE_CAP = 128
EEVEE_SAMPLE_CAP = 16
# 'BLENDER_EEVEE' IS EEVEE Next in 4.2+/5.x; the _NEXT id exists only in 4.2-4.5.
_EEVEE_ENGINES = ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT")
_ENGINE_REQUESTS = {"auto": ("CYCLES",), "eevee": _EEVEE_ENGINES, "cycles": ("CYCLES",)}

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
    entries = list(reversed(job["settings"]))
    # Blender filters file_format by media_type: a video scene's FFMPEG is only
    # accepted once media_type is back to VIDEO, so that entry goes first.
    entries.sort(key=lambda entry: entry[1] != "media_type")
    for owner, name, original, applied in entries:
        try:
            # Preserve a user's new setting if it changed while the job ran.
            if getattr(owner, name) == applied:
                setattr(owner, name, original)
        except (ReferenceError, RuntimeError, AttributeError, TypeError):
            pass
    if job.get('inspection') is not None:
        job['inspection'].cleanup()
    render_scene.remove(job.get('render_scene'))
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


def _read_png(scene, require_loaded=True) -> bytes:
    image = bpy.data.images.get("Render Result")
    # In a --background worker the Render Result holds pixels that has_data
    # does not report (no image buffer is acquired); save_render reads them.
    if image is None or (require_loaded and not image.has_data):
        raise RuntimeError("missing_pixels")
    with tempfile.TemporaryDirectory(prefix="mixar_preview_") as folder:
        path = folder + "/preview.png"
        settings = scene.render.image_settings
        fmt, compression = settings.file_format, settings.compression
        try:
            settings.file_format = "PNG"
            settings.compression = PNG_COMPRESSION
            image.save_render(path, scene=scene)
        finally:
            settings.file_format = fmt
            settings.compression = compression
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
    render_slot.phase(job["reservation"], "finalizing")
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
            try:
                try:
                    if job.get('inspection') is not None:
                        result['render'] = job['render']
                        job['inspection'].finish(result)
                finally:
                    _restore(job)
            except Exception:
                result.update(status="failed", error="scene_unavailable")
                result.pop("image_url", None)
                result.pop("image_base64", None)
            _job = None
            _remove_render_handlers()
            result["scene_revision"] = _revision
            result["render"] = dict(job["render"],
                                    elapsed_seconds=round(time.monotonic() - job["started_at"], 3))
            _publish(key, result)
        finally:
            render_slot.release(job["reservation"])

    return None


def _schedule(completed):
    # Called on Blender's render job thread: touch plain Python state only,
    # then schedule the RNA/image work on a main-loop timer.
    job = _job
    if job is not None:
        job["finishing"] = True
        job["completed"] = completed
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
    if _job is not None:
        if _job.get("worker"):
            _drop_worker_job(_job)
        else:
            render_slot.release(_job["reservation"])
    _job = None
    _forget_worker_snapshots()
    _revision += 1
    _records.clear()
    _remove_render_handlers()


@persistent
def _sweep_render_scenes(*_args):
    """Undo, a checkpoint restore or a file saved mid-render can bring back a
    private render scene after its job ended: remove all but the live one."""
    try:
        render_scene.sweep(keep=_job.get('render_scene') if _job is not None else None)
    except Exception:
        pass


@persistent
def _before_undo(*_args):
    """Undo has already killed the job (``WM_jobs_kill_all``) and frees the data
    only after this handler: settle now, while the copy and rig are still valid.
    A later ``_finish`` would write through dangling references and crash."""
    if _job is not None and not _job.get("worker"):
        # A worker job renders its own snapshot: undo changes nothing it uses.
        _finish(_job["key"], _job.get("completed", False))


def _install():
    for handlers, callback in ((bpy.app.handlers.depsgraph_update_post, _changed),
                               (bpy.app.handlers.load_pre, _before_load),
                               (bpy.app.handlers.load_post, _sweep_render_scenes),
                               (bpy.app.handlers.undo_pre, _before_undo),
                               (bpy.app.handlers.redo_pre, _before_undo),
                               (bpy.app.handlers.undo_post, _sweep_render_scenes),
                               (bpy.app.handlers.redo_post, _sweep_render_scenes)):
        if callback not in handlers:
            handlers.append(callback)


def _release_route_pin(source, scene) -> bool:
    """Put a routed script's window back on the user's tab before the invoke.

    Left to the executor's restore after the script, that scene switch freed the
    job's RenderEngine mid-start (``main_thread_routing.release_pin``). Only for a
    job on the private copy, which the operator names itself, and only when the
    tab it returns to is on the source's frame: the render operator copies the
    CONTEXT scene's frame onto the scene it renders. Every other job keeps the
    old order and relies on the ``engine.cc`` overlay. True when released.
    """
    if scene is source:
        return False
    try:
        from . import main_thread_routing as routing
    except ImportError:
        return False
    target = routing.pin_restore_target()
    if target is None or target.frame_current != source.frame_current:
        return False
    return routing.release_pin("native_render")


def poll(key):
    """Read-only state delivery, including changes since render completion."""
    if _job is not None and _job["key"] == key and _job.get("worker"):
        running = _poll_worker(_job)
        if running is not None:
            return running
    elif _job is not None and _job["key"] == key:
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


def _engine_id(scene, requested):
    """The engine id to render with, or None to leave the scene's own alone.

    Auto uses bounded Cycles to avoid EEVEE's first-use graphics-context stall.
    Cycles is dynamically registered: RNA's static enum_items omits it, so its
    add-on's ``scene.cycles`` settings stand in for availability. With the
    add-on disabled the scene keeps its own engine rather than failing the job.
    Only EEVEE's historical id variants are selected from the static list.
    """
    candidates = _ENGINE_REQUESTS.get(str(requested or "").strip().lower())
    if not candidates:
        return None
    if candidates == ("CYCLES",):
        return "CYCLES" if hasattr(scene, "cycles") else None
    try:
        available = {str(item.identifier) for item in
                     scene.render.bl_rna.properties["engine"].enum_items}
    except Exception:
        available = set()
    for candidate in candidates:
        if not available or candidate in available:
            return candidate
    return None


def _apply_resolution(render, set_value, width, height):
    """The requested size (capped for a final), or the scene's own scaled to
    the preview cap when the call named no size."""
    if width > 0 and height > 0:
        scale = min(1.0, FINAL_MAX_EDGE_PX / max(width, height, 1))
        set_value(render, "resolution_x", max(1, round(width * scale)))
        set_value(render, "resolution_y", max(1, round(height * scale)))
        return
    scale = min(1.0, MAX_EDGE_PX / max(render.resolution_x, render.resolution_y, 1))
    set_value(render, "resolution_x", max(1, round(render.resolution_x * scale)))
    set_value(render, "resolution_y", max(1, round(render.resolution_y * scale)))


def _downgrade_over_budget(scene, set_value, max_faces, fallback=None):
    """Swap Cycles for EEVEE when the scene is too big for this machine.

    Cycles gives every object whose instancing is defeated its own mesh AND BVH,
    and building them is an uninterruptible burst of host allocation: two Mixar
    processes were killed by the OS that way on 2026-09-20 (1250 tree copies with
    per-object material links, ~215M unique triangles on 16 GB). EEVEE draws the
    same scene from real instances and survived both times.

    So an over-budget final is DOWNGRADED, never refused and never allowed to
    crash the app. ``max_faces`` is the budget the backend derived from this
    machine's RAM; 0 (an older backend) means no limit. The engine read here is
    the one the JOB will actually use, because ``_apply_settings`` has already
    applied the call's own engine. Returns the disclosure dict, or None when
    nothing was changed.
    """
    from mixar.modules.common.render_coordinator.core.geometry_budget import downgrade_over_budget
    return downgrade_over_budget(scene, set_value, max_faces,
                                 fallback or _engine_id(scene, "eevee") or _EEVEE_ENGINES[0])


def _apply_settings(scene, set_value, width=0, height=0, engine="", max_faces=0, budget_engine=None,
                    use_gpu=None):
    render = scene.render
    wanted = _engine_id(scene, engine)
    if wanted is not None and str(render.engine) != wanted:
        set_value(render, "engine", wanted)
    # AFTER the call's own engine: the budget judges what this job will really
    # render with, so a scene the CALL turned into a Cycles render is downgraded
    # too — and the caps below then read the downgraded engine.
    downgraded = _downgrade_over_budget(scene, set_value, max_faces, budget_engine)
    _apply_resolution(render, set_value, int(width or 0), int(height or 0))
    set_value(render, "resolution_percentage", 100)
    # media_type BEFORE file_format: on Blender 5 a scene whose output is video
    # (FFMPEG) rejects PNG outright.
    if getattr(render.image_settings, "media_type", "IMAGE") != "IMAGE":
        set_value(render.image_settings, "media_type", "IMAGE")
    set_value(render.image_settings, "file_format", "PNG")
    engine_id = str(render.engine)
    if engine_id == "CYCLES":
        cap = (CYCLES_FINAL_SAMPLE_CAP if str(engine).strip().lower() == "cycles"
               else CYCLES_SAMPLE_CAP)
        set_value(scene.cycles, "samples", min(scene.cycles.samples, cap))
        if str(engine).strip().lower() == "auto":
            set_value(scene.cycles, "use_denoising", True)
        # The device is the user's preference, enabled once at startup; here it
        # is a per-job setting like any other, restored on every exit path.
        # A worker process is told the app's decision (``use_gpu``): the user may
        # have changed the preference this session without saving it.
        gpu = (render_device.use_gpu() if use_gpu is None
               else bool(use_gpu) and render_device.gpu_enabled())
        if gpu:
            set_value(scene.cycles, "device", "GPU")
            # Denoise where it renders: the CPU OpenImageDenoise kernel crashed
            # Mixar mid-preview (CPUInputProcessKernel_run_f32, Sky Temple QA
            # run, Oct 30) with the GPU rendering.
            if hasattr(scene.cycles, "denoising_use_gpu"):
                set_value(scene.cycles, "denoising_use_gpu", True)
    elif engine_id in _EEVEE_ENGINES:
        eevee = getattr(scene, "eevee", None)
        samples = getattr(eevee, "taa_render_samples", None)
        if samples is not None:
            set_value(eevee, "taa_render_samples", min(samples, EEVEE_SAMPLE_CAP))
    return downgraded


def _configure(context, source, scene, set_value, job, width=0, height=0, engine="",
               max_faces=0, inspection=None, use_gpu=None) -> dict:
    """Give ``scene`` the job's look: the inspection rig (its world, sun, camera
    and engine) or the call's engine, then size, samples, device and the
    geometry budget. Shared by the native job and the worker process, so both
    render the same picture. Returns the render info the reply carries.
    ``job['inspection']`` is set before the rig is built, so a failure part-way
    still cleans up what it created."""
    if inspection is not None:
        from .inspection_preview import Inspection
        job['inspection'] = Inspection(source, scene, inspection, set_value)
        job['inspection'].prepare(context)
        width, height = int(inspection.get('width', 1024)), int(inspection.get('height', 768))
        engine = ''  # The inspection rig already chose its shading engine.
    downgraded = _apply_settings(scene, set_value, width, height, engine, max_faces,
                                'BLENDER_WORKBENCH' if inspection is not None else None,
                                use_gpu=use_gpu)
    if inspection is not None and downgraded:
        set_value(scene.display.shading, 'color_type', 'MATERIAL')
        job['inspection'].metadata['warning'] = (
            'Geometry exceeds the material-preview memory budget. This is a solid '
            'structural preview; material nodes were not evaluated. Repair instancing '
            'or reduce unique geometry before judging materials.')
    info = _render_info(scene)
    if downgraded:
        # Rides the render info the backend already forwards, so the model
        # discloses that it did not get the engine it asked for.
        info["engine_downgraded"] = downgraded
    return info


def start(context, key, width=0, height=0, engine="", max_faces=0, inspection=None):
    """Start the preview job for ``key``; idempotent for a key already seen.

    ``width``/``height``/``engine`` are the backend's request (see
    ``_apply_settings``); a call that omits them keeps the old behaviour — the
    scene's own engine at the 768 px preview cap.

    ``max_faces`` is the backend's machine-derived geometry budget; a render
    whose CHOSEN engine is Cycles on a scene above it is downgraded to EEVEE and
    says so in ``render["engine_downgraded"]``.
    """
    global _job
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key):
        return {"job_id": str(key)[:64], "status": "failed", "error": "invalid_job_id"}
    _install()
    if key in _records or (_job is not None and _job["key"] == key):
        return poll(key)  # never restart a job the backend already has
    if _job is not None:
        poll(_job["key"])  # recover a lost completion before deciding it is busy
    if _job is not None or render_slot.busy():
        return {"job_id": key, "status": "busy", "error": "another_render_running"}
    source = context.scene
    if source is None:
        return {"job_id": key, "status": "failed", "error": "scene_unavailable"}
    session = _scene_session(source)
    win = context.window or next(iter(context.window_manager.windows), None)
    if (source.camera is None and inspection is None) or win is None or bpy.app.background:
        return {"job_id": key, "status": "failed", "error": "camera_and_window_required",
                "scene_session": session, "render": _render_info(source)}
    args = {"width": width, "height": height, "engine": engine, "max_faces": max_faces,
            "inspection": inspection}
    value = _start_worker(context, key, source, session, args)
    if value is not None:
        return value
    return _start_native(context, key, source, session, win, **args)


def _start_native(context, key, source, session, win, width=0, height=0, engine="", max_faces=0,
                  inspection=None):
    """The in-process path: Blender's interactive render job on a private copy."""
    global _job
    reservation = render_slot.acquire("agent-preview:" + key)
    if reservation is None:
        return {"job_id": key, "status": "busy", "error": "another_render_running"}
    settings = []

    def set_value(owner, name, value):
        settings.append((owner, name, getattr(owner, name), value))
        setattr(owner, name, value)

    job = {"key": key, "scene": source, "settings": settings, "started_at": time.monotonic(),
           "revision": _revision, "finishing": False, "scene_session": session, "render": {},
           "reservation": reservation, "render_scene": None}
    _job = job
    scene = source
    try:
        if inspection is not None or render_scene.isolate_final(source):
            scene = render_scene.create(source, inspection=inspection is not None)
            job["scene"] = job["render_scene"] = scene
        job["render"] = _configure(context, source, scene, set_value, job, width, height,
                                   engine, max_faces, inspection)
        bpy.app.handlers.render_complete.append(_complete)
        bpy.app.handlers.render_cancel.append(_cancelled)
        kwargs = {}
        if scene is not source:
            # Name the copy through the operator, never the context: bpy.ops
            # first evaluates the context scene's viewport depsgraph, which for
            # the copy is a second full evaluation of the user's objects (and
            # crashed in base-flag evaluation). The context stays on the user's
            # scene, already evaluated. A single-layer render must name the
            # copy's own layer, or it takes the window's layer of the user's scene.
            kwargs["scene"] = scene.name
            if scene.render.use_single_layer:
                layer = scene.view_layers.get(getattr(win.view_layer, "name", ""))
                kwargs["layer"] = (layer or scene.view_layers[0]).name
        # Flush our own setting writes before taking the revision baseline, and
        # before the job thread exists: an evaluation after the invoke would run
        # beside the job's own depsgraph build over the same objects.
        bpy.context.view_layer.update()
        override = {"window": win, "scene": source}
        if _release_route_pin(source, scene):
            # The window now shows the user's tab, which the switch just
            # evaluated; it is the context, as for an unrouted script. bpy.ops
            # evaluates the context scene first, and the routed scene, shown by
            # no window any more, crashed that evaluation (deg copy-on-eval).
            override = {"window": win}
        # The pixels go to the agent; never open an image-editor window.
        view = context.preferences.view
        display = view.render_display_type
        try:
            view.render_display_type = "NONE"
            with bpy.context.temp_override(**override):
                ret = bpy.ops.render.render("INVOKE_DEFAULT", write_still=False, **kwargs)
        finally:
            view.render_display_type = display
        if "RUNNING_MODAL" not in ret:
            raise RuntimeError("async_render_not_started")
        render_slot.phase(reservation, "rendering")
        job["revision"] = _revision
        return {"job_id": key, "status": "running", "render_revision": _revision,
                "scene_session": session, "render": dict(job["render"])}
    except Exception as exc:
        # A failure AFTER native invocation must not free the live renderer.
        if bpy.app.is_job_running("RENDER"):
            job["finishing"] = True
            bpy.app.timers.register(lambda: _finish(key, False), first_interval=0.1)
            return {"job_id": key, "status": "running", "scene_session": session,
                    "render": dict(job["render"])}
        _remove_render_handlers()
        try:
            _restore(job)
        finally:
            _job = None
            render_slot.release(reservation)
        code = str(exc) if str(exc) in {
            'inspection_mode_unsupported', 'inspection_view_unsupported',
            'inspection_focus_not_found', 'inspection_mark_unavailable'} else 'async_render_unavailable'
        value = {"job_id": key, "status": "failed", "error": code,
                 "scene_session": session, "render": job["render"] or _render_info(source)}
        _publish(key, value)
        return value


# ---------------------------------------------------------------------------
# Out of process: the same job in a background Mixar worker
# ---------------------------------------------------------------------------
#
# Every native crash in this feature's history was in the user's process: the
# render job thread reading a scene or depsgraph the main thread freed, the
# OpenImageDenoise kernel, an import landing mid-render. The worker renders a
# SNAPSHOT of the document in a second Mixar (``common/render_worker``), so a
# crash there costs one retry on a fresh worker, nothing of the user's runs on
# Blender's render job thread, and agent scripts are no longer refused with
# ``render_in_progress`` while a preview renders. The reply is the same dict,
# field for field: the worker runs ``_configure`` / ``_read_png`` / the
# inspection rig itself, and this process adds what only it knows
# (``scene_session``, the revisions, ``scene_advanced``, the elapsed time).
#
# A worker that cannot start falls back to the native job for that call, and
# after repeated boot failures the session stops trying (``supervisor.available``).
# A job that crashes its worker twice fails with ``render_worker_crashed``: the
# same render in this process would most likely crash the app.

#: The worker's own bound: the held-open call gives up at PREVIEW_DEFERRED_MAX_S
#: (240 s); the worker is killed a little after, so it never renders for nobody.
WORKER_TIMEOUT_S = 270.0
_last_worker = {}   # diagnostics of the last worker job (QA and logs)


def last_worker_job() -> dict:
    return dict(_last_worker)


def _jobs_dir() -> str:
    import os
    from mixar.modules.common.render_worker import supervisor
    folder = os.path.join(supervisor.root_dir(), "jobs")
    os.makedirs(folder, exist_ok=True)
    return folder


def _start_worker(context, key, source, session, args):
    """Hand the job to a worker; None when this call must run in-process."""
    global _job
    try:
        from mixar.modules.common.render_worker import snapshot, supervisor
        if not supervisor.available():
            return None
    except Exception:
        return None
    import os
    started = time.monotonic()
    view_layer = getattr(context, "view_layer", None)
    try:
        record = snapshot.write_or_reuse(
            "preview", lambda: snapshot.fingerprint(source, _revision), _flush_view_layer)
    except Exception:
        # A snapshot that cannot be written (disk full, a save refused) leaves
        # the in-process job, exactly as before the worker existed.
        return None
    out = os.path.join(_jobs_dir(), "preview-%s.json" % key)
    params = dict(args, key=key, use_gpu=render_device.use_gpu())
    try:
        job_id = supervisor.submit("preview", {
            "kind": "preview", "snapshot": record["path"], "images": record["images"],
            "scene": source.name, "view_layer": getattr(view_layer, "name", ""),
            "params": params, "out": out}, timeout_s=WORKER_TIMEOUT_S)
    except Exception:
        snapshot.release(record)
        return None
    snapshot.acquire(record)
    info = _render_info(source)
    _job = {"key": key, "scene": source, "settings": [], "started_at": started,
            "revision": _revision, "finishing": False, "scene_session": session,
            "render": info, "reservation": None, "render_scene": None, "worker": job_id,
            "snapshot": record, "out": out, "args": args,
            "view_layer": getattr(view_layer, "name", "")}
    _last_worker.clear()
    _last_worker.update({"key": key, "job": job_id, "state": "running",
                         "snapshot_bytes": record["bytes"], "snapshot_reused": record["reused"],
                         "snapshot_save_s": record["save_s"], "snapshot_images_s": record["images_s"],
                         "dirty_images": record["image_count"],
                         "start_s": round(time.monotonic() - started, 4)})
    return {"job_id": key, "status": "running", "render_revision": _revision,
            "scene_session": session, "render": dict(info)}


def _flush_view_layer():
    """Evaluate the tags the snapshot save left (its save handlers write scene
    properties), so the revision baseline taken next is not advanced by them."""
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


def _drop_worker_job(job):
    try:
        from mixar.modules.common.render_worker import snapshot, supervisor
        supervisor.cancel(job["worker"])
        supervisor.forget(job["worker"])
        snapshot.release(job["snapshot"])
    except Exception:
        pass


def _forget_worker_snapshots():
    try:
        from mixar.modules.common.render_worker import snapshot
        snapshot.invalidate()
    except Exception:
        pass


def _fallback_native(job):
    """The worker never started: run this call's job in-process after all."""
    source = job["scene"]
    try:
        _ = source.name
    except ReferenceError:
        return {"job_id": job["key"], "status": "failed", "error": "scene_unavailable",
                "scene_session": job["scene_session"]}
    win = next(iter(bpy.context.window_manager.windows), None)
    if win is None:
        return {"job_id": job["key"], "status": "failed", "error": "camera_and_window_required",
                "scene_session": job["scene_session"]}
    overrides = {"window": win, "scene": source}
    layer = source.view_layers.get(job.get("view_layer") or "")
    if layer is not None:
        overrides["view_layer"] = layer
    with bpy.context.temp_override(**overrides):
        return _start_native(bpy.context, job["key"], source, job["scene_session"], win,
                             **job["args"])


def _poll_worker(job):
    """Advance a worker job; the running reply, or None once it is terminal and
    published (``poll`` then reads the record)."""
    global _job
    import json
    import os
    from mixar.modules.common.render_worker import snapshot, supervisor

    key = job["key"]
    state = supervisor.poll(job["worker"])
    if state["state"] in ("queued", "running"):
        return {"job_id": key, "status": "running", "render_revision": job["revision"],
                "scene_session": job["scene_session"], "render": dict(job["render"])}
    _job = None
    supervisor.forget(job["worker"])
    snapshot.release(job["snapshot"])
    _last_worker.update(state=state["state"], error=state.get("error", ""),
                        attempts=state.get("attempts"), pid=state.get("pid"),
                        retried_after_crash=state.get("retried_after_crash"),
                        worker_seconds=state.get("seconds"),
                        elapsed_s=round(time.monotonic() - job["started_at"], 3))
    if state["state"] == "failed" and state.get("error") == "worker_unavailable":
        _last_worker["fallback"] = "in_process"
        value = _fallback_native(job)
        if value.get("status") != "running":
            _publish(key, value)
            return value
        return value
    result = None
    if state["state"] == "done":
        try:
            with open(state["out"], encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, ValueError):
            result = None
        try:
            os.remove(state["out"])
        except OSError:
            pass
    if not isinstance(result, dict):
        error = {"worker_crashed": "render_worker_crashed",
                 "worker_timeout": "preview_timeout"}.get(state.get("error"),
                                                          "async_render_unavailable")
        result = {"job_id": key, "status": "failed", "error": error,
                  "render": dict(job["render"])}
        if job["args"].get("inspection") is not None:
            result["success"] = False
    result.update(job_id=key, render_revision=job["revision"],
                  scene_session=job["scene_session"], scene_revision=_revision)
    if result.get("status") == "done":
        result["scene_advanced"] = _revision != job["revision"]
    result["render"] = dict(result.get("render") or job["render"],
                            elapsed_seconds=round(time.monotonic() - job["started_at"], 3))
    _publish(key, result)
    return None

