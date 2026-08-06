# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Single mutation surface for camera-direction shots."""

from __future__ import annotations

import json
import uuid

import bpy

from ..constants import DIRECTOR_SHOT_BASENAME, DIRECTOR_TEXT_SUFFIX
from .manifest import (
    build_camera_direction_manifest,
    serialize_camera_direction_manifest,
)


def active_shot(scene):
    """Return the selected shot for *scene*, or ``None``."""
    state = getattr(scene, "mixar_director", None)
    if state is None or not state.shots:
        return None
    index = min(max(0, state.active_shot_index), len(state.shots) - 1)
    if state.active_shot_index != index:
        state.active_shot_index = index
    return state.shots[index]


def latest_shot_index_for_camera(state, camera) -> int:
    """Return the newest take using *camera*, or ``-1`` when none does."""
    matches = [
        index for index, shot in enumerate(state.shots) if shot.camera == camera
    ]
    if not matches:
        return -1
    return max(matches, key=lambda index: (state.shots[index].version, index))


def scope_preview_range(scene, shot) -> None:
    """Loop playback within *shot*'s beats instead of the whole scene.

    Every shot shares one scene timeline, so without this the playhead and
    autoplay use the global frame range (the max across all shots) and a
    shot's cursor runs past its own beats into another shot's range.
    """
    frames = sorted({int(beat.frame) for beat in shot.beats}) if shot else []
    if frames:
        scene.use_preview_range = True
        scene.frame_preview_start = frames[0]
        scene.frame_preview_end = frames[-1]
    else:
        scene.use_preview_range = False


def create_shot(scene, camera, *, parent=None):
    """Create and activate a draft take referencing native scene data."""
    state = scene.mixar_director
    shot = state.shots.add()
    shot.shot_id = uuid.uuid4().hex
    shot.scene_ref = scene
    shot.camera = camera
    if parent is None:
        root_number = sum(1 for item in state.shots if not item.parent_shot_id)
        shot.name = f"{DIRECTOR_SHOT_BASENAME} {root_number:02d}"
    else:
        shot.name = parent.name
        shot.version = parent.version + 1
        shot.parent_shot_id = parent.shot_id
        shot.prompt = parent.prompt
        shot.guidance_strength = parent.guidance_strength
        shot.render_output_types = set(parent.render_output_types)
        shot.render_resolution_percentage = parent.render_resolution_percentage
    state.active_shot_index = len(state.shots) - 1
    scene.camera = camera
    return shot


def create_new_take(scene, shot):
    """Create an editable child take without mutating a locked shot."""
    return create_shot(scene, shot.camera, parent=shot)


def remove_shot(scene, index: int) -> bool:
    """Remove shot metadata while preserving its native camera and images."""
    state = scene.mixar_director
    if index < 0 or index >= len(state.shots):
        return False
    state.shots.remove(index)
    state.active_shot_index = min(index, max(0, len(state.shots) - 1))
    scope_preview_range(scene, active_shot(scene))
    return True


def _sample_camera(scene, camera, frame: int) -> dict:
    scene.frame_set(int(frame))
    try:
        evaluated = camera.evaluated_get(bpy.context.evaluated_depsgraph_get())
    except Exception:
        evaluated = camera
    location, rotation, _scale = evaluated.matrix_world.decompose()
    data = getattr(evaluated, "data", None) or camera.data
    return {
        "location": tuple(location),
        # Blender exposes quaternions as W, X, Y, Z.
        "rotation_quaternion": tuple(rotation),
        "projection": str(data.type),
        "lens_mm": float(data.lens),
        "ortho_scale": float(data.ortho_scale),
        "sensor_width_mm": float(data.sensor_width),
        "sensor_height_mm": float(data.sensor_height),
        "sensor_fit": str(data.sensor_fit),
        "shift_x": float(data.shift_x),
        "shift_y": float(data.shift_y),
    }


def build_shot_manifest(scene, shot) -> dict:
    """Sample native camera animation at each beat and build its manifest."""
    if shot.camera is None or shot.camera.type != 'CAMERA':
        raise ValueError("The shot has no camera")

    current_frame = scene.frame_current
    beats = []
    try:
        for beat in shot.beats:
            sample = _sample_camera(scene, shot.camera, beat.frame)
            sample.update({
                "id": beat.beat_id,
                "frame": beat.frame,
                "image_name": beat.image.name if beat.image else "",
            })
            beats.append(sample)
    finally:
        scene.frame_set(current_frame)

    render = scene.render
    return build_camera_direction_manifest(
        shot_id=shot.shot_id,
        shot_name=shot.name,
        version=shot.version,
        scene_name=scene.name,
        camera_name=shot.camera.name,
        frame_start=scene.frame_start,
        frame_end=scene.frame_end,
        fps=render.fps,
        fps_base=render.fps_base,
        resolution_x=render.resolution_x,
        resolution_y=render.resolution_y,
        prompt=shot.prompt,
        guidance_strength=shot.guidance_strength,
        beats=beats,
        pixel_aspect_x=render.pixel_aspect_x,
        pixel_aspect_y=render.pixel_aspect_y,
    )


def refresh_manifest(scene, shot) -> str:
    """Rebuild a draft shot's sparse representation from native data."""
    serialized = serialize_camera_direction_manifest(
        build_shot_manifest(scene, shot)
    )
    shot.manifest_json = serialized
    return serialized


def write_manifest_text(shot, serialized: str):
    """Write the manifest to a Blender Text datablock for inspection/export."""
    suffix = shot.shot_id[:6]
    name = f"{shot.name} T{shot.version:02d} {suffix}{DIRECTOR_TEXT_SUFFIX}"
    text = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    text.clear()
    text.write(serialized)
    shot.manifest_text_name = text.name
    return text


def compile_manifest(scene, shot) -> str:
    """Refresh and expose a draft manifest without locking the take."""
    serialized = refresh_manifest(scene, shot)
    write_manifest_text(shot, serialized)
    return serialized


def lock_shot(scene, shot) -> str:
    """Freeze the exact manifest used as this take's production contract."""
    if shot.state == 'LOCKED':
        return shot.snapshot_json
    if not shot.beats:
        raise ValueError("Capture at least one camera beat before locking")
    serialized = compile_manifest(scene, shot)
    shot.snapshot_json = serialized
    shot.locked_at = str(json.loads(serialized)["exported_at"])
    shot.state = 'LOCKED'
    return serialized
