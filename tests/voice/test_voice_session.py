# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The recorder's state machine: one mic, one target, captured at the start.

The rules here are the ones a second implementation would get wrong:

- A press while recording STOPS — it never re-aims the recording at whatever
  the new press named. The audio already captured belongs to the field it was
  started in.
- A press while transcribing is refused, not queued. Two transcripts racing
  for one text field is not something the user asked for.
- A clip too short to be speech is discarded without an upload, so a mis-click
  costs nothing.
- The transcript goes to the target the recording STARTED with, even if the
  user has since clicked into something else.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pytest  # noqa: E402

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.voice.constants import (  # noqa: E402
    STATE_IDLE,
    STATE_RECORDING,
    STATE_TRANSCRIBING,
    TARGET_CHAT,
)
from mixar.modules.voice.core import session as session_module  # noqa: E402


class FakeWindowManager:
    """Stands in for the C++ capture RNA."""

    def __init__(self, *, available=True, start_ok=True):
        self.mixar_audio_available = available
        self.mixar_audio_duration = 0.0
        self.mixar_audio_level = 0.0
        self.mixar_voice_state = STATE_IDLE
        self.mixar_voice_target = ""
        self.mixar_voice_message = ""
        self._start_ok = start_ok
        self.started = 0
        self.stopped = 0
        self.cancelled = 0
        self.stop_path = "/tmp/mixar_voice_test.wav"

    def mixar_audio_record_start(self):
        self.started += 1
        return self._start_ok

    def mixar_audio_record_stop(self):
        self.stopped += 1
        return self.stop_path

    def mixar_audio_record_cancel(self):
        self.cancelled += 1
        self.mixar_audio_duration = 0.0


class FakeRequest:
    """Captures what would have been uploaded, and lets the test settle it."""

    instances = []

    def __init__(self, filepath, *, on_done, on_failed):
        self.filepath = filepath
        self.on_done = on_done
        self.on_failed = on_failed
        self.started = False
        FakeRequest.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


@pytest.fixture(autouse=True)
def _isolated_session(monkeypatch):
    FakeRequest.instances.clear()
    monkeypatch.setattr(session_module, "TranscriptionRequest", FakeRequest)
    # The session drives a timer and repaints; neither belongs in a unit test.
    monkeypatch.setattr(session_module, "_redraw_voice_surfaces", lambda: None)
    monkeypatch.setattr(
        session_module.VoiceSession, "_ensure_tick", lambda self: None
    )
    session_module._session = None
    yield
    session_module._session = None


def _context(wm, scene=None):
    return SimpleNamespace(window_manager=wm, scene=scene or SimpleNamespace(name="Scene"))


def _session(wm, monkeypatch):
    monkeypatch.setattr(session_module, "_window_manager", lambda: wm)
    return session_module.get_session()


# -- starting --------------------------------------------------------------


def test_a_press_starts_recording_and_remembers_the_target(monkeypatch):
    wm = FakeWindowManager()
    session = _session(wm, monkeypatch)

    ok, _message = session.toggle(_context(wm), TARGET_CHAT)

    assert ok
    assert wm.started == 1
    assert session.state == STATE_RECORDING
    assert session.target == TARGET_CHAT


def test_an_unknown_target_never_opens_the_microphone(monkeypatch):
    wm = FakeWindowManager()
    session = _session(wm, monkeypatch)

    ok, message = session.toggle(_context(wm), "somewhere-else")

    assert not ok
    assert wm.started == 0
    assert session.state == STATE_IDLE
    assert message


def test_a_build_without_capture_refuses_rather_than_failing_later(monkeypatch):
    wm = FakeWindowManager(available=False)
    session = _session(wm, monkeypatch)

    ok, message = session.toggle(_context(wm), TARGET_CHAT)

    assert not ok
    assert wm.started == 0
    assert message


def test_a_device_that_will_not_open_leaves_an_error_the_ui_can_show(monkeypatch):
    wm = FakeWindowManager(start_ok=False)
    session = _session(wm, monkeypatch)

    ok, _ = session.toggle(_context(wm), TARGET_CHAT)

    assert not ok
    assert session.state == "ERROR"


# -- stopping --------------------------------------------------------------


def test_a_second_press_stops_and_starts_transcribing(monkeypatch):
    wm = FakeWindowManager()
    session = _session(wm, monkeypatch)
    session.toggle(_context(wm), TARGET_CHAT)
    wm.mixar_audio_duration = 2.5

    session.toggle(_context(wm), TARGET_CHAT)

    assert wm.stopped == 1
    assert session.state == STATE_TRANSCRIBING
    assert len(FakeRequest.instances) == 1
    assert FakeRequest.instances[0].started


