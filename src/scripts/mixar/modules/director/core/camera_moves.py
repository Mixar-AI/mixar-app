# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One-click cinematic camera moves that generate sparse shot keyframes.

Every move starts from the camera's live pose, computes two or three
target poses, and runs each through the ordinary ``capture_beat`` flow —
so a preset produces exactly what manual directing produces: native camera
keys, packed Moodboard stills, and manifest entries, spaced by the shot's
Keyframe Spacing. Nothing bespoke is stored.
"""

from __future__ import annotations

import math

from .capture import capture_beat
from .frame_math import frames_per_beat

# (key, label, tooltip)
CAMERA_MOVES = (
    ("ORBIT_LEFT", "Orbit Left", "Arc left around the subject, keeping it framed"),
    ("ORBIT_RIGHT", "Orbit Right", "Arc right around the subject, keeping it framed"),
    ("DOLLY_IN", "Dolly In", "Move toward the subject along the view direction"),
    ("DOLLY_OUT", "Dolly Out", "Move away from the subject along the view direction"),
    ("CRANE_UP", "Crane Up", "Rise above the subject while keeping it framed"),
    ("CRANE_DOWN", "Crane Down", "Descend toward the ground while keeping it framed"),
    ("PAN_LEFT", "Pan Left", "Rotate the camera left in place"),
    ("PAN_RIGHT", "Pan Right", "Rotate the camera right in place"),
)

_ORBIT_DEGREES = 60.0
_PAN_DEGREES = 40.0
_DOLLY_FACTOR = 0.4
_CRANE_FACTOR = 0.35
_FALLBACK_INTEREST = 6.0


def _camera_axes(matrix):
    from mathutils import Vector

    forward = -Vector((matrix[0][2], matrix[1][2], matrix[2][2]))
    if forward.length < 1e-6:
        forward = Vector((0.0, -1.0, 0.0))
    return forward.normalized()


def interest_distance(scene, camera) -> float:
    """How far away the subject is, from visible mesh bounds ahead of us."""
    from mathutils import Vector

    matrix = camera.matrix_world
    location = matrix.translation
    forward = _camera_axes(matrix)
    depths = []
    for obj in scene.objects:
        if obj.type != 'MESH' or not obj.visible_get():
            continue
        center = obj.matrix_world.translation
        depth = (Vector(center) - location).dot(forward)
        if depth > 0.1:
            depths.append(depth)
    if not depths:
        return _FALLBACK_INTEREST
    depths.sort()
    median = depths[len(depths) // 2]
    return max(0.5, min(median, 200.0))


def _aim_at(location, target):
    """A level camera matrix at *location* looking at *target*."""
    from mathutils import Matrix

    direction = target - location
    if direction.length < 1e-6:
        return Matrix.Translation(location)
    matrix = direction.normalized().to_track_quat('-Z', 'Y').to_matrix().to_4x4()
    matrix.translation = location
    return matrix


def move_poses(scene, camera, move: str):
    """Target world matrices for *move*, excluding the current pose."""
    from mathutils import Matrix, Vector

    matrix = camera.matrix_world.copy()
    location = matrix.translation.copy()
    forward = _camera_axes(matrix)
    distance = interest_distance(scene, camera)
    pivot = location + forward * distance

    if move in {"ORBIT_LEFT", "ORBIT_RIGHT"}:
        sign = 1.0 if move == "ORBIT_LEFT" else -1.0
        total = math.radians(_ORBIT_DEGREES) * sign
        poses = []
        # A midpoint beat keeps the arc an arc instead of a straight cut.
        for fraction in (0.5, 1.0):
            rotation = Matrix.Rotation(total * fraction, 4, 'Z')
            offset = rotation @ (location - pivot)
            poses.append(_aim_at(pivot + offset, pivot))
        return poses
    if move in {"DOLLY_IN", "DOLLY_OUT"}:
        sign = 1.0 if move == "DOLLY_IN" else -1.0
        target = matrix.copy()
        target.translation = location + forward * (distance * _DOLLY_FACTOR * sign)
        return [target]
    if move in {"CRANE_UP", "CRANE_DOWN"}:
        sign = 1.0 if move == "CRANE_UP" else -1.0
        lifted = location + Vector((0.0, 0.0, distance * _CRANE_FACTOR * sign))
        return [_aim_at(lifted, pivot)]
    if move in {"PAN_LEFT", "PAN_RIGHT"}:
        sign = 1.0 if move == "PAN_LEFT" else -1.0
        rotation = Matrix.Rotation(math.radians(_PAN_DEGREES) * sign, 4, 'Z')
        # Yaw around world Z in place: rotate the orientation, keep the spot.
        target = rotation @ matrix
        target.translation = location
        return [target]
    raise ValueError(f"Unknown camera move '{move}'")


def apply_camera_move(context, shot, state, move: str):
    """Capture the current pose plus each target pose as sparse keyframes."""
    scene = shot.scene_ref or context.scene
    camera = shot.camera
    poses = move_poses(scene, camera, move)
    stride = frames_per_beat(
        state.beat_seconds,
        scene.render.fps,
        scene.render.fps_base,
    )
    beats = []
    taken = {int(beat.frame) for beat in shot.beats}
    if int(scene.frame_current) not in taken:
        # Anchor the move where the camera stands right now, unless the
        # playhead already sits on a captured keyframe of this shot.
        beats.append(capture_beat(context, shot, state.beat_seconds))
    for pose in poses:
        if beats:
            scene.frame_set(int(beats[-1].frame) + stride)
        camera.matrix_world = pose
        context.view_layer.update()
        beats.append(capture_beat(context, shot, state.beat_seconds))
    return beats
