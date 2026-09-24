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


def shot_scene(shot, fallback=None):
    """The Scene a *shot* belongs to.

    ``state.shots`` is a collection on ``bpy.types.Scene``, so a shot's owning
    ID *is* its scene and ``id_data`` reaches it for free. Director used to
    carry an explicit ``scene_ref`` PointerProperty instead, and because an RNA
    ID pointer is refcounted that made every added shot bump the Scene's user
    count — the "Scene 2", "Scene 3" badge the topbar datablock selector shows
    beside the scene name. ``id_data`` holds no reference and cannot drift from
    the collection it was read through.
    """
    owner = getattr(shot, "id_data", None)
    # Identified by the property Director itself registers on Scene rather
    # than ``isinstance(..., bpy.types.Scene)``: the shots collection only
    # ever lives on a scene, and the attribute test also holds under the
    # ``bpy`` mock the standalone suite runs against.
    if owner is not None and getattr(owner, "mixar_director", None) is not None:
        return owner
    return fallback


def active_shot(scene):
    """Return the selected shot for *scene*, or ``None``."""
    state = getattr(scene, "mixar_director", None)
    if state is None or not state.shots:
        return None
    index = min(max(0, state.active_shot_index), len(state.shots) - 1)
    if state.active_shot_index != index:
        state.active_shot_index = index
    return state.shots[index]


def shot_index(state, shot) -> int:
    """Return *shot*'s position in ``state.shots``, or the active index.

    Matching on ``shot_id`` keeps the lookup valid across the RNA reference
    churn that adding a shot causes.
    """
    shot_id = getattr(shot, "shot_id", "")
    for index, item in enumerate(state.shots):
        if shot_id and item.shot_id == shot_id:
            return index
    return min(max(0, state.active_shot_index), max(0, len(state.shots) - 1))


def latest_shot_index_for_camera(state, camera) -> int:
    """Return the newest take using *camera*, or ``-1`` when none does."""
    matches = [
        index for index, shot in enumerate(state.shots) if shot.camera == camera
    ]
    if not matches:
        return -1
    return max(matches, key=lambda index: (state.shots[index].version, index))


def adopt_camera(scene, camera):
    """Make *camera*'s newest take the active shot, minting one if it has none.

    Each camera is its own shot and its own timeline, so adopting never
    reassigns an existing shot's camera — that collapsed every camera onto
    one strip. It switches to the take already directing this camera, or
    starts a fresh shot for a camera Director has not seen.

    This is what a click on a My Cameras row does, and what entering Cinema
    Mode does for the camera it opens on: looking through a camera without
    adopting it left the session with no active shot, which every
    shot-gated control reads as "nothing to do" — the Walk chip greyed out
    on entry, and the row never lit.

    Returns the active shot, or ``None`` when *camera* is not one.
    """
    state = getattr(scene, "mixar_director", None)
    if state is None or camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None
    index = latest_shot_index_for_camera(state, camera)
    if index >= 0:
        state.active_shot_index = index
        scene.camera = camera
        return state.shots[index]
    return create_shot(scene, camera)


def release_preview_range(scene) -> None:
    """Hand playback back to the SCENE's own frame range.

    This used to clamp the preview range to the active shot's first and last
    beat, so pressing play looped between two keyframes however long the
    scene was — and the dock's own Start and End fields, which edit
    ``scene.frame_start`` / ``frame_end``, had no effect on what played. Two
    controls for one thing, and the invisible one won.

    The scene range is the one a director sets and the one the dock shows, so
    it is the one that plays. Nothing is lost by dropping the clamp: a
    captured keyframe already pushes ``scene.frame_end`` out to cover itself
    (``capture_beat``), so a shot's beats are inside the range by
    construction.

    The session still SAVES the user's own preview range on entry and
    restores it on exit (``core/viewport.py``); turning it off here is part
    of what that restore puts back.
    """
    scene.use_preview_range = False


class _ShotSnapshot:
    """Plain copy of the fields a child take inherits from its parent.

    ``state.shots.add()`` reallocates the underlying IDProperty array, so any
    Blender reference obtained before the add points at freed memory
    afterwards. Every parent field is therefore read up front and the RNA
    reference dropped before a new shot is created.
    """

    __slots__ = (
        "name",
        "version",
        "shot_id",
        "prompt",
        "guidance_strength",
        "export_images",
        "render_output_types",
        "render_resolution_percentage",
        "handheld",
        "handheld_strength",
        "speed",
    )

    def __init__(self, shot):
        self.name = shot.name
        self.version = int(shot.version)
        self.shot_id = shot.shot_id
        self.prompt = shot.prompt
        self.guidance_strength = shot.guidance_strength
        self.export_images = bool(getattr(shot, "export_images", True))
        self.render_output_types = set(shot.render_output_types)
        self.render_resolution_percentage = int(shot.render_resolution_percentage)
        self.handheld = bool(shot.handheld)
        self.handheld_strength = float(shot.handheld_strength)
        self.speed = float(getattr(shot, "speed", 0.0))