def test_pressing_a_DIFFERENT_mic_stops_the_first_without_re_aiming_it(monkeypatch):
    """The audio belongs to the field it was started in.

    Re-aiming here would paste a sentence spoken into the chat onto a node
    prompt just because the second click landed there.
    """
    wm = FakeWindowManager()
    session = _session(wm, monkeypatch)
    session.toggle(_context(wm), TARGET_CHAT)
    wm.mixar_audio_duration = 3.0

    session.toggle(_context(wm), "node:some-node")

    assert session.state == STATE_TRANSCRIBING
    assert session._request is FakeRequest.instances[0]
    assert session.target == TARGET_CHAT


def test_a_press_while_transcribing_is_refused_not_queued(monkeypatch):
    wm = FakeWindowManager()
    session = _session(wm, monkeypatch)
    session.toggle(_context(wm), TARGET_CHAT)
    wm.mixar_audio_duration = 2.0
    session.toggle(_context(wm), TARGET_CHAT)
    assert session.state == STATE_TRANSCRIBING

    ok, message = session.toggle(_context(wm), TARGET_CHAT)

    assert not ok
    assert message
    assert wm.started == 1
    assert len(FakeRequest.instances) == 1


def test_a_clip_too_short_to_be_speech_is_discarded_without_an_upload(monkeypatch):
    wm = FakeWindowManager()
    session = _session(wm, monkeypatch)
    session.toggle(_context(wm), TARGET_CHAT)
    wm.mixar_audio_duration = 0.05

    session.toggle(_context(wm), TARGET_CHAT)

    assert wm.cancelled == 1
    assert wm.stopped == 0
    assert FakeRequest.instances == []
    assert session.state == STATE_IDLE
    assert session.message


def test_the_ceiling_stops_the_recording_on_its_own(monkeypatch):
    """Past the C++ buffer's cap the clock would tick over audio nobody has."""
    wm = FakeWindowManager()
    session = _session(wm, monkeypatch)
    session.toggle(_context(wm), TARGET_CHAT)
    wm.mixar_audio_duration = session_module.MAX_RECORDING_SECONDS + 1.0

    monkeypatch.setattr(session_module.bpy, "context", _context(wm), raising=False)
    session._tick()

    assert wm.stopped == 1
    assert session.state == STATE_TRANSCRIBING


# -- outcomes --------------------------------------------------------------


def test_the_transcript_lands_in_the_target_the_recording_started_with(monkeypatch):
    wm = FakeWindowManager()
    session = _session(wm, monkeypatch)
    scene = SimpleNamespace(name="Scene")
    session.toggle(_context(wm, scene), TARGET_CHAT)
    wm.mixar_audio_duration = 2.0
    session.toggle(_context(wm, scene), TARGET_CHAT)

    written = {}
    monkeypatch.setattr(
        session_module,
        "insert_transcript",
        lambda scene, target, text: written.update(target=target, text=text) or True,
    )
    monkeypatch.setattr(session_module.VoiceSession, "_resolve_scene", lambda self: scene)

    FakeRequest.instances[0].on_done("a red chair")

    assert written == {"target": TARGET_CHAT, "text": "a red chair"}
    assert session.state == STATE_IDLE


def test_silence_says_so_instead_of_raising_an_error(monkeypatch):
    wm = FakeWindowManager()
    session = _session(wm, monkeypatch)
    session.toggle(_context(wm), TARGET_CHAT)
    wm.mixar_audio_duration = 2.0
    session.toggle(_context(wm), TARGET_CHAT)

    FakeRequest.instances[0].on_done("   ")

    assert session.state == STATE_IDLE
    assert session.message == session_module.EMPTY_TRANSCRIPT_MESSAGE


def test_a_failed_transcription_surfaces_its_message(monkeypatch):
    wm = FakeWindowManager()
    session = _session(wm, monkeypatch)
    session.toggle(_context(wm), TARGET_CHAT)
    wm.mixar_audio_duration = 2.0
    session.toggle(_context(wm), TARGET_CHAT)

    FakeRequest.instances[0].on_failed("Could not reach Mixar (NET-001)")

    assert session.state == "ERROR"
    assert "NET-001" in session.message


def test_cancel_releases_the_device_and_abandons_the_request(monkeypatch):
    wm = FakeWindowManager()
    session = _session(wm, monkeypatch)
    session.toggle(_context(wm), TARGET_CHAT)
    wm.mixar_audio_duration = 2.0
    session.toggle(_context(wm), TARGET_CHAT)

    session.cancel()

    assert wm.cancelled >= 1
    assert getattr(FakeRequest.instances[0], "cancelled", False)
    assert session.state == STATE_IDLE
    assert session.target == ""
