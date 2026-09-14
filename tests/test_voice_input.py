# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Voice input: dictate into the composer.

One toggle starts a dictation session; the platform recogniser (on device
where the system supports it) streams partial transcriptions and the
composer's tail follows them — the text the user had typed stays, and every
partial REPLACES the previous transcription rather than piling on. Nothing is
sent; Generate still sends, and a send mid-dictation ends the session first.

The composer arithmetic and the event state machine are pure Python. The
platform halves — Info.plist usage strings (without which macOS terminates
the app on first microphone access), the runtime-loaded ObjC recogniser, the
operators, the island chip and the header buttons — are pinned at source
level.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

CHAT = ROOT / "src/source/blender/editors/space_mixie_chat"
BUBBLE = ROOT / "src/source/blender/editors/space_agent_bubble"
VOICE_CC = (CHAT / "mixie_chat_voice.cc").read_text(encoding="utf-8")
SPACE_CC = (CHAT / "space_mixie_chat.cc").read_text(encoding="utf-8")
CHAT_CMAKE = (CHAT / "CMakeLists.txt").read_text(encoding="utf-8")
SPEECH_MM = (ROOT / "src/intern/ghost/intern/GHOST_MixarSpeechCocoa.mm").read_text(encoding="utf-8")
GHOST_CMAKE = (ROOT / "src/intern/ghost/CMakeLists.txt").read_text(encoding="utf-8")
PLIST = (ROOT / "src/release/darwin/Mixar.app/Contents/Info.plist").read_text(encoding="utf-8")
CONSTANTS_PY = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/constants.py").read_text(encoding="utf-8")
VOICE_OPS_PY = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/voice_ops.py").read_text(
    encoding="utf-8"
)
CHAT_OPS_PY = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/chat_ops.py").read_text(
    encoding="utf-8"
)
CHAT_HEADER_PY = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/header.py").read_text(encoding="utf-8")
BUBBLE_HEADER_PY = (ROOT / "src/scripts/mixar/modules/agent_bubble/ui/header.py").read_text(encoding="utf-8")
ICONS_HH = (BUBBLE / "agent_ui_icons.hh").read_text(encoding="utf-8")
LAYOUT_HH = (BUBBLE / "agent_ui_layout.hh").read_text(encoding="utf-8")
LAYOUT_CC = (BUBBLE / "agent_ui_layout.cc").read_text(encoding="utf-8")
DRAW_CC = (BUBBLE / "agent_ui_controls_paint.cc").read_text(encoding="utf-8")
DRAW_HH = (BUBBLE / "agent_ui_draw.hh").read_text(encoding="utf-8")
STATE_CC = (BUBBLE / "agent_ui_state.cc").read_text(encoding="utf-8")
BUBBLE_CC = (BUBBLE / "space_agent_bubble.cc").read_text(encoding="utf-8")
VOICE_PY = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/voice.py").read_text(encoding="utf-8")


# `space_mixie_chat.core/__init__.py` imports the connection manager (and so
# auth -> keyring), none of which the standalone suite has. Seed a light
# package object so the two pure modules under test import as submodules
# without executing that init — their own relative imports only reach
# `..constants` (bpy-free) and lazily `.scribble`.
import types  # noqa: E402

