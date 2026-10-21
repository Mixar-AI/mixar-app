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
    from mixar.modules.space_mixie_chat.core import rules, scene_naming
    monkeypatch.setattr(scene_naming, 'auto_name_tab', lambda scene, text: '')
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


@pytest.fixture
def errors(monkeypatch):
    """The refusals handed to handle_command_error, and the loader clears."""
    from mixar.modules.space_mixie_chat.core import queue_processor
    shown = SimpleNamespace(results=[], cleared=[])
    monkeypatch.setattr(queue_processor, 'get_event_processor', lambda: SimpleNamespace(
        _clear_loader_bubbles=lambda target: shown.cleared.append(target),
        handle_command_error=lambda result, target, interjection=False:
            shown.results.append((result, interjection))))
    return shown


def _send(scene, state='IDLE', run_open=False):
    scene.mixie_chat_state, scene.mixie_run_open = state, run_open
    msg = scene.mixie_chat_messages.add()
    msg.sender = 'USER'
    assert composer_send.send_user_message(scene, composer_send.OutgoingMessage(
        'new message', user_message=msg)) == (True, '')
    return msg


@pytest.mark.parametrize('state,run_open', [('IDLE', False), ('IDLE', True), ('BUSY', True)])
def test_no_send_is_labelled(transport, state, run_open):
    """Not even an interjection waiting for its `joined` ack: bubbles carry
    no delivery label at all."""
    scene, calls = transport
    msg = _send(scene, state, run_open)
    assert msg.delivery_hint == ''
    assert msg.bubble_id == calls[0][1]['command_id']
    assert 'user_message' not in calls[0][0][1]


def test_batch_submit_does_not_reassign_prior_user_bubble(transport):
    scene, calls = transport
    msg = scene.mixie_chat_messages.add()
    msg.sender, msg.bubble_id = 'USER', 'earlier-command'
    handler = turn_transport.create_turn_handler(scene.name)
    assert handler.start_input_stream('sid', 'submit', answers=[{'answer': 'blue'}])
    assert msg.bubble_id == 'earlier-command'
    turn_events._consume('agent.command.result', {'command_id': calls[0][1]['command_id'], 'ok': True})
    assert (msg.bubble_id, msg.delivery_hint) == ('earlier-command', '')


def test_out_of_order_replies_keep_their_original_message(transport, errors):
    scene, calls = transport
    scene.mixie_chat_state, scene.mixie_run_open = 'BUSY', True
    first, second = scene.mixie_chat_messages.add(), scene.mixie_chat_messages.add()
    first.sender = second.sender = 'USER'
    for msg in (first, second):
        assert composer_send.send_user_message(scene, composer_send.OutgoingMessage('join', user_message=msg))[0]
    ids = (first.bubble_id, second.bubble_id)
    turn_events._consume('agent.command.result', {'command_id': second.bubble_id, 'ok': True})
    turn_events._consume('agent.command.result', {'command_id': first.bubble_id, 'uncertain': True})
    assert (first.bubble_id, second.bubble_id) == ids
    assert first.delivery_hint == second.delivery_hint == ''
    assert errors.results == []  # still being resent: nothing to say yet


def test_send_holds_the_frame_until_the_server_answers(transport, errors):
    scene, calls = transport
    # A message into an open run (the first-message naming path needs a real scene).
    scene.mixie_chat_state, scene.mixie_run_open = 'BUSY', True
    msg = scene.mixie_chat_messages.add()
    msg.sender = 'USER'
    assert composer_send.send_user_message(scene, composer_send.OutgoingMessage(
        'remove background', user_message=msg))[0]
    (method, payload, ack), kw = calls[0]
    cid = kw['command_id']
    assert turn_events._outbox[cid]['payload'] is payload
    ack({'code': -32020, 'data': {'uncertain': True, 'disconnected': True}})
    turn_events._drain()
    # Uncertain is not a failure: no label, no message, the frame stays held.
    assert cid in turn_events._outbox and msg.delivery_hint == '' and errors.results == []
    turn_events._outbox[cid]['attempts'] = 1  # resent on the next socket ...
    ack({'command_id': cid, 'state': 'accepted'})  # ... and admitted there
    turn_events._drain()
    assert cid not in turn_events._outbox and msg.delivery_hint == '' and errors.results == []


@pytest.mark.parametrize('state,run_open,interjection', [
    ('IDLE', False, False), ('BUSY', True, True),
])
def test_a_refusal_is_one_agent_message_and_never_a_label(transport, errors, state, run_open,
                                                         interjection):
    """A refused send AND a refused interjection both go to handle_command_error
    (BYOK card, sign-in / credits notice, or the plain-language error). The
    interjection's still-running turn keeps its loader and state."""
    scene, calls = transport
    msg = _send(scene, state, run_open)
    turn_events._consume('agent.command.result', {
        'command_id': msg.bubble_id, 'ok': False, 'status_code': 409,
        'code': 'byok_key_required', 'provider': 'codex'})
    assert msg.delivery_hint == ''
    assert [flag for _, flag in errors.results] == [interjection]
    assert errors.cleared == ([] if interjection else [scene])
    assert scene.mixie_chat_state == state


def test_a_server_side_cancel_says_nothing(transport, errors):
    """{ok: False, cancelled: True} is the backend's cancel of a message it
    received: the cancel shows its own state, no error and no label."""
    scene, calls = transport
    msg = _send(scene)
    turn_events._consume('agent.command.result', {
        'command_id': msg.bubble_id, 'ok': False, 'cancelled': True,
        'message': 'Agent command cancelled'})
    assert msg.delivery_hint == '' and errors.results == []


def test_a_message_the_client_gave_up_resending_is_one_friendly_message(transport, errors, monkeypatch):
    from mixar.modules.space_mixie_chat.core import send_failure
    scene, calls = transport
    msg = _send(scene)
    cid = msg.bubble_id
    resent = []
    from mixar.modules.common.agent_rpc import client
    monkeypatch.setattr(client, 'command', lambda *a, **kw: resent.append(kw['command_id']))
    for _ in range(turn_events._MAX_REDELIVERIES):
        turn_events._redeliver(cid, 'sid')  # request_status said "unknown"
        turn_events._drain()
    # Every automatic resend is still pending: nothing shown yet.
    assert resent == [cid] * turn_events._MAX_REDELIVERIES and errors.results == []
    turn_events._redeliver(cid, 'sid')  # the last attempt failed too: give up
    turn_events._drain()
    assert len(errors.results) == 1 and msg.delivery_hint == ''
    result, interjection = errors.results[0]
    assert result.get('undelivered') and not interjection
    assert send_failure.refusal_text(result) == send_failure.MSG_NOT_DELIVERED


def test_a_send_the_client_could_not_make_never_shows_the_exception(transport, errors, monkeypatch):
    from mixar.modules.common.agent_rpc.client import AgentRPCError
    from mixar.modules.space_mixie_chat.core import send_failure

    def offline(*args, **kwargs):
        raise AgentRPCError('Agent is reconnecting. Please try again when connected.')

    monkeypatch.setattr(turn_transport, 'command', offline)
    scene, calls = transport
    scene.mixie_chat_state = 'IDLE'
    msg = scene.mixie_chat_messages.add()
    msg.sender = 'USER'
    composer_send.send_user_message(scene, composer_send.OutgoingMessage('hi', user_message=msg))
    turn_events._drain()
    (result, _), = errors.results
    assert 'message' not in result and result['unsent'] is True
    assert send_failure.refusal_text(result) == send_failure.MSG_OFFLINE
    assert msg.delivery_hint == ''
