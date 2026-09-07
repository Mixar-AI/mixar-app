# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Voice input — dictate into the chat composer.

One toggle (``mixie_chat.voice_toggle``) starts and stops a dictation
session. While it runs, the platform recogniser (on device where the system
supports it) streams partial transcriptions and Python keeps the composer's
tail in step with them: the text that was in the composer when the session
started stays, and everything after it is the CURRENT transcription — each
partial replaces the previous one, so corrections the recogniser makes
mid-sentence show up rather than piling on. The final transcription is
written the same way; nothing is sent, the user still presses Generate (or
says nothing and Generate stops the session first — see chat_ops).

The composer arithmetic is ``bpy``-free (``VoiceComposer``) and pinned by the
standalone suite. Everything platform-specific is behind three C++
operators (``mixie_chat_voice.cc``): ``voice_start`` (whose poll is the
platform capability — no platform table here), ``voice_stop`` and
``voice_poll``, which pops one recogniser event into the
``mixie_chat_voice_event_*`` WindowManager properties. A timer pumps those
while a session is up.
"""

from __future__ import annotations

import time
from typing import Optional

from mixar.config.logging_config import get_logger

from ..constants import (
    CHAT_INPUT_MAXLEN,
    VOICE_EVENT_DENIED,
    VOICE_EVENT_ERROR,
    VOICE_EVENT_FINAL,
    VOICE_EVENT_LISTENING,
    VOICE_EVENT_PARTIAL,
    VOICE_EVENT_POLL_S,
    VOICE_EVENT_STOPPED,
    VOICE_MAX_SESSION_S,
    VOICE_STOP_GRACE_S,
    VOICE_TOAST_ID,
)

logger = get_logger(__name__)


class VoiceComposer:
    """The composer's text during one dictation session.

    ``base`` is what the user had typed when the session began; a
    transcription is appended after it with exactly one separating space
    (none when the base is empty or already ends in whitespace), replacing
    the previous transcription rather than adding to it.
    """

    def __init__(self, base: str, maxlen: int = CHAT_INPUT_MAXLEN):
        self.base = base if isinstance(base, str) else ""
        self.maxlen = maxlen
        self.transcript = ""

    def compose(self, transcript: str) -> str:
        """The full composer text once *transcript* is applied."""
        transcript = (transcript or "").replace("\x1F", "").strip()
        self.transcript = transcript
        if not transcript:
            return self.base[: self.maxlen]
        sep = "" if (not self.base or self.base[-1].isspace()) else " "
        return (self.base + sep + transcript)[: self.maxlen]


class VoiceSession:
    """State machine over recogniser events. ``bpy``-free."""

    def __init__(self, composer: VoiceComposer, now_fn=time.monotonic):
        self.composer = composer
        self._now = now_fn
        self.started_at = now_fn()
        self.listening = False
        self.stopping_since: Optional[float] = None
        self.done = False
        self.status = "Starting…"
        self.notice: Optional[tuple] = None  # (level, message)
        self.text: Optional[str] = None      # composer text to write, if any
        # Events of an abandoned earlier session can precede this one's
        # LISTENING; nothing before it is ours (except a start refusal).
        self.saw_listening = False
        self.saw_failure = False

    def handle(self, kind: int, payload: str) -> None:
        """Apply one event. Sets ``text`` when the composer must be rewritten."""
        self.text = None
        self.notice = None
        if kind == VOICE_EVENT_LISTENING:
            self.listening = True
            self.saw_listening = True
            self.status = "Listening…"
        elif kind in (VOICE_EVENT_PARTIAL, VOICE_EVENT_FINAL):
            if not self.saw_listening:
                return  # a previous session's straggler
            self.text = self.composer.compose(payload)
            if kind == VOICE_EVENT_FINAL:
                self.status = "Done"
        elif kind == VOICE_EVENT_DENIED:
            self.saw_failure = True
            what = payload or "microphone"
            self.status = f"{what.capitalize()} access denied"
            self.notice = ("warning",
                           f"Voice input needs {what} access — allow it for Mixar in "
                           "System Settings › Privacy & Security")
        elif kind == VOICE_EVENT_ERROR:
            self.saw_failure = True
            self.status = "Voice input failed"
            self.notice = ("error", f"Voice input failed: {payload or 'unknown error'}")
        elif kind == VOICE_EVENT_STOPPED:
            if not (self.saw_listening or self.saw_failure):
                return  # a previous session's straggler
            self.listening = False
            self.done = True
            if self.status == "Listening…":
                self.status = ""

    def request_stop(self) -> None:
        if self.stopping_since is None:
            self.stopping_since = self._now()

    def timed_out(self) -> bool:
        """The recogniser owes us a STOPPED it is not delivering, or the
        session has run past the cap: finish with what we have."""
        now = self._now()
        if self.stopping_since is not None and now - self.stopping_since > VOICE_STOP_GRACE_S:
            return True
        return now - self.started_at > VOICE_MAX_SESSION_S


# =============================================================================
# Blender glue
# =============================================================================

_session: Optional[VoiceSession] = None
_scene = None


def available() -> bool:
    """True when this build and platform can dictate."""
    try:
        import bpy

        op = getattr(getattr(bpy.ops, "mixie_chat", None), "voice_start", None)
        return op is not None and bool(op.poll())
    except Exception:  # noqa: BLE001
        return False


def is_listening(wm=None) -> bool:
    try:
        import bpy

        wm = wm or bpy.context.window_manager
        return bool(getattr(wm, "mixie_chat_voice_listening", False))
    except Exception:  # noqa: BLE001
        return False


def toggle(context) -> str:
    """Start a session, or stop the one running. Returns what happened."""
    if _session is not None and not _session.done:
        stop()
        return "stopped"
    return start(context)


def start(context) -> str:
    global _session, _scene
    import bpy

    scene = getattr(context, "scene", None) or bpy.context.scene
    if scene is None:
        return "no_scene"
    if not available():
        return "unavailable"
    _release_composer()
    _drain_events()
    _session = VoiceSession(VoiceComposer(getattr(scene, "mixie_chat_input", "") or ""))
    _scene = scene
    _set_status("Starting…")
    try:
        result = bpy.ops.mixie_chat.voice_start()
    except Exception as exc:  # noqa: BLE001
        logger.error("[Voice] could not start: %s", exc)
        result = {"CANCELLED"}
    if "FINISHED" not in result:
        # The recogniser refused outright; its reason (if any) is already
        # queued as an event, so pump once to surface it.
        _pump_events()
        if _session is not None and not _session.done:
            _finish()
        return "unavailable"
    _ensure_timer()
    return "started"


def stop() -> None:
    """End the running session; the final transcription follows as events."""
    import bpy

    if _session is None or _session.done:
        return
    _session.request_stop()
    try:
        bpy.ops.mixie_chat.voice_stop()
    except Exception:  # noqa: BLE001
        logger.debug("[Voice] stop failed", exc_info=True)
    _ensure_timer()


def stop_if_listening() -> None:
    """For the send path: a message sent mid-dictation ends the session with
    what has been recognised so far, IMMEDIATELY — its final transcription,
    arriving after the composer was cleared, must not be written back into
    the next message. The recogniser's trailing events are drained by the
    next start and ignored by the stale-event guard."""
    if _session is not None and not _session.done:
        stop()
        _finish()


def reset_state() -> None:
    global _session, _scene
    _session = None
    _scene = None
    _set_listening(False)
    _set_status("")


# -----------------------------------------------------------------------------
# Event pump
# -----------------------------------------------------------------------------

def _ensure_timer() -> None:
    import bpy

    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=VOICE_EVENT_POLL_S)


def _tick():
    session = _session
    if session is None or session.done:
        return None
    try:
        _pump_events()
        if _session is not None and not _session.done and _session.timed_out():
            logger.info("[Voice] session timed out; finishing with the current text")
            _finish()
    except Exception:  # noqa: BLE001 — a timer callback must not raise
        logger.error("[Voice] event pump failed", exc_info=True)
    return None if (_session is None or _session.done) else VOICE_EVENT_POLL_S


def _drain_events() -> None:
    """Discard events left by an earlier session (see stop_if_listening)."""
    import bpy

    op = getattr(getattr(bpy.ops, "mixie_chat", None), "voice_poll", None)
    if op is None or not op.poll():
        return
    for _ in range(64):
        if "FINISHED" not in op():
            break


def _pump_events() -> None:
    import bpy

    session = _session
    if session is None:
        return
    op = getattr(getattr(bpy.ops, "mixie_chat", None), "voice_poll", None)
    if op is None or not op.poll():
        return
    wm = bpy.context.window_manager
    for _ in range(64):  # never spin forever on a flooding recogniser
        if "FINISHED" not in op():
            break
        kind = int(getattr(wm, "mixie_chat_voice_event_kind", 0))
        text = str(getattr(wm, "mixie_chat_voice_event_text", "") or "")
        session.handle(kind, text)
        if session.text is not None:
            _write_composer(session.text)
        if session.notice is not None:
            _toast(*session.notice)
        _set_listening(session.listening)
        _set_status(session.status)
        if session.done:
            _finish()
            break


def _finish() -> None:
    global _session
    if _session is not None:
        _session.done = True
        _session.listening = False
    _set_listening(False)
    _set_status("")
    _redraw()


# -----------------------------------------------------------------------------
# Seams
# -----------------------------------------------------------------------------

def _write_composer(text: str) -> None:
    scene = _scene
    if scene is None:
        return
    try:
        _release_composer()
        scene.mixie_chat_input = text[:CHAT_INPUT_MAXLEN]
    except Exception:  # noqa: BLE001
        logger.debug("[Voice] could not write the composer", exc_info=True)
    _redraw()


def _release_composer() -> None:
    from . import scribble

    scribble.release_composer()


def _redraw() -> None:
    from . import scribble

    scribble.redraw_chat()


def _set_listening(listening: bool) -> None:
    try:
        import bpy

        wm = bpy.context.window_manager
        if hasattr(wm, "mixie_chat_voice_listening"):
            if bool(wm.mixie_chat_voice_listening) != bool(listening):
                wm.mixie_chat_voice_listening = bool(listening)
                _redraw()
    except Exception:  # noqa: BLE001
        pass


def _set_status(status: str) -> None:
    try:
        import bpy

        wm = bpy.context.window_manager
        if hasattr(wm, "mixie_chat_voice_status") and wm.mixie_chat_voice_status != status:
            wm.mixie_chat_voice_status = status
    except Exception:  # noqa: BLE001
        pass


def _toast(level: str, message: str) -> None:
    try:
        from mixar.modules.common.notifications import get_notification_store

        get_notification_store().push(level, message, "", id=VOICE_TOAST_ID)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Voice] %s (toast unavailable: %s)", message, exc)
