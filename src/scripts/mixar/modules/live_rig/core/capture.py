# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Webcam frame capture for live rig drive.

The first scaffold uses a no-hardware backend so operators and the pump can
run without OpenCV / platform camera entitlements. Swap in a real capture
implementation behind :func:`open_capture` when the camera stack lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class Frame:
    """One camera frame in a backend-agnostic shape.

    ``pixels`` is optional RGB bytes (H*W*3). Empty frames keep the rest of
    the pipeline exercisable without a physical camera.
    """

    width: int
    height: int
    pixels: bytes = b""
    timestamp: float = 0.0


class CaptureDevice(Protocol):
    def read(self) -> Optional[Frame]:
        ...

    def close(self) -> None:
        ...


class NullCapture:
    """Always yields a 1x1 placeholder frame (no device access)."""

    def read(self) -> Optional[Frame]:
        return Frame(width=1, height=1, pixels=b"\x00\x00\x00")

    def close(self) -> None:
        return None


_active: Optional[CaptureDevice] = None


def open_capture(camera_index: int = 0) -> CaptureDevice:
    """Open the active capture device (null backend for the scaffold)."""
    global _active
    if _active is not None:
        _active.close()
    _active = NullCapture()
    return _active


def get_capture() -> Optional[CaptureDevice]:
    return _active


def close_capture() -> None:
    global _active
    if _active is not None:
        _active.close()
        _active = None
