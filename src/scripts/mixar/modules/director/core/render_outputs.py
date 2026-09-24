# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render camera motion as persistent Beauty, Clay, and Depth movies.

ONE multi-pass job serves both callers: a Director shot (span from its beats)
and a natively keyframed camera driven from the Render / Timeline menus
(`start_camera_render`). Everything caller-specific — whose camera, where the
progress goes, what the movie is called — lives behind a `RenderTarget`.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import tempfile
import time
import uuid

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.common.render_coordinator import core as render_slot

from .render_passes import (
    configure_render_pass,
    restore_render_settings,
    snapshot_render_settings,
)
from .render_target import (
    resolve_status_owner,
    camera_target,
    resolve_target,
    shot_target,
    target_ref,
)
from .rotation_curves import repair_rotation_continuity
from .shot_api import shot_scene
from .render_spec import ordered_render_kinds, render_frame_bounds


logger = get_logger(__name__)

_KIND_LABELS = {
    "BEAUTY": "Color",
    "CLAY": "Clay",
    "DEPTH": "Depth",
}
_NEXT_PASS_POLL_SECONDS = 0.15
_NEXT_PASS_TIMEOUT_SECONDS = 10.0
_job = None


class _RenderStartDeferred(RuntimeError):
    """The previous Blender render job has not released its slot yet."""


def shot_frame_range(shot) -> tuple[int, int]:
    """Return the render span defined by the shot's keyframes."""
    return render_frame_bounds(beat.frame for beat in shot.beats)


def render_job_active() -> bool:
    return _job is not None


def _job_target(job):
    """Re-resolve the running job's target, or ``None`` if it is gone."""
    scene = bpy.data.scenes.get(job["scene_name"])
    if scene is None:
        return None, None
    return scene, resolve_target(scene, job["target"])


def _redraw() -> None:
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in getattr(getattr(window, "screen", None), "areas", ()):
            if area.type in {'VIEW_3D', 'MIXIE'}:
                area.tag_redraw()


def _temporary_movie_path(kind: str) -> str:
    directory = bpy.app.tempdir or tempfile.gettempdir()
    stem = f"mixar_director_{kind.lower()}_{uuid.uuid4().hex[:8]}"
    return os.path.join(directory, f"{stem}.mp4")


def _resolved_movie_path(path: str) -> str:
    for candidate in (path, f"{path}.mp4", f"{os.path.splitext(path)[0]}.mp4"):
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
            return candidate
    raise RuntimeError("The animation render did not produce an MP4")


def _remove_handlers() -> None:
    for handlers, callback in (
        (bpy.app.handlers.render_complete, _on_render_complete),
        (bpy.app.handlers.render_cancel, _on_render_cancel),
        (bpy.app.handlers.render_write, _on_render_write),
    ):
        try:
            if callback in handlers:
                handlers.remove(callback)
        except Exception:
            pass


@persistent
def _before_load(_unused, _extra=None):
    global _job
    if _job is not None:
        render_slot.release(_job.get("reservation"))
    _job = None
    _remove_handlers()


def _add_handlers() -> None:
    if _before_load not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_before_load)
    _remove_handlers()
    bpy.app.handlers.render_complete.append(_on_render_complete)
    bpy.app.handlers.render_cancel.append(_on_render_cancel)
    bpy.app.handlers.render_write.append(_on_render_write)


def _restore_active_pass(job, scene) -> None:
    if not job.get("configured"):
        return
    view_layer = scene.view_layers.get(job["view_layer_name"])
    view_layer = view_layer or scene.view_layers[0]
    restore_render_settings(
        scene,
        view_layer,
        job["saved"],
        job.get("temp_group_name", ""),
    )
    job["configured"] = False
    job["temp_group_name"] = ""


def _discard_temporary_movie(path: str) -> None:
    for candidate in (path, f"{path}.mp4", f"{os.path.splitext(path)[0]}.mp4"):
        try:
            os.remove(candidate)
        except OSError:
            pass


def _finish_job(success: bool, message: str) -> None:
    global _job
    job = _job
    if job is None:
        return
    # Between passes our settings are already restored. A foreign native
    # render must not keep the next-pass timeout (and our reservation) alive.
    if job.get("configured") and bpy.app.is_job_running("RENDER"):
        def finish_when_idle():
            if _job is not job:
                return None
            if bpy.app.is_job_running("RENDER"):
                return _NEXT_PASS_POLL_SECONDS
            _finish_job(success, message)
            return None
        bpy.app.timers.register(finish_when_idle, first_interval=_NEXT_PASS_POLL_SECONDS)
        return
    _job = None
    _remove_handlers()
    try:
        scene, target = _job_target(job)
        if scene is not None:
            _restore_active_pass(job, scene)
        if target is not None:
            target.set_status(
                running=False,
                progress=1.0 if success else 0.0,
                status=message,
            )
        elif scene is not None:
            # The camera was renamed or deleted mid-render, so the target no
            # longer resolves — but the RNA that shows "running" (the shot, or
            # the scene's camera-export settings) is still there and would stay
            # frozen at "rendering" until the file is reloaded.
            owner = resolve_status_owner(scene, job["target"])
            if owner is not None:
                owner.render_is_running = False
                owner.render_progress = 0.0
                owner.render_status = message
        _redraw()
    finally:
        render_slot.release(job.get("reservation"))


