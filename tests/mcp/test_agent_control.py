# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Full-agent hand-off never borrows a script lease or answers stale questions."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from mixar.modules.mcp_bridge.core import agent_control as control
from mixar.modules.space_mixie_chat.constants import SessionState


def message(sender='AGENT', **fields):
    return SimpleNamespace(sender=sender, bubble_id='', text='', content='', input_type='',
        interrupt_id='', delivery_hint='', action_items=[], batched_questions='', **fields)


@pytest.fixture
def rig(monkeypatch):
    cid, sid = str(uuid4()), str(uuid4())
    user = message('USER')
    user.bubble_id = cid
    scene = SimpleNamespace(mixie_session_id=sid, mixie_chat_messages=[user], name='Selected')
    session = SimpleNamespace(get_state=Mock(return_value=SessionState.IDLE), run_open=Mock(return_value=False))
    monkeypatch.setattr(control.lease, '_enabled', lambda: True)
    monkeypatch.setattr(control.lease, 'has_active_operation', lambda sid: False)
    monkeypatch.setattr(control, '_scene', lambda sid: (scene, session))
    send = Mock(return_value={'success': True})
    monkeypatch.setattr(control, '_send', send)
    return SimpleNamespace(cid=cid, sid=sid, scene=scene, session=session, send=send)


def dispatch(rig, action, **kwargs):
    return control.dispatch(dict(action=action, session_id=rig.sid, command_id=str(uuid4()), **kwargs))


def test_start_uses_same_scene_and_exact_brief(rig):
    result = dispatch(rig, 'start', text='Make a chair with curved arms and mortise joints')
    assert result['success']
    assert rig.send.call_args.args[0] is rig.scene
    assert rig.send.call_args.args[1]['text'] == 'Make a chair with curved arms and mortise joints'


@pytest.mark.parametrize('state', [SessionState.BUSY, SessionState.AWAITING_INPUT, SessionState.OFFLINE])
def test_start_does_not_interject_or_answer_a_different_task(rig, state):
    rig.session.get_state.return_value = state
    assert not dispatch(rig, 'start', text='Another model')['success']
    rig.send.assert_not_called()


def test_open_run_blocks_start_even_when_foreground_idle(rig):
    rig.session.run_open.return_value = True
    assert not dispatch(rig, 'start', text='Another model')['success']
    rig.send.assert_not_called()


def test_status_returns_only_visible_content_not_private_thinking(rig):
    response = message(thinking_text='private reasoning', ephemeral='private draft')
    response.content = 'Built the chair; inspection found four legs.'
    rig.scene.mixie_chat_messages.append(response)
    result = control.status(rig.scene, rig.session, rig.cid)
    assert result['messages'] == [response.content]
    assert 'private' not in str(result)


def test_a_newer_user_turn_fences_response_and_cancellation(rig):
    rig.scene.mixie_chat_messages.append(message('USER'))
    for action in ('respond', 'cancel'):
        result = dispatch(rig, action, text='Yes', target_command_id=rig.cid, interrupt_id='old')
        assert not result['success'] and 'newer' in result['error']
    rig.send.assert_not_called()


def test_question_identity_must_match_and_file_pickers_stay_local(rig):
    rig.session.get_state.return_value = SessionState.AWAITING_INPUT
    question = message()
    question.input_type, question.interrupt_id = 'file_save', 'current'
    rig.scene.mixie_chat_messages.append(question)
    for interrupt, error in [('stale', 'question changed'), ('current', 'native file picker')]:
        result = dispatch(rig, 'respond', text='Yes', target_command_id=rig.cid, interrupt_id=interrupt)
        assert not result['success'] and error in result['error']
    rig.send.assert_not_called()


def test_exact_current_user_response_reaches_normal_composer(rig):
    rig.session.get_state.return_value = SessionState.AWAITING_INPUT
    question = message()
    question.input_type, question.interrupt_id = 'choice', 'current'
    rig.scene.mixie_chat_messages.append(question)
    result = dispatch(rig, 'respond', text='Use walnut', target_command_id=rig.cid, interrupt_id='current')
    assert result['success']
    assert rig.send.call_args.args[1]['text'] == 'Use walnut'
