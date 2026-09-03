# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Walk-style camera motion for the Cinema Mode WASD/QE hints.

The top strip advertises W/A/S/D and Q/E at all times, but those keys only
ever existed inside `view3d.walk`, which `MIXAR_OT_director_navigate`
supervises — so outside Navigate the hints described nothing. This is the
motion behind them: one step per key press, along the same axes walk uses.

Two things it deliberately does NOT do. It never keys anything: it moves the
camera and leaves recording to the existing auto-key / capture flow, exactly
as walk does. And it derives its speed from Blender's own walk preference
rather than a private constant, so "how fast is WASD" has one answer in the
app.

Distance is time-based, not per-press: a key held down repeats at whatever
rate the OS decides, so a fixed per-press step would travel at a different
speed on every machine. Multiplying the walk speed by the real elapsed time
since the previous press makes a held key move at `walk_speed` regardless.
"""

from __future__ import annotations

# (identifier, label, tooltip)
NUDGE_DIRECTIONS = (
    ("FORWARD", "Forward", "Move the camera along its view direction"),
    ("BACK", "Back", "Move the camera against its view direction"),
    ("LEFT", "Left", "Strafe the camera left"),
    ("RIGHT", "Right", "Strafe the camera right"),
    ("UP", "Up", "Raise the camera along the world Z axis"),
    ("DOWN", "Down", "Lower the camera along the world Z axis"),
)

_VERTICAL = {"UP", "DOWN"}

# A gap longer than this is a fresh tap rather than an auto-repeat, so it is
# not allowed to bank up distance while the user was reading the screen.
MAX_STEP_SECONDS = 0.12
# What a single tap is worth. Below this a lone press barely registers.
FIRST_STEP_SECONDS = 0.05

DEFAULT_WALK_SPEED = 3.0


def walk_speed(context) -> float:
    """Blender's own walk-navigation speed, in scene units per second."""
    try:
        speed = context.preferences.view.walk_navigation.walk_speed
    except AttributeError:
        return DEFAULT_WALK_SPEED
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        return DEFAULT_WALK_SPEED
    return speed if speed > 0.0 else DEFAULT_WALK_SPEED


def step_seconds(now: float, last: float | None) -> float:
    """Seconds of travel this press is worth."""
    if last is None:
        return FIRST_STEP_SECONDS
    elapsed = now - last
    if elapsed <= 0.0 or elapsed > MAX_STEP_SECONDS:
        return FIRST_STEP_SECONDS
    return max(elapsed, FIRST_STEP_SECONDS)


def nudge_offset(camera, direction: str, distance: float):
    """World-space offset for one step of *direction*.

    W/S and A/D ride the camera's own axes — forward is its local -Z, the way
    walk flies with gravity off — while Q/E move on world Z, which is what the
    strip's "Z-axis" label means and what walk's up/down do.
    """
    from mathutils import Vector

    if direction in _VERTICAL:
        axis = Vector((0.0, 0.0, 1.0 if direction == "UP" else -1.0))
    else:
        matrix = camera.matrix_world
        if direction in {"LEFT", "RIGHT"}:
            axis = Vector(matrix.col[0][:3])
            if direction == "LEFT":
                axis = -axis
        else:
            axis = -Vector(matrix.col[2][:3])
            if direction == "BACK":
                axis = -axis
        length = axis.length
        if length <= 1e-6:
            return Vector((0.0, 0.0, 0.0))
        axis = axis / length
    return axis * distance


def move_camera(camera, offset) -> None:
    """Translate *camera* by a world-space *offset*.

    Written through ``matrix_world`` so a parented camera moves the distance
    asked for rather than the distance its parent's transform makes of it.
    """
    matrix = camera.matrix_world.copy()
    matrix.translation = matrix.translation + offset
    camera.matrix_world = matrix
