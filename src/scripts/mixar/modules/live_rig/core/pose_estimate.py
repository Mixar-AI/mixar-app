# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Body / face landmark estimation from a camera frame.

Scaffold returns an empty landmark set so retarget + apply stay callable.
Replace :func:`estimate_pose` with MediaPipe (or similar) without changing
callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from .capture import Frame


@dataclass
class PoseLandmarks:
    """Named 3D landmarks in camera space (normalized or metres — TBD)."""

    points: Dict[str, tuple[float, float, float]] = field(default_factory=dict)
    confidence: float = 0.0
    timestamp: float = 0.0


def estimate_pose(frame: Frame) -> PoseLandmarks:
    """Estimate actor landmarks from *frame*.

    Scaffold: empty landmarks with confidence 0. Real backends should fill
    a stable set of keys (hips, spine, shoulders, elbows, wrists, …) that
    :mod:`retarget` understands.
    """
    return PoseLandmarks(points={}, confidence=0.0, timestamp=frame.timestamp)