_CORE_PKG = "mixar.modules.space_mixie_chat.core"
if _CORE_PKG not in sys.modules:
    _pkg = types.ModuleType(_CORE_PKG)
    _pkg.__path__ = [str(SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core")]
    _pkg.__package__ = _CORE_PKG
    sys.modules[_CORE_PKG] = _pkg

from mixar.modules.space_mixie_chat import constants as C  # noqa: E402
from mixar.modules.space_mixie_chat.core.voice import VoiceComposer, VoiceSession  # noqa: E402


class _Clock:
    def __init__(self):
        self.t = 50.0

    def __call__(self):
        return self.t


# ---------------------------------------------------------------------------
# Composer arithmetic
# ---------------------------------------------------------------------------


def test_transcript_is_appended_after_the_typed_text_with_one_space():
    c = VoiceComposer("make a red cube")
    assert c.compose("and a blue sphere") == "make a red cube and a blue sphere"
    assert VoiceComposer("").compose("hello") == "hello"
    assert VoiceComposer("trailing ").compose("hello") == "trailing hello"


def test_partials_replace_each_other_instead_of_piling_on():
    c = VoiceComposer("base")
    assert c.compose("hel") == "base hel"
    assert c.compose("hello wor") == "base hello wor"
    assert c.compose("hello world") == "base hello world"


def test_an_empty_transcript_leaves_the_typed_text_alone():
    c = VoiceComposer("keep me")
    assert c.compose("") == "keep me"
    assert c.compose("   ") == "keep me"


def test_the_enter_marker_can_never_arrive_by_voice():
    """\\x1F on mixie_chat_input is the in-band submit request."""
    assert "\x1F" not in VoiceComposer("").compose("send\x1F it")


def test_the_composer_cap_is_respected():
    c = VoiceComposer("x" * 10, maxlen=15)
    assert len(c.compose("y" * 100)) == 15


# ---------------------------------------------------------------------------
# Event state machine
# ---------------------------------------------------------------------------


def _session():
    clock = _Clock()
    return VoiceSession(VoiceComposer("hi"), now_fn=clock), clock


def test_listening_then_partials_then_final_then_stopped():
    s, _ = _session()
    s.handle(C.VOICE_EVENT_LISTENING, "")
    assert s.listening and s.status == "Listening…" and s.text is None
    s.handle(C.VOICE_EVENT_PARTIAL, "make a")
    assert s.text == "hi make a"
    s.handle(C.VOICE_EVENT_FINAL, "make a cube")
    assert s.text == "hi make a cube"
    s.handle(C.VOICE_EVENT_STOPPED, "")
    assert s.done and not s.listening


def test_denied_permission_produces_a_notice_and_the_session_ends():
    s, _ = _session()
    s.handle(C.VOICE_EVENT_DENIED, "microphone")
    assert s.notice is not None and "microphone" in s.notice[1]
    assert "Privacy & Security" in s.notice[1]
    s.handle(C.VOICE_EVENT_STOPPED, "")
    assert s.done


def test_events_of_a_previous_session_are_ignored_before_listening():
    """Leftovers of an abandoned session precede the new LISTENING; a stale
    STOPPED must not end the session that just started, nor a stale partial
    write into its composer."""
    s, _ = _session()
    s.handle(C.VOICE_EVENT_PARTIAL, "old words")
    assert s.text is None
    s.handle(C.VOICE_EVENT_STOPPED, "")
    assert not s.done
    s.handle(C.VOICE_EVENT_LISTENING, "")
    s.handle(C.VOICE_EVENT_STOPPED, "")
    assert s.done


def test_a_stop_the_recogniser_never_acknowledges_times_out():
    s, clock = _session()
    s.handle(C.VOICE_EVENT_LISTENING, "")
    s.request_stop()
    clock.t += C.VOICE_STOP_GRACE_S / 2
    assert not s.timed_out()
    clock.t += C.VOICE_STOP_GRACE_S
    assert s.timed_out()


def test_a_session_cannot_run_forever():
    s, clock = _session()
    s.handle(C.VOICE_EVENT_LISTENING, "")
    clock.t += C.VOICE_MAX_SESSION_S + 1
    assert s.timed_out()


# ---------------------------------------------------------------------------
# Platform plumbing
# ---------------------------------------------------------------------------


def test_info_plist_declares_microphone_and_speech_usage():
    assert "<key>NSMicrophoneUsageDescription</key>" in PLIST
    assert "<key>NSSpeechRecognitionUsageDescription</key>" in PLIST


def test_voice_is_an_allowlist_and_registers_nothing_elsewhere():
    assert re.search(r'^VOICE_INPUT_SUPPORTED = sys\.platform == "darwin"', CONSTANTS_PY, re.M)
    assert "if VOICE_INPUT_SUPPORTED else ()" in VOICE_OPS_PY


def test_speech_helper_is_runtime_loaded_and_built():
    assert "dlopen(" in SPEECH_MM and "NSClassFromString(" in SPEECH_MM
    assert "[SFSpeechRecognizer " not in SPEECH_MM
    assert "[AVAudioEngine " not in SPEECH_MM
    assert "AVMediaTypeAudio" not in SPEECH_MM, "a framework constant symbol would need link flags"
    assert "NSMicrophoneUsageDescription" in SPEECH_MM  # documents the plist dependency
    assert "intern/GHOST_MixarSpeechCocoa.mm" in GHOST_CMAKE
    assert 'extern "C" bool Mixar_SpeechPopEvent(' in SPEECH_MM


def test_voice_operators_are_registered_and_built():
    for op in ("MIXIE_CHAT_OT_voice_start", "MIXIE_CHAT_OT_voice_stop", "MIXIE_CHAT_OT_voice_poll"):
        assert f"void {op}(wmOperatorType *ot)" in VOICE_CC
        assert f"WM_operatortype_append({op});" in SPACE_CC
    assert "mixie_chat_voice.cc" in CHAT_CMAKE


def test_sending_a_message_ends_a_running_dictation_first():
    send = CHAT_OPS_PY[CHAT_OPS_PY.index("scribble.flush_pending_ink()") - 400 : CHAT_OPS_PY.index("scribble.flush_pending_ink()")]
    assert "voice_input.stop_if_listening()" in send


def test_every_surface_binds_the_one_toggle():
    assert '"mixie_chat.voice_toggle"' in CHAT_HEADER_PY
    assert '"mixie_chat.voice_toggle"' in BUBBLE_HEADER_PY
    assert '"mixie_chat.voice_toggle"' in BUBBLE_CC
    # Drawn only where the operator exists — never a dead microphone.
    assert "hasattr(bpy.types, 'MIXIE_CHAT_OT_voice_toggle')" in CHAT_HEADER_PY
    assert "hasattr(bpy.types, 'MIXIE_CHAT_OT_voice_toggle')" in BUBBLE_HEADER_PY
    assert 'WM_operatortype_find("MIXIE_CHAT_OT_voice_toggle", true)' in STATE_CC


def test_island_voice_chip():
    enum = ICONS_HH[ICONS_HH.index("enum AgentIcon") :]
    enum = enum[: enum.index("};")]
    names = re.findall(r"AGENT_ICON_[A-Z_]+", enum)
    assert "AGENT_ICON_MIC" in names and names[-1] == "AGENT_ICON_COUNT"
    assert "rctf chip_voice;" in LAYOUT_HH
    assert "r_layout->chip_voice = f.box(voice_x, chip_y, AGENT_CHIP_VOICE_W, AGENT_CHIP_H);" in LAYOUT_CC
    assert "bool voice_available;" in DRAW_HH and "bool voice_listening;" in DRAW_HH
    assert "if (state->voice_available) {" in DRAW_CC
    assert "AGENT_ICON_MIC" in DRAW_CC
    # Without the operator the chips after Voice close the gap.
    begin = BUBBLE_CC[BUBBLE_CC.index("bool agent_bubble_island_layout_get(") :]
    begin = begin[: begin.index("\n}\n")]
    assert "if (!r_state->voice_available)" in begin
    assert "thumbs_after = layout->chip_voice;" in BUBBLE_CC


def _mm_fn(signature_start: str) -> str:
    start = SPEECH_MM.index(signature_start)
    return SPEECH_MM[start : SPEECH_MM.index("\n}\n", start)]


def test_permission_requests_are_gated_on_the_responsible_bundles_usage_string():
    """TCC reads the usage string from the bundle of the process RESPONSIBLE
    for us, not from ours: a `make run` from Cursor / VS Code / Terminal.app is
    attributed to the terminal app, none of which declares the speech key, and
    TCC answered the first Voice click by SIGKILLing Mixar (crash report of
    2026-09-05, `responsibleProc = Cursor`) while our own plist had both
    strings. Every request must be preceded by a check of THAT bundle."""
    assert 'dlsym(\n      RTLD_DEFAULT, "responsibility_get_pid_responsible_for_pid")' in SPEECH_MM
    attribution = _mm_fn("TccAttribution tcc_attribution()")
    assert "proc_pidpath(responsible" in attribution
    assert '[NSBundle bundleWithPath:dir]' in attribution
    assert "[NSBundle mainBundle]" in attribution  # the self-responsible case

    start = SPEECH_MM[SPEECH_MM.index('extern "C" bool Mixar_SpeechStart') :]
    assert start.index('tcc_request_allowed(@"NSSpeechRecognitionUsageDescription"') < start.index(
        "@selector(requestAuthorization:)")
    mic = _mm_fn("void request_microphone_then_start()")
    assert mic.index('tcc_request_allowed(@"NSMicrophoneUsageDescription"') < mic.index(
        "requestAccessForMediaType:")


def test_a_refused_request_explains_and_ends_the_session_without_asking():
    gate = _mm_fn("bool tcc_request_allowed(")
    assert "push_event_ns(SPEECH_EVENT_ERROR, why)" in gate
    assert 'push_event(SPEECH_EVENT_STOPPED, "")' in gate
    assert "requestAuthorization" not in gate and "requestAccessForMediaType" not in gate
    # The message names the launching app and the way out.
    assert "Launch Mixar.app" in gate and "who.app_name" in gate
    # The Python side surfaces ERROR text as the toast, so the explanation reaches
    # the user even from the island window (no status bar there).
    assert 'self.notice = ("error", f"Voice input failed: {payload' in VOICE_PY
