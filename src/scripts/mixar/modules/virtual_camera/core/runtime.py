# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Runtime pump: the ``bpy.app.timers`` loop wiring session → camera → stream.

Follows the repo handler pattern — server threads only fill the Session;
every bpy mutation happens here on the main thread. The encoder worker gets
raw pixel buffers and never imports bpy.
"""

from __future__ import annotations

import threading
import time

import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    APPLY_TIMER_INTERVAL,
    STATE_SYNC_INTERVAL,
    STREAM_JPEG_QUALITY,
    STREAM_QUALITY_SIZES,
)
from . import stream_encode
from .camera_driver import CameraDriver
from .server import get_server
from .stream_capture import ViewportCapture

logger = get_logger(__name__)

# Consecutive capture failures before streaming is disabled for the session
# (camera control must survive a dead GPU-capture path).
_CAPTURE_FAILURE_LIMIT = 3


class _EncoderWorker:
    """Single worker with a one-slot mailbox: late frames overwrite, so the
    stream degrades to a lower rate instead of building latency."""

    def __init__(self, send) -> None:
        self._send = send
        self._cond = threading.Condition()
        self._slot = None
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="mixar-vcam-encoder", daemon=True
        )
        self._thread.start()

    def submit(self, raw: bytes, width: int, height: int, quality: int) -> None:
        with self._cond:
            self._slot = (raw, width, height, quality)
            self._cond.notify()

    def stop(self) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()

    def _loop(self) -> None:
        while True:
            with self._cond:
                while self._running and self._slot is None:
                    self._cond.wait(timeout=1.0)
                if not self._running:
                    return
                raw, width, height, quality = self._slot
                self._slot = None
            try:
                payload = stream_encode.encode_frame(
                    raw, width, height,
                    jpeg_quality=STREAM_JPEG_QUALITY.get(quality, 68),
                )
            except (ValueError, MemoryError):
                continue
            self._send(payload)


class Runtime:
    def __init__(self) -> None:
        self.server = get_server()
        self.driver = CameraDriver()
        self.capture = ViewportCapture()
        self._encoder: _EncoderWorker | None = None
        self._timer_registered = False
        self._last_tick = 0.0
        self._last_capture = 0.0
        self._last_sync = 0.0
        self._last_state: dict | None = None
        self._was_connected = False
        self._capture_failures = 0
        self.capture_disabled = False
        self.last_error = ""

    # ---- lifecycle ----------------------------------------------------------

    def start(self) -> bool:
        if not self.server.start():
            return False
        self._capture_failures = 0
        self.capture_disabled = False
        self.last_error = ""
        if self._encoder is None:
            self._encoder = _EncoderWorker(self.server.send_stream_frame)
        if not self._timer_registered:
            self._last_tick = time.monotonic()
            bpy.app.timers.register(self._tick, first_interval=APPLY_TIMER_INTERVAL)
            self._timer_registered = True
        return True

    def stop(self) -> None:
        self.server.stop()
        if self._encoder is not None:
            self._encoder.stop()
            self._encoder = None
        self.driver.set_recording(False)
        # The timer notices state.running is False and unregisters itself.

    @property
    def running(self) -> bool:
        return self.server.state.running

    # ---- timer --------------------------------------------------------------

    def _tick(self):
        """Guarded timer entry: an unhandled exception would make Blender
        silently unregister the timer, freezing camera control while the
        panel still shows a connected phone (same rationale as the bootstrap
        UI loader's batch tick)."""
        try:
            return self._tick_inner()
        except Exception:
            logger.exception("virtual_camera: control tick failed")
            self.last_error = "Internal error in control tick — see console"
            return APPLY_TIMER_INTERVAL

    def _tick_inner(self):
        if not self.server.state.running:
            self._timer_registered = False
            self.capture.free()
            self._tag_redraw()
            return None

        now = time.monotonic()
        dt = min(max(now - self._last_tick, 1e-4), 0.25)
        self._last_tick = now

        session = self.server.session
        connected = self.server.state.phone_connected
        if connected != self._was_connected:
            self._was_connected = connected
            self._last_state = None  # force a full state push on (re)connect
            if connected:
                self.driver.ensure_camera()
            self._tag_redraw()

        if connected:
            self._apply_settings(session)
            self._run_commands(session)
            packet = session.control_snapshot(now)
            self.driver.apply(packet, session.snapshot_settings(), dt)
            self.driver.record_keyframes()
            self._pump_stream(session, now)
            self._sync_state(session, now)

        return APPLY_TIMER_INTERVAL

    # ---- pieces -------------------------------------------------------------

    def _apply_settings(self, session) -> None:
        dirty = session.take_dirty_settings()
        if not dirty:
            return
        settings = session.snapshot_settings()
        if "lens" in dirty:
            self.driver.set_lens(
                dirty["lens"], vertigo=bool(settings.get("vertigo"))
            )
        if dirty.get("vertigo") is False:
            self.driver.reset_vertigo()

    def _run_commands(self, session) -> None:
        for command in session.take_commands():
            name, args = command["name"], command["args"]
            if name == "recenter":
                packet = session.control_snapshot(time.monotonic())
                self.driver.recenter(packet.quat if packet else None)
            elif name == "record_toggle":
                turning_on = not self.driver.recording
                self.driver.set_recording(turning_on)
                if turning_on and not self.driver.is_playing():
                    self.driver.play_toggle()
            elif name == "play_toggle":
                self.driver.play_toggle()
            elif name == "stop":
                self.driver.set_recording(False)
                self.driver.stop_playback()
            elif name == "camera_select":
                cam_name = args.get("name")
                if isinstance(cam_name, str):
                    self.driver.select_camera(cam_name)
            elif name == "camera_new":
                self.driver.new_camera()
            elif name == "camera_revert":
                self.driver.revert()

    def _pump_stream(self, session, now: float) -> None:
        if self.capture_disabled:
            return
        settings = session.snapshot_settings()
        fps = float(settings.get("stream_fps") or 0)
        if fps <= 0 or self._encoder is None:
            return
        if now - self._last_capture < 1.0 / fps:
            return
        self._last_capture = now
        camera = self.driver.camera()
        quality = int(settings.get("stream_quality", 2))
        short_edge = STREAM_QUALITY_SIZES.get(quality, 720)
        try:
            result = self.capture.capture(camera, short_edge)
        except Exception:
            self._capture_failures += 1
            if self._capture_failures >= _CAPTURE_FAILURE_LIMIT:
                self.capture_disabled = True
                self.last_error = "Viewport streaming unavailable — camera control still active"
                logger.exception(
                    "virtual_camera: capture failed %d times, streaming disabled",
                    self._capture_failures,
                )
                self.server.send_json(
                    {"t": "toast", "msg": "Live view unavailable on this system"}
                )
            return
        self._capture_failures = 0
        if result is not None:
            raw, width, height = result
            self._encoder.submit(raw, width, height, quality)

    def _sync_state(self, session, now: float) -> None:
        if now - self._last_sync < STATE_SYNC_INTERVAL:
            return
        self._last_sync = now
        scene = bpy.context.scene
        camera = self.driver.camera()
        state = {
            "t": "state",
            "cameras": self.driver.camera_names(),
            "active": camera.name if camera else "",
            "frame": scene.frame_current if scene else 0,
            "playing": self.driver.is_playing(),
            "recording": self.driver.recording,
            "lens": round(camera.data.lens, 2) if camera else 0,
        }
        if self._last_state is None:
            state["settings"] = session.snapshot_settings()
        if state != self._last_state:
            self._last_state = {k: v for k, v in state.items() if k != "settings"}
            self.server.send_json(state)

    @staticmethod
    def _tag_redraw() -> None:
        wm = bpy.context.window_manager
        if wm is None:
            return
        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'UI':
                            region.tag_redraw()


_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = Runtime()
    return _runtime


def shutdown() -> None:
    """Full stop — called from unregister and load_pre."""
    global _runtime
    if _runtime is not None:
        _runtime.stop()
