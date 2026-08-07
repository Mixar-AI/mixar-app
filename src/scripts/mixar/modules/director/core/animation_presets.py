# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blocking-level character motion presets keyed on native scene objects.

Phase-zero directing needs characters that MOVE through the shot, not
final limb animation — the video model animates the body, the manifest
carries the path. Each preset keys plain object-level root motion (travel,
turn, bob) from the current playhead over a chosen duration, grouped under
"Director Character" so it reads clearly in native editors and undoes as
one operator step.

Characters are assumed to face their local -Y axis, Blender's front-axis
convention; a Turn preset reorients rigs that face elsewhere.
"""

from __future__ import annotations

import math

# (key, label, tooltip)
ANIMATION_PRESETS = (
    ("WALK", "Walk Forward", "Walk ahead at a natural pace with a subtle step bob"),
    ("RUN", "Run Forward", "Run ahead with a stronger, faster stride bob"),
    ("TURN_LEFT", "Turn Left", "Turn 90 degrees to the left in place"),
    ("TURN_RIGHT", "Turn Right", "Turn 90 degrees to the right in place"),
    ("TURN_AROUND", "Turn Around", "Turn a full 180 degrees in place"),
    ("IDLE", "Idle", "Stay in place with a gentle breathing sway"),
)

_WALK_SPEED = 1.4  # metres per second
_RUN_SPEED = 3.5
_WALK_BOB = 0.03
_RUN_BOB = 0.06
_WALK_STEPS_HZ = 1.8
_RUN_STEPS_HZ = 2.8
_IDLE_BOB = 0.012
_IDLE_HZ = 0.4


def _rotation_data_path(obj) -> str:
    if obj.rotation_mode == 'QUATERNION':
        return "rotation_quaternion"
    if obj.rotation_mode == 'AXIS_ANGLE':
        return "rotation_axis_angle"
    return "rotation_euler"


def _key(obj, data_path: str, frame: int) -> None:
    obj.keyframe_insert(
        data_path=data_path,
        frame=frame,
        group="Director Character",
    )


def _forward_vector(obj):
    """The character's level world-space forward (local -Y convention)."""
    from mathutils import Vector

    matrix = obj.matrix_world
    forward = -Vector((matrix[0][1], matrix[1][1], matrix[2][1]))
    forward.z = 0.0
    if forward.length < 1e-6:
        forward = Vector((0.0, -1.0, 0.0))
    return forward.normalized()


def _fps(scene) -> float:
    base = scene.render.fps_base or 1.0
    return scene.render.fps / base


def _travel(obj, scene, frame_start: int, seconds: float, speed: float,
            bob_height: float, steps_hz: float) -> int:
    """Key straight-ahead travel with a step bob; returns the end frame."""
    from mathutils import Vector

    fps = _fps(scene)
    frame_end = frame_start + max(1, round(seconds * fps))
    forward = _forward_vector(obj)
    start = obj.location.copy()
    base_z = start.z
    # One location key per bob extreme keeps the path light but alive.
    samples = max(2, round(seconds * steps_hz * 2))
    for sample in range(samples + 1):
        fraction = sample / samples
        frame = round(frame_start + (frame_end - frame_start) * fraction)
        travel = forward * (speed * seconds * fraction)
        bob = abs(math.sin(math.pi * steps_hz * seconds * fraction)) * bob_height
        obj.location = Vector((start.x + travel.x, start.y + travel.y, base_z + bob))
        _key(obj, "location", frame)
    return frame_end


def _turn(obj, scene, frame_start: int, seconds: float, degrees: float) -> int:
    from mathutils import Matrix

    fps = _fps(scene)
    frame_end = frame_start + max(1, round(seconds * fps))
    path = _rotation_data_path(obj)
    _key(obj, path, frame_start)
    rotation = Matrix.Rotation(math.radians(degrees), 4, 'Z')
    matrix = obj.matrix_world.copy()
    target = rotation @ matrix
    target.translation = matrix.translation
    obj.matrix_world = target
    _key(obj, path, frame_end)
    return frame_end


def _idle(obj, scene, frame_start: int, seconds: float) -> int:
    from mathutils import Vector

    fps = _fps(scene)
    frame_end = frame_start + max(1, round(seconds * fps))
    start = obj.location.copy()
    samples = max(2, round(seconds * _IDLE_HZ * 2))
    for sample in range(samples + 1):
        fraction = sample / samples
        frame = round(frame_start + (frame_end - frame_start) * fraction)
        sway = math.sin(math.tau * _IDLE_HZ * seconds * fraction) * _IDLE_BOB
        obj.location = Vector((start.x, start.y, start.z + sway))
        _key(obj, "location", frame)
    obj.location = start
    return frame_end


def apply_animation_preset(scene, obj, preset: str, seconds: float) -> int:
    """Key *preset* on *obj* from the playhead; returns the end frame."""
    frame_start = int(scene.frame_current)
    if preset == "WALK":
        end = _travel(
            obj, scene, frame_start, seconds, _WALK_SPEED, _WALK_BOB, _WALK_STEPS_HZ
        )
    elif preset == "RUN":
        end = _travel(
            obj, scene, frame_start, seconds, _RUN_SPEED, _RUN_BOB, _RUN_STEPS_HZ
        )
    elif preset == "TURN_LEFT":
        end = _turn(obj, scene, frame_start, seconds, 90.0)
    elif preset == "TURN_RIGHT":
        end = _turn(obj, scene, frame_start, seconds, -90.0)
    elif preset == "TURN_AROUND":
        end = _turn(obj, scene, frame_start, seconds, 180.0)
    elif preset == "IDLE":
        end = _idle(obj, scene, frame_start, seconds)
    else:
        raise ValueError(f"Unknown animation preset '{preset}'")
    scene.frame_end = max(scene.frame_end, end)
    return end
