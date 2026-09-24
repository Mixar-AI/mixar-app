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
from .keying import key_camera_pose
from .retime import note_beat_timing
from .rotation_curves import repair_rotation_continuity, rotation_data_path
from .shot_api import refresh_manifest, release_preview_range, shot_scene
from .viewport import enter_camera_view, find_view3d_context


def _key_camera(camera, frame: int) -> None:
    key_camera_pose(camera, frame)
    repair_rotation_continuity(camera)


def _delete_camera_keys(camera, frame: int) -> None:
    # A shot whose camera object was deleted keeps a None pointer; removing
    # its keyframes must still clean up the beat and its moodboard still.
    if camera is None:
        return
    for target, data_path in (
        (camera, "location"),
        (camera, rotation_data_path(camera)),
        (camera.data, "lens"),
    ):
        try:
            target.keyframe_delete(data_path=data_path, frame=frame)
        except (RuntimeError, TypeError):
            pass
    repair_rotation_continuity(camera)


_CAMERA_MOTION_PATHS = {
    "location",
    "rotation_euler",
    "rotation_quaternion",
    "rotation_axis_angle",
}


def purge_camera_animation(camera) -> None:
    """Delete the camera's transform/lens F-curves and handheld noise.

    Per-frame key deletion leaves strays behind whenever keys exist off the
    tracked beat frames (native auto-keying, hand-inserted keys, drifted
    edits) — and a fully deleted strip must leave a genuinely static
    camera. Director owns its shot cameras' motion, so when the last shot
    referencing a camera lets go, the motion goes with it.
    """
    from .anim_curves import remove_fcurves
    from .handheld import remove_handheld

    remove_handheld(camera)
    remove_fcurves(camera, _CAMERA_MOTION_PATHS)
    remove_fcurves(camera.data, {"lens"})


def camera_shared_elsewhere(scene, shot) -> bool:
    """Whether another shot (any state) still directs *shot*'s camera."""
    state = getattr(scene, "mixar_director", None)
    if state is None or shot.camera is None:
        return False
    me = shot.as_pointer()
    return any(
        item.camera == shot.camera and item.as_pointer() != me
        for item in state.shots
    )


def _render_splat_still(scene, camera):
    """Capture a splat scene's still through a real EEVEE render.

    A viewport OpenGL capture comes out blank in splat scenes: the KIRI
    proxy draws only during interactive viewport redraws (never inside
    ``render.opengl``), the splat mesh itself is eye-hidden, and the
    splat_render_camera handlers that push camera matrices into the
    geometry-nodes sockets fire only for real renders. So capture the way
    the Beauty video pass renders: EEVEE evaluating the splat's
    camera-facing quads, with the render handlers feeding the camera.
    """
    from mixar.modules.moodboard.core.splat_render_camera import (
        enable_render_updates,
    )

    render = scene.render
    old_engine = render.engine
    old_samples = scene.eevee.taa_render_samples
    old_camera = scene.camera
    try:
        # Safe no-op when already enabled; covers splats from files saved
        # before import-time enabling existed.
        enable_render_updates(scene.objects)
        scene.camera = camera
        render.engine = 'BLENDER_EEVEE'
        scene.eevee.taa_render_samples = 16
        return bpy.ops.render.render(write_still=True)
    finally:
        render.engine = old_engine
        scene.eevee.taa_render_samples = old_samples
        scene.camera = old_camera


def _render_viewport_still(context, scene, camera, display_name: str):
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
        from mixar.modules.moodboard.core.splat_render_camera import (
            scene_has_splats,
        )

        with context.temp_override(
            window=window,
            area=area,
            region=region,
            space_data=space,
            scene=scene,
        ):
            if scene_has_splats(scene):
                result = _render_splat_still(scene, camera)
            else:
                result = bpy.ops.render.opengl(
                    write_still=True,
                    view_context=True,
                )
        if 'FINISHED' not in result or not os.path.isfile(path):
            raise RuntimeError("Viewport capture did not produce an image")

        # Pack the still into the blend WITHOUT boarding it. Captures used to
        # land on the moodboard immediately, which cluttered the board; stills
        # now reach the board only through an explicit Export.
        from mixar.modules.moodboard.core.media_import import pack_still_image

        return pack_still_image(path, display_name=display_name)
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


def _discard_still(scene, image, shot=None) -> None:
    """Drop a replaced capture's packed still if nothing else wants it.

    Auto Key re-keys the same beat over and over while a director nudges a
    camera, and each capture renders a fresh still. Without this the
    superseded ones pile up in ``bpy.data.images`` — packed, orphaned, and
    carried into the saved file. A still that was exported to the moodboard,
    or that another beat still points at, is left alone.
    """
    if image is None:
        return
    board = getattr(scene, "mixie_moodboard_images", None)
    if board is not None and any(item.image == image for item in board):
        return
    if shot is not None and any(beat.image == image for beat in shot.beats):
        return
    if getattr(image, "users", 0) != 0:
        return
    try:
        bpy.data.images.remove(image)
    except Exception:
        # A still that cannot be freed is a leak, never a failed capture.
        pass


