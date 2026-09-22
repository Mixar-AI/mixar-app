# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Connection-independent session state shared between the server thread and
the main-thread camera driver.

The WebSocket thread feeds inbound messages in; the ``bpy.app.timers`` pump
drains commands and reads the latest control packet. Everything here is pure
Python guarded by a lock — no bpy access — so the threading contract stays
simple and the logic stays unit-testable.
"""

from __future__ import annotations

import math
import threading
from typing import Any

from ..constants import (
    CONTROL_STALE_SECONDS,
    DEFAULT_LENS_MM,
    DEFAULT_MOVE_SCALE,
    DEFAULT_SEND_RATE_HZ,
    DEFAULT_SMOOTHING,
    DEFAULT_STREAM_FPS,
    DEFAULT_STREAM_QUALITY,
    LENS_MAX_MM,
    LENS_MIN_MM,
    STREAM_FPS_MAX,
)

_ALLOWED_COMMANDS = frozenset({
    "recenter", "record_toggle", "play_toggle", "stop",
    "camera_select", "camera_new", "camera_revert",
})

_SETTING_VALIDATORS: dict[str, Any] = {
    "lens": lambda v: _clampf(v, LENS_MIN_MM, LENS_MAX_MM),
    "move_scale": lambda v: _clampf(v, 0.01, 100.0),
    "smoothing": lambda v: _clampf(v, 0.0, 0.95),
    "send_rate": lambda v: _clampf(v, 10, 60),
    "stream_fps": lambda v: _clampf(v, 0, STREAM_FPS_MAX),
    "stream_quality": lambda v: int(_clampf(v, 1, 3)),
    "vertigo": lambda v: bool(v),
}


def _clampf(value: Any, lo: float, hi: float) -> float:
    """Clamp a number off the wire.

    `NaN` has to be rejected rather than clamped: every comparison against
    it is False, so `min`/`max` hand it straight back and it would reach the
    camera as a lens or a move scale. `json.loads` accepts the non-standard
    `NaN`/`Infinity` literals, so a phone can send one.
    """
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("not a finite number")
    return min(max(number, lo), hi)


def _finite(c: Any) -> bool:
    return isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c)


def _valid_quat(q: Any) -> bool:
    """A rotation, not an assertion that four numbers arrived.

    `Infinity` passes a bare magnitude test — `inf > 1e-6` is True — and
    normalising it yields `NaN` in the camera's world matrix, which is a
    transform nothing recovers from without reloading the file.
    """
    return (
        isinstance(q, (list, tuple)) and len(q) == 4
        and all(_finite(c) for c in q)
        and sum(c * c for c in q) > 1e-6
    )


def _valid_stick(j: Any) -> bool:
    return (
        isinstance(j, (list, tuple)) and len(j) == 2
        and all(_finite(c) and abs(c) <= 1.5 for c in j)
    )


class ControlPacket:
    __slots__ = ("quat", "j1", "j2", "received_at")

    def __init__(self, quat, j1, j2, received_at: float) -> None:
        self.quat = quat
        self.j1 = j1
        self.j2 = j2
        self.received_at = received_at


class Session:
    """One paired phone. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._control: ControlPacket | None = None
        self._commands: list[dict] = []
        self._dirty_settings: dict[str, Any] = {}
        self.settings: dict[str, Any] = {
            "lens": DEFAULT_LENS_MM,
            "move_scale": DEFAULT_MOVE_SCALE,
            "smoothing": DEFAULT_SMOOTHING,
            "send_rate": DEFAULT_SEND_RATE_HZ,
            "stream_fps": DEFAULT_STREAM_FPS,
            "stream_quality": DEFAULT_STREAM_QUALITY,
            "vertigo": False,
        }
        self.connected = False
        self.device_info: dict = {}

    # ---- server-thread side -------------------------------------------------

    def handle_message(self, msg: Any, now: float) -> None:
        """Digest one inbound JSON message. Unknown/malformed input is ignored
        (never raises: a hostile or outdated app must not kill the server)."""
        if not isinstance(msg, dict):
            return
        kind = msg.get("t")
        if kind == "ctl":
            quat = msg.get("q")
            j1 = msg.get("j1")
            j2 = msg.get("j2")
            packet = ControlPacket(
                tuple(quat) if _valid_quat(quat) else None,
                tuple(j1) if _valid_stick(j1) else (0.0, 0.0),
                tuple(j2) if _valid_stick(j2) else (0.0, 0.0),
                now,
            )
            with self._lock:
                self._control = packet
        elif kind == "set":
            key = msg.get("key")
            validator = _SETTING_VALIDATORS.get(key)
            if validator is None or "value" not in msg:
                return
            try:
                value = validator(msg["value"])
            except (TypeError, ValueError):
                return
            with self._lock:
                self.settings[key] = value
                self._dirty_settings[key] = value
        elif kind == "cmd":
            name = msg.get("name")
            if name not in _ALLOWED_COMMANDS:
                return
            args = msg.get("args")
            with self._lock:
                self._commands.append(
                    {"name": name, "args": args if isinstance(args, dict) else {}}
                )
        elif kind == "hello":
            info = msg.get("device")
            with self._lock:
                self.connected = True
                self.device_info = info if isinstance(info, dict) else {}

    def mark_disconnected(self) -> None:
        with self._lock:
            self.connected = False
            self._control = None
            self._commands.clear()

    # ---- main-thread side ---------------------------------------------------

    def control_snapshot(self, now: float) -> ControlPacket | None:
        """Latest control packet, or None if the feed has gone stale."""
        with self._lock:
            packet = self._control
        if packet is None or now - packet.received_at > CONTROL_STALE_SECONDS:
            return None
        return packet

    def take_commands(self) -> list[dict]:
        with self._lock:
            commands, self._commands = self._commands, []
        return commands

    def take_dirty_settings(self) -> dict[str, Any]:
        with self._lock:
            dirty, self._dirty_settings = self._dirty_settings, {}
        return dirty

    def snapshot_settings(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.settings)

    def update_setting(self, key: str, value: Any) -> None:
        """Server-side change (e.g. Blender UI) — pushed to the app via state."""
        with self._lock:
            self.settings[key] = value
