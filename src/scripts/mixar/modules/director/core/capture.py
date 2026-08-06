# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Capture camera poses as native keyframes and packed moodboard stills."""

from __future__ import annotations

import os
import tempfile
import uuid

import bpy

from .frame_math import frames_per_beat, next_beat_frame
from .shot_api import refresh_manifest, scope_preview_range
from .viewport import enter_camera_view, find_view3d_context


def _rotation_data_path(camera) -> str:
    if camera.rotation_mode == 'QUATERNION':
        return "rotation_quaternion"
    if camera.rotation_mode == 'AXIS_ANGLE':
        return "rotation_axis_angle"
    return "rotation_euler"


def _key_camera(camera, frame: int) -> None:
    camera.keyframe_insert(data_path="location", frame=frame, group="Director")
    camera.keyframe_insert(
        data_path=_rotation_data_path(camera),
        frame=frame,
        group="Director",
    )
    camera.data.keyframe_insert(data_path="lens", frame=frame, group="Director")


def _delete_camera_keys(camera, frame: int) -> None:
    for target, data_path in (
        (camera, "location"),
        (camera, _rotation_data_path(camera)),
        (camera.data, "lens"),
    ):
        try:
            target.keyframe_delete(data_path=data_path, frame=frame)
        except (RuntimeError, TypeError):
            pass


def _render_viewport_still(
    context, scene, display_name: str, prompt: str, group_name: str = ""
):
    target = find_view3d_context(context)
    if target is None:
        raise RuntimeError("No 3D viewport is available")
    window, area, region, space = target
    render = scene.render
    image_settings = render.image_settings
    old = {
        "filepath": render.filepath,
        "percentage": render.resolution_percentage,
        "media_type": getattr(image_settings, "media_type", None),
        "format": image_settings.file_format,
        "color_mode": image_settings.color_mode,
    }
    temp_dir = bpy.app.tempdir or tempfile.gettempdir()
    path = os.path.join(temp_dir, f"mixar_director_{uuid.uuid4().hex}.png")
    try:
        render.filepath = path
        longest_edge = max(render.resolution_x, render.resolution_y, 1)
        render.resolution_percentage = min(100, max(1, round(128000 / longest_edge)))
        # Blender 5 filters file formats by media type: a scene whose output
        # is FFMPEG video rejects PNG until the settings return to IMAGE.
        if old["media_type"] is not None:
            image_settings.media_type = 'IMAGE'
        image_settings.file_format = 'PNG'
        image_settings.color_mode = 'RGB'
        with context.temp_override(
            window=window,
            area=area,
            region=region,
            space_data=space,
            scene=scene,
        ):
            result = bpy.ops.render.opengl(
                write_still=True,
                view_context=True,
            )
        if 'FINISHED' not in result or not os.path.isfile(path):
            raise RuntimeError("Viewport capture did not produce an image")

        from mixar.modules.moodboard.core.media_import import import_packed_still

        item = import_packed_still(
            scene,
            path,
            display_name=display_name,
            generation_prompt=prompt,
            selected=True,
            group_name=group_name,
        )
        return item.image
    finally:
        render.filepath = old["filepath"]
        render.resolution_percentage = old["percentage"]
        # Restore the media type first: a video file format such as FFMPEG
        # only exists again once the settings are back in the VIDEO namespace.
        if old["media_type"] is not None:
            image_settings.media_type = old["media_type"]
        image_settings.file_format = old["format"]
        image_settings.color_mode = old["color_mode"]
        try:
            os.remove(path)
        except OSError:
            pass


def capture_beat(context, shot, beat_seconds: float):
    """Capture the live camera pose at the next sparse timeline keyframe."""
    if shot.state != 'DRAFT':
        raise ValueError("Create a new take before editing a locked shot")
    camera = shot.camera
    scene = shot.scene_ref or context.scene
    if camera is None or camera.type != 'CAMERA':
        raise ValueError("Choose a camera before capturing a keyframe")

    enter_camera_view(context, camera, remember=False)
    world_matrix = camera.matrix_world.copy()
    lens = float(camera.data.lens)
    original_frame = scene.frame_current
    stride = frames_per_beat(
        beat_seconds,
        scene.render.fps,
        scene.render.fps_base,
    )
    # Place the beat where the playhead sits so the slider defines its time.
    # Fall back to the next automatic stride when the playhead is before the
    # start or already holds a beat (the repeat-capture quick flow).
    taken = {int(beat.frame) for beat in shot.beats}
    target_frame = int(scene.frame_current)
    if target_frame < scene.frame_start or target_frame in taken:
        target_frame = next_beat_frame(
            taken,
            frame_start=scene.frame_start,
            stride=stride,
        )
    try:
        scene.frame_set(target_frame)
        camera.matrix_world = world_matrix
        camera.data.lens = lens
        context.view_layer.update()
        number = len(shot.beats) + 1
        image = _render_viewport_still(
            context,
            scene,
            f"{shot.name} · Keyframe {number:02d}",
            shot.prompt,
            group_name=shot.name,
        )
        _key_camera(camera, target_frame)
        if shot.handheld:
            # The first capture creates the F-curves noise can attach to.
            from .handheld import refresh_handheld

            refresh_handheld(shot)
        beat = shot.beats.add()
        beat.beat_id = uuid.uuid4().hex
        beat.frame = target_frame
        beat.image = image
        shot.active_beat_index = len(shot.beats) - 1
        scene.frame_end = max(scene.frame_end, target_frame)
        refresh_manifest(scene, shot)
        scope_preview_range(scene, shot)

        from .auto_key import mark_captured

        mark_captured(shot)
        return beat
    except Exception:
        scene.frame_set(original_frame)
        camera.matrix_world = world_matrix
        camera.data.lens = lens
        raise


def remove_beat(scene, shot, index: int) -> bool:
    """Remove one sparse keyframe, its camera keys, and its moodboard capture."""
    if shot.state != 'DRAFT' or index < 0 or index >= len(shot.beats):
        return False
    beat = shot.beats[index]
    image = beat.image
    _delete_camera_keys(shot.camera, beat.frame)

    if image is not None and hasattr(scene, "mixie_moodboard_images"):
        for item_index in range(len(scene.mixie_moodboard_images) - 1, -1, -1):
            if scene.mixie_moodboard_images[item_index].image == image:
                scene.mixie_moodboard_images.remove(item_index)
    shot.beats.remove(index)
    shot.active_beat_index = min(index, max(0, len(shot.beats) - 1))

    if image is not None:
        still_used = any(
            item.image == image for item in scene.mixie_moodboard_images
        ) if hasattr(scene, "mixie_moodboard_images") else False
        if not still_used and getattr(image, "users", 0) == 0:
            try:
                bpy.data.images.remove(image)
            except Exception:
                pass
    refresh_manifest(scene, shot)
    scope_preview_range(scene, shot)
    return True
