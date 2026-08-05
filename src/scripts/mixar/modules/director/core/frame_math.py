# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure timeline math for sparse camera beats."""

from __future__ import annotations

from collections.abc import Iterable


def effective_fps(fps: float, fps_base: float = 1.0) -> float:
    """Return Blender's effective frames-per-second value."""
    fps_value = float(fps)
    base_value = float(fps_base)
    if fps_value <= 0.0:
        raise ValueError("fps must be greater than zero")
    if base_value <= 0.0:
        raise ValueError("fps_base must be greater than zero")
    return fps_value / base_value


def frames_per_beat(
    seconds: float,
    fps: float,
    fps_base: float = 1.0,
) -> int:
    """Convert a director-facing beat interval to at least one frame."""
    return max(1, round(max(0.0, float(seconds)) * effective_fps(fps, fps_base)))


def next_beat_frame(
    existing_frames: Iterable[int],
    *,
    frame_start: int,
    stride: int,
) -> int:
    """Return the first frame, then one stride beyond the latest beat."""
    frames = [int(frame) for frame in existing_frames]
    if not frames:
        return int(frame_start)
    return max(frames) + max(1, int(stride))


def seconds_from_frame(
    frame: int,
    *,
    origin_frame: int,
    fps: float,
    fps_base: float = 1.0,
) -> float:
    """Return zero-based seconds from *origin_frame*."""
    return (int(frame) - int(origin_frame)) / effective_fps(fps, fps_base)


def clamp_frame_delta(
    frames: Iterable[int],
    requested_delta: int,
    *,
    minimum_frame: int,
    maximum_frame: int = 1048574,
) -> int:
    """Clamp a shared frame offset without changing the strip's spacing."""
    values = [int(frame) for frame in frames]
    if not values:
        return 0
    lower = int(minimum_frame) - min(values)
    upper = int(maximum_frame) - max(values)
    return min(max(int(requested_delta), lower), upper)
