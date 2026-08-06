# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cached world-space sampling of a shot camera's path for the overlay.

The path is sampled from the camera's location F-curves directly
(``fcurve.evaluate`` is pure curve math and includes the handheld noise
modifiers) — never by scrubbing ``scene.frame_set``, which would
re-evaluate the whole depsgraph per sample. Samples rebuild only when a
cheap signature of the animation changes, so a viewport redraw normally
costs one cached read.
"""

from __future__ import annotations

MAX_SAMPLES = 256
MIN_SAMPLES = 32

_cache = {"key": None, "samples": (), "beats": ()}


def _location_fcurves(camera) -> dict:
    from .anim_curves import assigned_fcurves

    return {
        fcurve.array_index: fcurve
        for fcurve in assigned_fcurves(camera)
        if fcurve.data_path == "location"
    }


def _evaluate(fcurves: dict, fallback, frame: float) -> tuple:
    return tuple(
        fcurves[axis].evaluate(frame) if axis in fcurves else fallback[axis]
        for axis in range(3)
    )


def _signature(shot, camera, frames, fcurves: dict):
    probes = tuple(
        (
            axis,
            len(fcurve.keyframe_points),
            round(sum(point.co[1] for point in fcurve.keyframe_points), 4),
            len(fcurve.modifiers),
        )
        for axis, fcurve in sorted(fcurves.items())
    )
    return (
        camera.name,
        frames,
        bool(shot.handheld),
        round(float(shot.handheld_strength), 3),
        probes,
    )


def sample_path(shot):
    """``(path_points, beat_points)`` in world space, or empty tuples."""
    camera = shot.camera
    if camera is None or len(shot.beats) < 2:
        return (), ()
    frames = tuple(sorted({int(beat.frame) for beat in shot.beats}))
    if frames[-1] - frames[0] < 1:
        return (), ()
    fcurves = _location_fcurves(camera)
    if not fcurves:
        return (), ()
    key = _signature(shot, camera, frames, fcurves)
    if _cache["key"] == key:
        return _cache["samples"], _cache["beats"]

    fallback = tuple(camera.location)
    span = frames[-1] - frames[0]
    count = max(MIN_SAMPLES, min(MAX_SAMPLES, span + 1))
    samples = tuple(
        _evaluate(fcurves, fallback, frames[0] + span * (index / (count - 1)))
        for index in range(count)
    )
    beats = tuple(_evaluate(fcurves, fallback, frame) for frame in frames)
    _cache.update({"key": key, "samples": samples, "beats": beats})
    return samples, beats


def playhead_point(scene, shot):
    """Where the camera sits at the current frame, or ``None``.

    Cheap enough to recompute every redraw — playback moves it constantly.
    """
    camera = shot.camera
    if camera is None or not shot.beats:
        return None
    fcurves = _location_fcurves(camera)
    if not fcurves:
        return None
    frames = sorted(int(beat.frame) for beat in shot.beats)
    frame = min(max(int(scene.frame_current), frames[0]), frames[-1])
    return _evaluate(fcurves, tuple(camera.location), frame)


def clear_cache() -> None:
    _cache.update({"key": None, "samples": (), "beats": ()})
