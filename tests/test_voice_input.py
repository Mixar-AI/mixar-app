# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Dictation owns one draft and may satisfy one explicit send, never two."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'src/scripts/mixar/modules/space_mixie_chat/core'
spec = importlib.util.spec_from_file_location(
    'mixar.modules.space_mixie_chat.core.voice_input._draft_tests',
    CORE / 'voice_input/composer.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Draft = module.Draft
from mixar.modules.space_mixie_chat.constants import CHAT_INPUT_MAXLEN


def test_stop_inserts_without_sending():
    draft = Draft('Make it red.', 'chat1')
    assert draft.final('Add a bevel.', 'Make it red.', 'chat1') == ('Make it red. Add a bevel.', False)


def test_explicit_send_waits_and_is_consumed_once():
    draft = Draft('', 'chat1')
    draft.pending_send = True
    assert draft.final('A cube', '', 'chat1') == ('A cube', True)
    assert draft.final('A cube', '', 'chat1') == (None, False)


def test_manual_edit_is_preserved_and_cancels_pending_send():
    draft = Draft('Red', 'chat1')
    draft.pending_send = True
    assert draft.final('cube', 'Blue', 'chat1') == ('Blue cube', False)


def test_late_transcript_cannot_enter_a_new_chat():
    draft = Draft('', 'chat1')
    draft.pending_send = True
    assert draft.final('Delete it', '', 'chat2') == (None, False)


def test_empty_speech_never_sends_existing_text():
    draft = Draft('Keep camera', 'chat1')
    draft.pending_send = True
    assert draft.final('', 'Keep camera', 'chat1') == (None, False)


def test_voice_cannot_inject_submit_marker():
    draft = Draft('', 'chat1')
    assert draft.final('hello\x1f', '', 'chat1') == ('hello', False)


def test_overflow_refuses_instead_of_truncating_instruction():
    draft = Draft('x' * CHAT_INPUT_MAXLEN, 'chat1')
    with pytest.raises(ValueError):
        draft.final('do not delete', draft.base, 'chat1')


def test_permission_guard_and_native_capture_are_bundled():
    native = (ROOT / 'src/source/blender/python/intern/bpy_mixar_capture.cc').read_text()
    cocoa = (ROOT / 'src/intern/ghost/intern/GHOST_MixarMicrophoneCocoa.mm').read_text()
    assert 'alcCaptureStop' in native and 'alcCaptureSamples' in native
    assert 'NSMicrophoneUsageDescription' in cocoa
    assert 'NSSpeechRecognitionUsageDescription' not in cocoa