def _start_current_pass() -> None:
    job = _job
    scene, target = _job_target(job)
    if scene is None or target is None:
        raise RuntimeError("The render camera was removed while rendering")
    view_layer = scene.view_layers.get(job["view_layer_name"])
    view_layer = view_layer or scene.view_layers[0]
    kind = job["kinds"][job["index"]]
    path = _temporary_movie_path(kind)
    job["path"] = path
    job["temp_group_name"] = configure_render_pass(
        scene, view_layer, target, kind, path
    )
    job["configured"] = True
    job["finalize_scheduled"] = False
    label = _KIND_LABELS[kind]
    target.set_status(
        status=(
            f"Rendering {label} {job['index'] + 1}/{len(job['kinds'])}"
            " · Esc to cancel"
        )
    )
    _redraw()

    render_slot.phase(job["reservation"], "rendering")
    job["pass_running"] = True
    manager = bpy.context.window_manager
    window = bpy.context.window or next(iter(getattr(manager, "windows", ())), None)
    if window is None:
        result = bpy.ops.render.render(animation=True, write_still=False)
    else:
        with bpy.context.temp_override(window=window, scene=scene):
            result = bpy.ops.render.render(
                'INVOKE_DEFAULT',
                animation=True,
                write_still=False,
            )
    if 'CANCELLED' in result:
        job["pass_running"] = False
        _restore_active_pass(job, scene)
        _discard_temporary_movie(path)
        raise _RenderStartDeferred("Blender render slot is still busy")


def _record_output(scene, target, kind: str, path: str) -> None:
    from mixar.modules.moodboard.core.media_import import import_generated_video

    label = _KIND_LABELS[kind]
    display_name = target.display_name(label)
    prompt = f"{label} motion guide for {target.display_prefix}"
    if target.prompt:
        prompt = f"{prompt}\n\n{target.prompt}"
    # No group_name: guide videos land as loose board items, not a formal group
    # (the user groups exports manually if they want).
    image_name = import_generated_video(
        path,
        scene_name=scene.name,
        generation_prompt=prompt,
        display_name=display_name,
        selected=False,
    )
    target.record_output(
        kind,
        bpy.data.images.get(image_name),
        datetime.now(timezone.utc).isoformat(),
    )


def _complete_current_pass():
    job = _job
    if job is None or not render_slot.owns(job.get("reservation")):
        return None
    if bpy.app.is_job_running("RENDER"):
        return _NEXT_PASS_POLL_SECONDS
    render_slot.phase(job["reservation"], "finalizing")
    job["pass_running"] = False
    scene, target = _job_target(job)
    if scene is None or target is None:
        _finish_job(False, "Render failed: the render camera is unavailable")
        return None
    kind = job["kinds"][job["index"]]
    try:
        _restore_active_pass(job, scene)
        path = _resolved_movie_path(job["path"])
        _record_output(scene, target, kind, path)
        job["completed"] += 1
        job["index"] += 1
        if job["index"] < len(job["kinds"]):
            _queue_next_pass(target)
            return None
    except Exception as exc:
        logger.exception("Director guide render failed")
        _finish_job(False, f"Render failed: {exc}")
        return None
    _finish_job(
        True,
        f"Added {job['completed']} video{'s' if job['completed'] != 1 else ''} to Moodboard",
    )
    return None


def _schedule_for_job(callback, delay):
    """Timers from a previous file/job must never act on the next job."""
    job = _job
    def run():
        if _job is not job or job is None:
            return None
        return callback()
    bpy.app.timers.register(run, first_interval=delay)


def _queue_next_pass(target) -> None:
    job = _job
    kind = job["kinds"][job["index"]]
    label = _KIND_LABELS[kind]
    job["next_pass_deadline"] = time.monotonic() + _NEXT_PASS_TIMEOUT_SECONDS
    target.set_status(
        status=f"Preparing {label} {job['index'] + 1}/{len(job['kinds'])}"
    )
    _redraw()
    _schedule_for_job(_start_next_pass_when_idle, _NEXT_PASS_POLL_SECONDS)


