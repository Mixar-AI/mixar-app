# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A command can update only the user bubble explicitly created for it."""

from types import SimpleNamespace

import pytest
from _open_run_support import _scene, clean_state, live_bpy
from mixar.modules.space_mixie_chat.core import composer_send, turn_events, turn_transport


@pytest.fixture
def transport(monkeypatch, live_bpy):
    from mixar.modules.common.agent_rpc import client
    from mixar.modules.space_mixie_chat.core import rules
    scene = _scene(session_id='sid')
    live_bpy.data.scenes.append(scene)
    monkeypatch.setattr(turn_events, 'arm', lambda: None)
    monkeypatch.setattr(client, 'get_client', lambda: SimpleNamespace(connection_id='connection'))
    monkeypatch.setattr(rules, 'compose_wire_message', lambda scene, text: text)
    monkeypatch.setattr(rules, 'mark_rules_sent', lambda scene: None)
    calls = []
    monkeypatch.setattr(turn_transport, 'command', lambda *a, **kw: calls.append((a, kw)))
    yield scene, calls
    turn_transport._handlers.clear()


@pytest.mark.parametrize('state,run_open,hint', [
    ('IDLE', False, ''), ('IDLE', True, ''), ('BUSY', True, 'queued'),
])
def test_only_interjections_display_queued(transport, state, run_open, hint):
    scene, calls = transport
    scene.mixie_chat_state, scene.mixie_run_open = state, run_open
    msg = scene.mixie_chat_messages.add()
    msg.sender = 'USER'
    assert composer_send.send_user_message(scene, composer_send.OutgoingMessage(
        'new message', user_message=msg)) == (True, '')
    assert msg.delivery_hint == hint
    assert msg.bubble_id == calls[0][1]['command_id']
    assert 'user_message' not in calls[0][0][1]


def test_batch_submit_does_not_reassign_prior_user_bubble(transport):
    scene, calls = transport
    msg = scene.mixie_chat_messages.add()
    msg.sender, msg.bubble_id, msg.delivery_hint = 'USER', 'earlier-command', 'queued'
    handler = turn_transport.create_turn_handler(scene.name)
    assert handler.start_input_stream('sid', 'submit', answers=[{'answer': 'blue'}])
    assert (msg.bubble_id, msg.delivery_hint) == ('earlier-command', 'queued')
    turn_events._consume('agent.command.result', {'command_id': calls[0][1]['command_id'], 'ok': True})
    assert (msg.bubble_id, msg.delivery_hint) == ('earlier-command', 'queued')


def test_out_of_order_replies_keep_their_original_message(transport):
    scene, calls = transport
    scene.mixie_chat_state, scene.mixie_run_open = 'BUSY', True
    first, second = scene.mixie_chat_messages.add(), scene.mixie_chat_messages.add()
    first.sender = second.sender = 'USER'
    for msg in (first, second):
        assert composer_send.send_user_message(scene, composer_send.OutgoingMessage('join', user_message=msg))[0]
    turn_events._consume('agent.command.result', {'command_id': second.bubble_id, 'ok': True})
    assert second.delivery_hint == '' and first.delivery_hint == 'queued'
    turn_events._consume('agent.command.result', {'command_id': first.bubble_id, 'uncertain': True})
    assert first.delivery_hint == 'delivery uncertain' and second.delivery_hint == ''
