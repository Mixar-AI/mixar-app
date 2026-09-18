# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The one voice session: record -> transcribe -> insert, and its UI mirror.

There is ONE microphone and one place a transcript is going, so there is one
session. Everything about the feature's state lives here and is mirrored onto
the WindowManager for the three surfaces that draw a mic button — the C++ chat
footer, the C++ node tile and the Python N-panel all read those properties and
none of them keeps state of its own.

WindowManager, never Scene: a half-finished recording is a property of this
running app, not something to serialize into a shared `.blend`.

Two rules the rest of the module exists to hold:

- **The target is captured at START.** Pressing the mic in the chat and then
  clicking a node must not paste the sentence into the node — see
  `core/targets.py`.
- **A second start while recording stops the FIRST one.** Whether the user
  presses the same button again or a different one, the audio already captured
  belongs to the field it was started in; the new press never re-aims it.
"""

from __future__ import annotations

import time
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    EMPTY_TRANSCRIPT_MESSAGE,
    MAX_RECORDING_SECONDS,
    MESSAGE_TTL_S,
    MIN_RECORDING_SECONDS,
    RECORDING_TICK_S,
    STATE_ERROR,
    STATE_IDLE,
    STATE_RECORDING,
    STATE_TRANSCRIBING,
)
from . import glyph_icons
from .targets import insert_transcript, is_valid_target
from .transcription import TranscriptionRequest

logger = get_logger(__name__)


def _window_manager():
    try:
        return bpy.context.window_manager
    except Exception:
        return None


def _redraw_voice_surfaces() -> None:
    """Repaint every surface that can draw a mic button.

    The level meter and the clock are only as smooth as this, and the Agent
    Bubble lives in its OWN window — so regions are tagged, not just areas,
    the same reason the queue-status contract gives.
    """
    try:
        for window in bpy.context.window_manager.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type in _VOICE_SURFACE_AREA_TYPES:
                    for region in area.regions:
                        region.tag_redraw()
    except Exception:
        pass


#: Areas that can host a mic button. `AGENT_BUBBLE` is listed for the same
#: reason the queue surfaces list it: the bubble and its minimised pill live in
#: their own windows and are missed by a scan of the main screen alone.
_VOICE_SURFACE_AREA_TYPES = {
    "MIXIE_CHAT",
    "AGENT_BUBBLE",
    "VIEW_3D",
    "MIXIE",
}


class VoiceSession:
    """Process-wide recorder + transcription state machine."""

    def __init__(self) -> None:
        self.state = STATE_IDLE
        self.target = ""
        self.message = ""
        self._scene_name = ""
        self._request: Optional[TranscriptionRequest] = None
        self._message_until = 0.0
        self._tick_registered = False

    # -- public API --------------------------------------------------------

    def toggle(self, context, target: str) -> tuple[bool, str]:
        """Start or stop recording for `target`. Returns `(ok, message)`.

        A press while TRANSCRIBING is ignored rather than queued: the user is
        waiting on words that are already on their way, and starting a second
        recording would leave two transcripts racing for one text field.
        """
        if self.state == STATE_TRANSCRIBING:
            return False, "Still transcribing the last recording"

        if self.state == STATE_RECORDING:
            # Stop — deliberately ignoring `target`. The audio belongs to the
            # field this recording was STARTED in.
            return self.stop(context)

        return self.start(context, target)

    def start(self, context, target: str) -> tuple[bool, str]:
        if not is_valid_target(target):
            logger.warning(f"[Voice] refusing to record for unknown target {target!r}")
            return False, "Voice input isn't available here"

        wm = context.window_manager if context else _window_manager()
        if wm is None:
            return False, "Voice input isn't available right now"
        if not getattr(wm, "mixar_audio_available", False):
            return False, "This build cannot record audio"

        if not wm.mixar_audio_record_start():
            # The C++ side reported the reason through `reports` (no device,
            # access denied); the operator surfaces that. Anything we invent
            # here would be less specific.
            self._enter_error("")
            return False, ""

        # Build RECORDING's frames here, not in the redraw that first shows
        # them: `icon_id` is reached from a panel draw, and the handler pattern
        # keeps heavy work off that path. This is the press the module's
        # contract names, and the mic is already opening.
        glyph_icons.prewarm(STATE_RECORDING)

        self.state = STATE_RECORDING
        self.target = target
        self.message = ""
        self._scene_name = getattr(getattr(context, "scene", None), "name", "") or ""
        self._ensure_tick()
        self._publish()
        return True, ""

    def stop(self, context) -> tuple[bool, str]:
        """Stop recording and start transcribing whatever was captured."""
        if self.state != STATE_RECORDING:
            return False, ""

        wm = context.window_manager if context else _window_manager()
        if wm is None:
            self.cancel()
            return False, "Voice input isn't available right now"

        duration = float(getattr(wm, "mixar_audio_duration", 0.0) or 0.0)
        if duration < MIN_RECORDING_SECONDS:
            # Too short to be speech — a mis-click, or a press-and-release the
            # user did not mean. Discard it without spending a credit.
            wm.mixar_audio_record_cancel()
            self._enter_idle_with_message(EMPTY_TRANSCRIPT_MESSAGE)
            return False, ""

        filepath = wm.mixar_audio_record_stop()
        if not filepath:
            self._enter_error("")
            return False, ""

        # Same reason, for the state with the most frames.
        glyph_icons.prewarm(STATE_TRANSCRIBING)

        self.state = STATE_TRANSCRIBING
        self._publish()
        self._request = TranscriptionRequest(
            filepath,
            on_done=self._on_transcript,
            on_failed=self._on_failed,
        )
        self._request.start()
        return True, ""

    def cancel(self) -> None:
        """Abandon whatever is in flight and return to idle."""
        wm = _window_manager()
        if wm is not None:
            try:
                wm.mixar_audio_record_cancel()
            except Exception:
                pass
        if self._request is not None:
            self._request.cancel()
            self._request = None
        self._enter_idle_with_message("")

    def shutdown(self) -> None:
        """Release the device at unregister — the module may be reloading."""
        self.cancel()
        self._tick_registered = False

    # -- transcription outcomes -------------------------------------------

    def _on_transcript(self, transcript: str) -> None:
        self._request = None
        text = (transcript or "").strip()
        if not text:
            # Silence is a SUCCESS at every layer below this one; the only
            # thing left is to say so plainly.
            self._enter_idle_with_message(EMPTY_TRANSCRIPT_MESSAGE)
            return

        scene = self._resolve_scene()
        if not insert_transcript(scene, self.target, text):
            self._enter_idle_with_message("That field is gone — transcript dropped")
            return
        self._enter_idle_with_message("")

    def _on_failed(self, message: str) -> None:
        self._request = None
        self._enter_error(message)

    # -- internals ---------------------------------------------------------

    def _resolve_scene(self):
        """The scene the recording was started in, if it still exists.

        Resolved by NAME rather than held as a reference: a scene pointer kept
        across an undo or a file load is a dangling one, and pasting into a
        freed datablock is a crash rather than a wrong paste.
        """
        scene = bpy.data.scenes.get(self._scene_name) if self._scene_name else None
        if scene is not None:
            return scene
        try:
            return bpy.context.scene
        except Exception:
            return None

    def _enter_idle_with_message(self, message: str) -> None:
        self.state = STATE_IDLE
        self.target = ""
        self.message = message
        if message:
            # The notice needs a tick to expire it; without a message the
            # running tick sees idle-and-silent and unregisters itself.
            self._message_until = time.monotonic() + MESSAGE_TTL_S
            self._ensure_tick()
        else:
            self._message_until = 0.0
        self._publish()

    def _enter_error(self, message: str) -> None:
        self.state = STATE_ERROR
        self.target = ""
        self.message = message
        self._message_until = time.monotonic() + MESSAGE_TTL_S
        self._ensure_tick()
        self._publish()

    def _ensure_tick(self) -> None:
        """One self-stopping timer drives the clock, the meter and the TTL."""
        if self._tick_registered:
            return
        self._tick_registered = True
        bpy.app.timers.register(self._tick, first_interval=RECORDING_TICK_S)

    def _tick(self) -> Optional[float]:
        if self.state == STATE_RECORDING:
            wm = _window_manager()
            duration = float(getattr(wm, "mixar_audio_duration", 0.0) or 0.0)
            if duration >= MAX_RECORDING_SECONDS:
                # The C++ buffer stopped growing at its own ceiling, so every
                # further second would be a clock ticking over audio nobody
                # captured. Stop and transcribe what there is.
                self.stop(bpy.context)
            self._publish()
            _redraw_voice_surfaces()
            return RECORDING_TICK_S

        if self.state == STATE_TRANSCRIBING:
            self._publish()
            _redraw_voice_surfaces()
            return RECORDING_TICK_S

        if self.message and time.monotonic() < self._message_until:
            return RECORDING_TICK_S

        if self.message:
            self.message = ""
            if self.state == STATE_ERROR:
                self.state = STATE_IDLE
            self._publish()
            _redraw_voice_surfaces()

        self._tick_registered = False
        return None

    def _publish(self) -> None:
        """Mirror the session onto the WindowManager for the draw surfaces."""
        wm = _window_manager()
        if wm is None:
            return
        try:
            wm.mixar_voice_state = self.state
            wm.mixar_voice_target = self.target
            wm.mixar_voice_message = self.message
        except Exception:
            # Properties are not registered yet (startup ordering) — the next
            # publish catches up, and nothing downstream depends on this one.
            pass


_session: Optional[VoiceSession] = None


def get_session() -> VoiceSession:
    global _session
    if _session is None:
        _session = VoiceSession()
    return _session
