# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render Director shots as persistent Beauty, Clay, and Depth movies."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import tempfile
import time
import uuid

import bpy

from mixar.config.logging_config import get_logger

from .render_passes import (
    configure_render_pass,
    restore_render_settings,
    snapshot_render_settings,
)
from .render_spec import ordered_render_kinds, render_frame_bounds


logger = get_logger(__name__)

_KIND_LABELS = {
    "BEAUTY": "Beauty Preview",
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


def _find_shot(scene, shot_id: str):
    state = getattr(scene, "mixar_director", None)
    if state is None:
        return None
    return next((shot for shot in state.shots if shot.shot_id == shot_id), None)


def _redraw() -> None:
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in getattr(getattr(window, "screen", None), "areas", ()):
            if area.type in {'VIEW_3D', 'MIXIE'}:
                area.tag_redraw()


def _temporary_movie_path(shot, kind: str) -> str:
    directory = bpy.app.tempdir or tempfile.gettempdir()
    stem = f"mixar_director_{shot.shot_id[:8]}_{kind.lower()}_{uuid.uuid4().hex[:8]}"
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


def _add_handlers() -> None:
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
    _job = None
    _remove_handlers()
    if job is None:
        return
    scene = bpy.data.scenes.get(job["scene_name"])
    shot = _find_shot(scene, job["shot_id"]) if scene is not None else None
    if scene is not None:
        _restore_active_pass(job, scene)
    if shot is not None:
        shot.render_is_running = False
        shot.render_progress = 1.0 if success else 0.0
        shot.render_status = message
    _redraw()


def _start_current_pass() -> None:
    job = _job
    scene = bpy.data.scenes.get(job["scene_name"])
    shot = _find_shot(scene, job["shot_id"]) if scene is not None else None
    if scene is None or shot is None:
        raise RuntimeError("The Director shot was removed while rendering")
    view_layer = scene.view_layers.get(job["view_layer_name"])
    view_layer = view_layer or scene.view_layers[0]
    kind = job["kinds"][job["index"]]
    path = _temporary_movie_path(shot, kind)
    job["path"] = path
    job["temp_group_name"] = configure_render_pass(scene, view_layer, shot, kind, path)
    job["configured"] = True
    job["finalize_scheduled"] = False
    label = _KIND_LABELS[kind]
    shot.render_status = f"Rendering {label} {job['index'] + 1}/{len(job['kinds'])} · Esc to cancel"
    _redraw()

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


def _record_output(scene, shot, kind: str, path: str) -> None:
    from mixar.modules.moodboard.core.media_import import import_generated_video

    label = _KIND_LABELS[kind]
    display_name = f"{shot.name} T{shot.version:02d} · {label}"
    prompt = f"{label} motion guide for {shot.name}"
    if shot.prompt:
        prompt = f"{prompt}\n\n{shot.prompt}"
    # No group_name: guide videos land as loose board items, not a formal group
    # (the user groups exports manually if they want).
    image_name = import_generated_video(
        path,
        scene_name=scene.name,
        generation_prompt=prompt,
        display_name=display_name,
        selected=False,
    )
    output = shot.render_outputs.add()
    output.output_id = uuid.uuid4().hex
    output.kind = kind
    output.image = bpy.data.images.get(image_name)
    output.rendered_at = datetime.now(timezone.utc).isoformat()


def _complete_current_pass():
    job = _job
    if job is None:
        return None
    job["pass_running"] = False
    scene = bpy.data.scenes.get(job["scene_name"])
    shot = _find_shot(scene, job["shot_id"]) if scene is not None else None
    if scene is None or shot is None:
        _finish_job(False, "Render failed: shot is unavailable")
        return None
    kind = job["kinds"][job["index"]]
    try:
        _restore_active_pass(job, scene)
        path = _resolved_movie_path(job["path"])
        _record_output(scene, shot, kind, path)
        job["completed"] += 1
        job["index"] += 1
        if job["index"] < len(job["kinds"]):
            _queue_next_pass(shot)
            return None
    except Exception as exc:
        logger.exception("Director shot render failed")
        _finish_job(False, f"Render failed: {exc}")
        return None
    _finish_job(
        True,
        f"Added {job['completed']} shot video{'s' if job['completed'] != 1 else ''} to Moodboard",
    )
    return None


def _queue_next_pass(shot) -> None:
    job = _job
    kind = job["kinds"][job["index"]]
    label = _KIND_LABELS[kind]
    job["next_pass_deadline"] = time.monotonic() + _NEXT_PASS_TIMEOUT_SECONDS
    shot.render_status = f"Preparing {label} {job['index'] + 1}/{len(job['kinds'])}"
    _redraw()
    bpy.app.timers.register(
        _start_next_pass_when_idle,
        first_interval=_NEXT_PASS_POLL_SECONDS,
    )


def _start_next_pass_when_idle():
    job = _job
    if job is None:
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
    bpy.app.timers.register(_complete_current_pass, first_interval=0.1)


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
    bpy.app.timers.register(
        lambda: _finish_job(False, "Shot render canceled"),
        first_interval=0.1,
    )


def _on_render_write(scene, _depsgraph=None) -> None:
    if (
        _job is None
        or not _job.get("pass_running")
        or scene.name != _job["scene_name"]
    ):
        return
    shot = _find_shot(scene, _job["shot_id"])
    if shot is None:
        return
    frame_start, frame_end = shot_frame_range(shot)
    frame_count = max(1, frame_end - frame_start + 1)
    within_pass = (scene.frame_current - frame_start + 1) / frame_count
    shot.render_progress = min(
        1.0,
        (_job["index"] + within_pass) / len(_job["kinds"]),
    )
    _redraw()


def start_shot_render(context, shot) -> int:
    """Start an interactive multi-pass render and return the pass count."""
    global _job
    if _job is not None or bpy.app.is_job_running("RENDER"):
        raise RuntimeError("Another render is already in progress")
    if shot.camera is None or shot.camera.type != 'CAMERA':
        raise ValueError("Choose a shot camera first")
    kinds = ordered_render_kinds(shot.render_output_types)
    if not kinds:
        raise ValueError("Select at least one shot render")
    shot_frame_range(shot)

    scene = shot.scene_ref or context.scene
    view_layer = context.view_layer
    if scene.view_layers.get(view_layer.name) is None:
        view_layer = scene.view_layers[0]
    _job = {
        "scene_name": scene.name,
        "shot_id": shot.shot_id,
        "view_layer_name": view_layer.name,
        "kinds": kinds,
        "index": 0,
        "completed": 0,
        "saved": snapshot_render_settings(scene, view_layer),
        "configured": False,
        "temp_group_name": "",
        "pass_running": False,
    }
    shot.render_is_running = True
    shot.render_progress = 0.0
    shot.render_status = "Preparing shot render"
    _add_handlers()
    try:
        _start_current_pass()
    except Exception:
        _finish_job(False, "Could not start shot render")
        raise
    return len(kinds)
