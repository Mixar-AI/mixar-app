# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Runtime pump: the ``bpy.app.timers`` loop wiring session → camera → stream.

Follows the repo handler pattern — server threads only fill the Session;
every bpy mutation happens here on the main thread. The encoder worker gets
raw pixel buffers and never imports bpy.

The timer is NOT a guaranteed-GPU moment, so it never touches the GPU: it
parks a frame request and tags a viewport, and a VIEW_3D ``POST_PIXEL`` draw
handler does the offscreen render and the readback. See ``stream_capture``.
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
from . import stream_encode, wm_mirror
from .camera_driver import CameraDriver
from .server import get_server
from .stream_capture import ViewportCapture, find_view3d

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
        # GPU work is serviced by a VIEW_3D draw handler, never by the timer
        # (see stream_capture's module docstring): the timer only parks a
        # request here and tags a viewport for redraw.
        self._draw_handler = None
        self._frame_request: tuple[int, int] | None = None
        self._release_capture = False

    # ---- lifecycle ----------------------------------------------------------

    def start(self) -> bool:
        if not self.server.start():
            return False
        self._capture_failures = 0
        self.capture_disabled = False
        self.last_error = ""
        self._release_capture = False
        self._frame_request = None
        self._ensure_draw_handler()
        self._publish_state()
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
        self._request_capture_release()
        wm_mirror.clear()
        self._tag_redraw()
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
            self._request_capture_release()
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
            self._publish_state()
            self._tag_redraw()

        if connected:
            self._apply_settings(session)
            self._run_commands(session)
            packet = session.control_snapshot(now)
            self.driver.apply(packet, session.snapshot_settings(), dt)
            self.driver.record_keyframes()
            self._pump_stream(session, now)
            self._sync_state(session, now)
            self._publish_state()

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
        """Park a frame request for the draw handler and nudge a viewport.

        No GPU call happens here — a timer tick is not a guaranteed-GPU
        moment and touching the GPU from one access-violates on Windows.
        """
        if self.capture_disabled:
            return
        settings = session.snapshot_settings()
        fps = float(settings.get("stream_fps") or 0)
        if fps <= 0 or self._encoder is None:
            return
        if now - self._last_capture < 1.0 / fps:
            return
        self._last_capture = now
        self._frame_request = (
            STREAM_QUALITY_SIZES.get(int(settings.get("stream_quality", 2)), 720),
            int(settings.get("stream_quality", 2)),
        )
        self._tag_viewport_redraw()

    # ---- draw handler (the only place GPU resources are touched) ------------

    def _ensure_draw_handler(self) -> None:
        if self._draw_handler is None:
            self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
                self._service_capture, (), 'WINDOW', 'POST_PIXEL'
            )

    def remove_draw_handler(self) -> None:
        """Teardown only — never called from inside the callback (removing a
        draw handler mid-iteration of the region's handler list is a
        use-after-free)."""
        if self._draw_handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, 'WINDOW')
            self._draw_handler = None

    def _request_capture_release(self) -> None:
        self._frame_request = None
        self._release_capture = True
        self._tag_viewport_redraw()

    def _service_capture(self) -> None:
        """VIEW_3D POST_PIXEL callback: a real draw, so the GPU context is
        current. Must never raise — an exception here breaks the viewport."""
        try:
            self._service_capture_inner()
        except Exception:
            logger.exception("virtual_camera: capture service failed")

    def _service_capture_inner(self) -> None:
        if self._release_capture:
            self._release_capture = False
            self.capture.free()
            return
        request = self._frame_request
        if request is None:
            return
        self._frame_request = None
        if self.capture_disabled or self._encoder is None:
            return
        short_edge, quality = request
        camera = self.driver.camera()
        if camera is None:
            return
        try:
            result = self.capture.capture(
                camera, short_edge, bpy.context.space_data, bpy.context.region
            )
        except Exception:
            self._note_capture_failure()
            return
        self._capture_failures = 0
        if result is not None:
            raw, width, height = result
            self._encoder.submit(raw, width, height, quality)

    def _note_capture_failure(self) -> None:
        self._capture_failures += 1
        if self._capture_failures < _CAPTURE_FAILURE_LIMIT:
            return
        self.capture_disabled = True
        self.last_error = "Viewport streaming unavailable — camera control still active"
        logger.exception(
            "virtual_camera: capture failed %d times, streaming disabled",
            self._capture_failures,
        )
        self.server.send_json(
            {"t": "toast", "msg": "Live view unavailable on this system"}
        )

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

    def _publish_state(self) -> None:
        """Mirror the session onto WindowManager for the Cinema surface.

        Main thread only, never from the draw handler — this writes RNA.
        """
        if wm_mirror.sync(self):
            self._tag_redraw()

    @staticmethod
    def _tag_viewport_redraw() -> None:
        """Drive the stream cadence: the draw handler only runs when a VIEW_3D
        WINDOW region actually redraws."""
        view3d = find_view3d()
        if view3d is not None:
            view3d[1].tag_redraw()

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


def shutdown(*, remove_handler: bool = False) -> None:
    """Full stop — called from unregister and load_pre.

    ``remove_handler`` is for unregister only: on a .blend load the handler
    must stay installed so the next draw can free the offscreen from a real
    GPU context.
    """
    global _runtime
    if _runtime is not None:
        _runtime.stop()
        if remove_handler:
            # `stop()` only PARKS the offscreen release for the draw handler
            # to service, and removing the handler leaves nothing to service
            # it — so on unregister the offscreen is not freed by us.
            # Deliberate: freeing it here would be the first GPU call this
            # module makes outside a draw callback (the invariant
            # `tests/virtual_camera/test_stream_capture_gpu_context.py`
            # pins), and a GPU free with no current context is a crash where
            # this is one buffer reclaimed by Blender's own teardown.
            _runtime.remove_draw_handler()