def _start_next_pass_when_idle():
    job = _job
    if job is None or not render_slot.owns(job.get("reservation")):
        return None
    before_deadline = time.monotonic() < job["next_pass_deadline"]
    try:
        render_slot_busy = bpy.app.is_job_running("RENDER")
    except Exception:
        render_slot_busy = False
    if render_slot_busy:
        if before_deadline:
            return _NEXT_PASS_POLL_SECONDS
        _finish_job(False, "Render failed: Blender did not release the render slot")
        return None
    try:
        _start_current_pass()
    except _RenderStartDeferred:
        if before_deadline:
            return _NEXT_PASS_POLL_SECONDS
        _finish_job(False, "Render failed: Blender refused the next video pass")
    except Exception as exc:
        logger.exception("Could not start the next Director render pass")
        _finish_job(False, f"Render failed: {exc}")
    return None


def _on_render_complete(scene, _depsgraph=None) -> None:
    if (
        _job is None
        or not _job.get("pass_running")
        or scene.name != _job["scene_name"]
    ):
        return
    if _job.get("finalize_scheduled"):
        return
    _job["finalize_scheduled"] = True
    _schedule_for_job(_complete_current_pass, 0.1)


def _on_render_cancel(scene, _depsgraph=None) -> None:
    if (
        _job is None
        or not _job.get("pass_running")
        or scene.name != _job["scene_name"]
    ):
        return
    if _job.get("finalize_scheduled"):
        return
    _job["pass_running"] = False
    _job["finalize_scheduled"] = True
    _schedule_for_job(lambda: _finish_job(False, "Shot render canceled"), 0.1)


def _on_render_write(scene, _depsgraph=None) -> None:
    if (
        _job is None
        or not _job.get("pass_running")
        or scene.name != _job["scene_name"]
    ):
        return
    _scene, target = _job_target(_job)
    if target is None:
        return
    frame_count = max(1, target.frame_end - target.frame_start + 1)
    within_pass = (scene.frame_current - target.frame_start + 1) / frame_count
    target.set_status(
        progress=min(1.0, (_job["index"] + within_pass) / len(_job["kinds"]))
    )
    _redraw()


def _start_render(context, scene, target, preparing: str) -> int:
    """Arm the job for *target* and start its first pass.

    Never touches the camera's animation: a bare Export-to-Moodboard camera
    is the USER's, and rewriting its rotation keys (even to an equivalent
    representation) from a render button would be a silent, non-undoable
    edit. Director repairs its own shot cameras in ``start_shot_render``.
    """
    global _job
    view_layer = context.view_layer
    if view_layer is None or scene.view_layers.get(view_layer.name) is None:
        view_layer = scene.view_layers[0]
    _job = {
        "scene_name": scene.name,
        "target": target_ref(target),
        "view_layer_name": view_layer.name,
        "kinds": tuple(target.kinds),
        "index": 0,
        "completed": 0,
        "saved": snapshot_render_settings(scene, view_layer),
        "configured": False,
        "temp_group_name": "",
        "pass_running": False,
    }
    reservation = render_slot.acquire("director-guides")
    if reservation is None:
        _job = None
        raise RuntimeError("Another render is already in progress")
    _job["reservation"] = reservation
    try:
        target.set_status(running=True, progress=0.0, status=preparing)
        _add_handlers()
        _start_current_pass()
    except Exception:
        _finish_job(False, "Could not start the guide render")
        raise
    return len(target.kinds)


def start_shot_render(context, shot) -> int:
    """Start an interactive multi-pass render and return the pass count."""
    if _job is not None or render_slot.busy():
        raise RuntimeError("Another render is already in progress")
    if shot.camera is None or shot.camera.type != 'CAMERA':
        raise ValueError("Choose a shot camera first")
    kinds = ordered_render_kinds(shot.render_output_types)
    if not kinds:
        raise ValueError("Select at least one shot render")
    frame_start, frame_end = shot_frame_range(shot)
    # Director owns this camera's keys, so the continuity repair every other
    # Director key-writing path runs is right here too.
    repair_rotation_continuity(shot.camera)

    scene = shot_scene(shot, context.scene)
    target = shot_target(shot, frame_start, frame_end, kinds)
    return _start_render(context, scene, target, "Preparing shot render")


def start_camera_render(context, scene, settings, camera, plan) -> int:
    """Render a natively animated camera; *plan* froze the span and passes.

    The caller (`ui/camera_export_drawer` / its operator) has already built and
    validated the plan, so this never re-derives a span — the readiness rules
    live in ONE place, `core/render_request.py`.
    """
    if _job is not None or render_slot.busy():
        raise RuntimeError("Another render is already in progress")
    if not plan.ok:
        raise ValueError(plan.reason)
    target = camera_target(settings, camera, plan)
    return _start_render(context, scene, target, "Preparing camera render")