def capture_beat(context, shot, beat_seconds: float, *, replace_existing: bool = False):
    """Capture the live camera pose at the next sparse timeline keyframe.

    With ``replace_existing`` the playhead's own keyframe is RE-KEYED rather
    than a new one appended beyond it. That is what Auto Key needs: the
    director nudges the camera, looks at it, nudges again — all at one frame —
    and every adjustment must refine that frame's pose, not march a new
    keyframe forward through the shot. It is Blender's own auto-key rule.
    Manual capture keeps the append, which is the repeat-capture quick flow.
    """
    if shot.state != 'DRAFT':
        raise ValueError("Create a new take before editing a locked shot")
    camera = shot.camera
    scene = shot_scene(shot, context.scene)
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
    if target_frame < scene.frame_start or (
        target_frame in taken and not replace_existing
    ):
        target_frame = next_beat_frame(
            taken,
            frame_start=scene.frame_start,
            stride=stride,
        )
    # Resolved against the frame the keyframe will ACTUALLY land on. The
    # fallback above can move it — a beat left behind the scene's start is
    # the case — and an index resolved before the move points at a beat on
    # a different frame, whose still would then be replaced with a render
    # of a pose that was keyed somewhere else.
    existing_index = -1
    if replace_existing:
        for index, beat in enumerate(shot.beats):
            if int(beat.frame) == target_frame:
                existing_index = index
                break
    # Parking on the frame being keyed, and forcing the pose back onto the
    # camera, are this function doing its job — not a camera being flown.
    # `core/record.py` would otherwise hear every one of them.
    from .record import suspend_recording

    try:
        with suspend_recording():
            scene.frame_set(target_frame)
        camera.matrix_world = world_matrix
        camera.data.lens = lens
        context.view_layer.update()
        number = existing_index + 1 if existing_index >= 0 else len(shot.beats) + 1
        image = _render_viewport_still(
            context,
            scene,
            camera,
            f"{shot.name} · Keyframe {number:02d}",
        )
        _key_camera(camera, target_frame)
        from .interpolation import apply_interpolation

        # The beat for this key is not on `shot.beats` yet, so the frame is
        # named explicitly; the rest of the shot's keys come from its beats.
        apply_interpolation(shot, target_frame)
        if shot.handheld:
            # The first capture creates the F-curves noise can attach to.
            from .handheld import refresh_handheld

            refresh_handheld(shot)
        if existing_index >= 0:
            # Re-keying the playhead's own beat: `keyframe_insert` already
            # overwrote the camera's keys at this frame, so only the beat's
            # still is stale. Its id and timing are what the strip, the
            # manifest and the Speed slider identify it by, and they stay.
            beat = shot.beats[existing_index]
            superseded = beat.image
            beat.image = image
            shot.active_beat_index = existing_index
            _discard_still(scene, superseded, shot)
        else:
            beat = shot.beats.add()
            beat.beat_id = uuid.uuid4().hex
            beat.frame = target_frame
            note_beat_timing(shot, beat)
            beat.image = image
            shot.active_beat_index = len(shot.beats) - 1
        scene.frame_end = max(scene.frame_end, target_frame)
        refresh_manifest(scene, shot)
        release_preview_range(scene)

        from .auto_key import mark_captured

        mark_captured(shot)
        return beat
    except Exception:
        with suspend_recording():
            scene.frame_set(original_frame)
        camera.matrix_world = world_matrix
        camera.data.lens = lens
        raise


def remove_beat(scene, shot, index: int, *, delete_keys: bool = True) -> bool:
    """Remove one sparse keyframe, its camera keys, and its moodboard capture.

    ``delete_keys=False`` removes the beat alone, for a caller that has
    already dealt with the keys under it (a native key delete, or a drag
    that replaced them) — and then never purges the camera, whose remaining
    keys are ones the director kept.
    """
    if shot.state != 'DRAFT' or index < 0 or index >= len(shot.beats):
        return False
    beat = shot.beats[index]
    image = beat.image
    if delete_keys:
        _delete_camera_keys(shot.camera, beat.frame)

    if image is not None and hasattr(scene, "mixie_moodboard_images"):
        for item_index in range(len(scene.mixie_moodboard_images) - 1, -1, -1):
            if scene.mixie_moodboard_images[item_index].image == image:
                scene.mixie_moodboard_images.remove(item_index)
    shot.beats.remove(index)
    shot.active_beat_index = min(index, max(0, len(shot.beats) - 1))

    _discard_still(scene, image, shot)
    if (
        delete_keys
        and not shot.beats
        and shot.camera is not None
        and not camera_shared_elsewhere(scene, shot)
    ):
        # The last keyframe is gone: leave a genuinely static camera
        # instead of whatever stray keys per-frame deletion missed.
        purge_camera_animation(shot.camera)
    refresh_manifest(scene, shot)
    release_preview_range(scene)
    return True
