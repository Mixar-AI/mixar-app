# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Retime a shot with the Cinema Mode Speed slider.

``shot.speed`` scales every interval between the shot's keyframes relative
to the FIRST beat, whose frame never moves::

    factor(speed) = 2 ** (-speed)
    frame = first + round((time_base - first) * factor(speed))

``beat.time_base`` is the beat's frame at speed 0 — the timing as captured.
Storing it as a float per beat is what keeps a slider drag drift-free: one
drag fires the update dozens of times, and rescaling the current integer
frames on every tick would accumulate rounding until the shot came back
from ``0 -> 1 -> 0`` with different frames. The speed update therefore never
derives ``time_base`` from the frames; every OTHER writer of ``beat.frame``
(capture, adoption, timeline drags, shot split) records it through
:func:`note_beat_timing` / :func:`shift_shot_timing`.

Beats saved before this feature carry ``time_base == 0.0`` and are backfilled
lazily from their frame, so old files behave as if their current timing is
speed 0.
"""

from __future__ import annotations

import math

from .shot_api import refresh_manifest, scope_preview_range


def speed_factor(speed: float) -> float:
    """Duration multiplier for *speed*: ``+1`` halves intervals, ``-1`` doubles."""
    return 2.0 ** (-float(speed))


def _round_frame(value: float) -> int:
    # Half-up rounding: ``round()`` is banker's and would pair frames oddly.
    return int(math.floor(float(value) + 0.5))


def _recorded_time_base(beat) -> float:
    """The beat's ``time_base``, backfilled from its frame when unrecorded."""
    time_base = float(getattr(beat, "time_base", 0.0))
    if time_base == 0.0 and int(beat.frame) != 0:
        time_base = float(int(beat.frame))
        try:
            beat.time_base = time_base
        except Exception:
            # Read-only stand-ins (or a locked file) still get a usable value.
            pass
    return time_base


def _anchor(shot):
    """The chronologically first beat — the shot's anchor — or ``None``."""
    beats = list(shot.beats)
    if not beats:
        return None
    return min(beats, key=lambda beat: int(beat.frame))


def note_beat_timing(shot, beat) -> None:
    """Record ``beat.time_base`` from its current frame at the shot's speed.

    Call this whenever a beat's frame is set by anything OTHER than the
    speed update. When *beat* is (or becomes) the shot's anchor, every beat
    is re-recorded: the anchor moving changes every interval measured from it.
    """
    factor = speed_factor(getattr(shot, "speed", 0.0))
    frame = int(beat.frame)
    anchor = _anchor(shot)
    first = int(anchor.frame) if anchor is not None else frame
    if frame <= first:
        # *beat* is the anchor (or ties it): rebase everything on it.
        for other in shot.beats:
            other.time_base = frame + (int(other.frame) - frame) / factor
        beat.time_base = float(frame)
        return
    # The anchor's base equals its frame whenever it was recorded here; a
    # backfilled old file agrees, so this is the exact inverse of the retime.
    first_base = _recorded_time_base(anchor)
    beat.time_base = first_base + (frame - first) / factor


def shift_shot_timing(shot, delta: int) -> None:
    """Slide every recorded ``time_base`` by *delta* after a whole-strip move.

    A uniform shift keeps every interval, so shifting the stored bases is
    exact where re-recording from the rounded frames would lose sub-frame
    timing; beats without a recorded base are recorded fresh.
    """
    delta = int(delta)
    unrecorded = []
    for beat in shot.beats:
        time_base = float(getattr(beat, "time_base", 0.0))
        if time_base == 0.0 and int(beat.frame) - delta != 0:
            unrecorded.append(beat)
            continue
        beat.time_base = time_base + delta
    for beat in unrecorded:
        note_beat_timing(shot, beat)


def retimed_frames(shot, speed: float) -> list[tuple[int, int]]:
    """Return ``(old_frame, new_frame)`` per beat, in collection order.

    Frames are scaled relative to the anchor; beats that would collapse onto
    one frame after rounding stay at least one frame apart, in chronological
    order — keys are never merged.
    """
    beats = list(shot.beats)
    if not beats:
        return []
    factor = speed_factor(speed)
    order = sorted(range(len(beats)), key=lambda i: (int(beats[i].frame), i))
    anchor = beats[order[0]]
    first = int(anchor.frame)
    first_base = _recorded_time_base(anchor)
    targets = [0] * len(beats)
    previous = None
    for i in order:
        base = _recorded_time_base(beats[i])
        frame = first + _round_frame((base - first_base) * factor)
        if previous is not None and frame <= previous:
            frame = previous + 1
        targets[i] = frame
        previous = frame
    return [(int(beat.frame), targets[i]) for i, beat in enumerate(beats)]


def apply_shot_speed(scene, shot) -> int:
    """Retime *shot*'s beats and native camera keys to ``shot.speed``.

    Returns how many beats moved. Locked shots are left untouched. Every
    key is matched BEFORE any frame changes, so the moves never collide
    mid-way regardless of direction.
    """
    if shot is None or getattr(shot, "state", "DRAFT") != 'DRAFT':
        return 0
    camera = getattr(shot, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return 0
    moves = retimed_frames(shot, getattr(shot, "speed", 0.0))
    changed = [(old, new) for old, new in moves if old != new]
    if not changed:
        return 0

    from .timeline import _CAMERA_PATHS, _director_keyframes, _restore_shift

    old_frames = {old for old, _new in changed}
    object_curves, object_points = _director_keyframes(
        camera, _CAMERA_PATHS, old_frames
    )
    data_curves, data_points = _director_keyframes(
        camera.data, {"lens"}, old_frames
    )
    curves = object_curves + data_curves
    points = object_points + data_points
    point_positions = [
        (
            point,
            float(point.co[0]),
            float(point.handle_left[0]),
            float(point.handle_right[0]),
        )
        for point in points
    ]
    delta_by_frame = {old: new - old for old, new in changed}
    point_deltas = [
        (point, delta_by_frame[_round_frame(co_x)])
        for point, co_x, _left, _right in point_positions
        if _round_frame(co_x) in delta_by_frame
    ]
    beat_frames = [old for old, _new in moves]
    scene_state = (
        int(scene.frame_current),
        int(scene.frame_end),
        int(scene.frame_preview_start),
        int(scene.frame_preview_end),
    )
    manifest_json = shot.manifest_json

    try:
        for point, delta in point_deltas:
            point.co[0] += delta
            point.handle_left[0] += delta
            point.handle_right[0] += delta
        for fcurve in curves:
            fcurve.update()
        for beat, (_old, new) in zip(shot.beats, moves, strict=True):
            if int(beat.frame) != new:
                beat.frame = new
        last = max(new for _old, new in moves)
        scene.frame_end = max(int(scene.frame_end), last)
        scope_preview_range(scene, shot)
        refresh_manifest(scene, shot)
    except Exception:
        _restore_shift(
            scene,
            shot,
            beat_frames,
            point_positions,
            curves,
            scene_state,
            manifest_json,
        )
        raise
    return len(changed)
