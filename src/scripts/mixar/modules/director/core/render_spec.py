# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure ordering and timing rules for Director shot renders."""

from __future__ import annotations

from .frame_math import effective_fps


RENDER_KIND_ORDER = ("BEAUTY", "CLAY", "DEPTH")


def ordered_render_kinds(selected) -> tuple[str, ...]:
    """Return selected render kinds in a stable production order."""
    enabled = {str(kind) for kind in selected}
    return tuple(kind for kind in RENDER_KIND_ORDER if kind in enabled)


def render_frame_bounds(frames) -> tuple[int, int]:
    """Return the first/last distinct frame, requiring an animatable span."""
    ordered = sorted({int(frame) for frame in frames})
    if len(ordered) < 2:
        raise ValueError("Capture at least two keyframes to render a video")
    return ordered[0], ordered[-1]


def render_duration_seconds(
    frame_start: int,
    frame_end: int,
    fps: float,
    fps_base: float,
) -> float:
    """Duration between the inclusive shot endpoints in timeline seconds."""
    return max(0, int(frame_end) - int(frame_start)) / effective_fps(
        fps,
        fps_base,
    )