def create_shot(scene, camera, *, parent=None):
    """Create and activate a draft take referencing native scene data."""
    state = scene.mixar_director
    if parent is not None and not isinstance(parent, _ShotSnapshot):
        parent = _ShotSnapshot(parent)
    shot = state.shots.add()
    shot.shot_id = uuid.uuid4().hex
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
        shot.export_images = parent.export_images
        shot.render_output_types = set(parent.render_output_types)
        shot.render_resolution_percentage = parent.render_resolution_percentage
        # The take shares the parent's camera keys, so the Speed slider must
        # rest where the parent left it; no beats exist yet, so this retimes
        # nothing.
        shot.speed = parent.speed
    state.active_shot_index = len(state.shots) - 1
    scene.camera = camera
    return shot


def split_shot(scene, shot, frame: int):
    """Move the keyframes after *frame* into a new shot on the same camera.

    Native camera keys stay put — both shots read the same camera animation
    and each scopes its own preview range through its beats, exactly like
    two hand-built shots sharing a camera would.
    """
    if shot.state != 'DRAFT':
        raise ValueError("Create a new take before splitting a locked shot")
    moving = [
        index for index, beat in enumerate(shot.beats) if beat.frame > frame
    ]
    if not moving or len(moving) == len(shot.beats):
        raise ValueError(
            "Place the playhead between two keyframes to split the shot"
        )
    state = scene.mixar_director
    original_index = shot_index(state, shot)
    # Everything read from *shot* must be copied out first: adding the new
    # shot reallocates the collection and leaves this reference dangling.
    carried = _ShotSnapshot(shot)
    moved_beats = [
        (
            shot.beats[index].beat_id,
            int(shot.beats[index].frame),
            shot.beats[index].image,
        )
        for index in moving
    ]
    camera = shot.camera

    from .retime import note_beat_timing

    new_shot = create_shot(scene, camera)
    new_shot.prompt = carried.prompt
    new_shot.guidance_strength = carried.guidance_strength
    new_shot.export_images = carried.export_images
    new_shot.render_output_types = set(carried.render_output_types)
    new_shot.render_resolution_percentage = carried.render_resolution_percentage
    # Set before any beat exists: the speed update retimes nothing, and the
    # copied frames are then recorded under the speed they were made at.
    new_shot.speed = carried.speed
    for beat_id, beat_frame, beat_image in moved_beats:
        copy = new_shot.beats.add()
        copy.beat_id = beat_id
        copy.frame = beat_frame
        copy.image = beat_image
        note_beat_timing(new_shot, copy)

    # Re-resolve the original shot: its pre-add reference is no longer valid.
    shot = state.shots[original_index]
    for index in reversed(moving):
        shot.beats.remove(index)
    shot.active_beat_index = max(0, len(shot.beats) - 1)
    new_shot.active_beat_index = 0
    refresh_manifest(scene, shot)
    refresh_manifest(scene, new_shot)
    # Keep directing the first half: the playhead still sits inside it.
    state.active_shot_index = original_index
    release_preview_range(scene)
    return new_shot


def create_new_take(scene, shot):
    """Create an editable child take without mutating a locked shot."""
    # Snapshot before the add: the parent reference dies with the realloc.
    parent = _ShotSnapshot(shot)
    take = create_shot(scene, shot.camera, parent=parent)
    # The take shares the parent's camera, whose F-curves already carry any
    # handheld modifiers — inherit the setting so the toggle stays truthful.
    take.handheld_strength = parent.handheld_strength
    take.handheld = parent.handheld
    return take


def remove_shot(scene, index: int) -> bool:
    """Remove shot metadata, preserving the camera object and images.

    The camera's Director-authored motion goes with the last shot that
    references it — otherwise scrubbing keeps animating a camera whose
    strip no longer exists. Takes sharing the camera keep the animation.
    """
    from .capture import camera_shared_elsewhere, purge_camera_animation

    state = scene.mixar_director
    if index < 0 or index >= len(state.shots):
        return False
    shot = state.shots[index]
    camera = shot.camera
    release_motion = camera is not None and not camera_shared_elsewhere(
        scene, shot
    )
    state.shots.remove(index)
    if release_motion:
        purge_camera_animation(camera)
    state.active_shot_index = min(index, max(0, len(state.shots) - 1))
    release_preview_range(scene)
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
    from .record import suspend_recording

    # Sampling evaluates other frames and then restores the playhead. Neither
    # the recorder nor the one-shot playback stop may treat it as live input.
    with suspend_recording():
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
    from .rotation_curves import repair_rotation_continuity

    repair_rotation_continuity(shot.camera)
    serialized = compile_manifest(scene, shot)
    shot.snapshot_json = serialized
    shot.locked_at = str(json.loads(serialized)["exported_at"])
    shot.state = 'LOCKED'
    return serialized
