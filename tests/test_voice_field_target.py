# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native-field results cannot write chat or cancel another dictation target."""
from types import SimpleNamespace as NS
from unittest.mock import Mock

from test_voice_capture_start import rig  # noqa: F401
from mixar.modules.space_mixie_chat.core.voice_input import fields


def test_stale_field_cannot_clear_a_new_target():
    wm = NS()
    fields.begin(wm, 'new')
    fields.clear(wm, 'old')
    assert wm.mixie_chat_voice_field_token == 'new'


def test_final_is_sanitized_and_stays_in_native_mailbox():
    wm = NS()
    fields.publish(wm, 'node', '  blue\x1f cube\x00  ')
    assert wm.mixie_chat_voice_field_ready
    assert wm.mixie_chat_voice_field_text == 'blue cube'
    fields.clear(wm, 'node')
    assert not wm.mixie_chat_voice_field_ready
    assert not wm.mixie_chat_voice_field_text


def test_field_result_never_reads_or_writes_the_chat_draft(rig):
    voice, session, _, _ = rig
    import bpy
    session.field_token = 'image-node'
    session.draft = None
    voice._identity = Mock(side_effect=AssertionError('chat identity read'))
    voice._attachments = Mock(side_effect=AssertionError('chat attachments read'))
    voice._begin_capture(session)
    voice.stop()
    session.transport.events.put({'type': 'final', 'text': 'blue cube'})
    assert voice._tick() is None
    assert session.scene.mixie_chat_input == 'Keep draft'
    assert bpy.context.window_manager.mixie_chat_voice_field_text == 'blue cube'
    assert bpy.context.window_manager.mixie_chat_voice_field_token == 'image-node'
    assert voice._session is None


def test_field_transcript_preserves_paragraphs_and_unicode_without_control_bytes():
    wm = NS()
    fields.publish(wm, 'node', ' café\r\nblue\tcube\rnext\u2028line\u2029end\x07\x7f ')
    assert wm.mixie_chat_voice_field_text == 'café\nblue cube\nnext\nline\nend'
    fields.publish(wm, 'node', ''.join(chr(c) for c in range(32)) + '\x7f')
    assert wm.mixie_chat_voice_field_text == ''


def test_send_during_field_capture_never_submits_a_chat(rig):
    voice, session, _, _ = rig
    session.field_token = 'node'
    session.draft = None
    assert voice.defer_send(NS(scene=session.scene)) is True
    assert voice._session is None
    assert session.scene.mixie_chat_input == 'Keep draft'


def test_cancel_from_old_field_cannot_stop_current_capture(rig):
    voice, session, _, _ = rig
    wm = NS()
    fields.begin(wm, 'new')
    session.field_token = 'new'
    voice.cancel_field(NS(window_manager=wm), 'old')
    assert voice._session is session
    assert wm.mixie_chat_voice_field_token == 'new'


def test_chat_field_cannot_accept_a_previous_conversations_result(rig):
    voice, session, _, _ = rig
    session.field_token = 'composer'
    session.field_chat_identity = 'previous-chat'
    session.draft = None
    session.transport.events.put({'type': 'final', 'text': 'wrong conversation'})
    assert voice._tick() is None
    assert voice._session is None
    assert session.scene.mixie_chat_input == 'Keep draft'
