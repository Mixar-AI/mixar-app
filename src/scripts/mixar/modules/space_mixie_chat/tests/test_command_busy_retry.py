# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A -32017 busy ack resends the SAME command once after the server's hint."""

import sys
from types import SimpleNamespace

import pytest
from _open_run_support import _scene, clean_state, live_bpy  # noqa: F401
from mixar.modules.space_mixie_chat.core import command_retry, turn_events, turn_transport

BUSY = {'code': -32017, 'message': 'busy',
        'data': {'retry_after_s': 7, 'reason': 'admission_busy'}}


@pytest.fixture
def sent(monkeypatch, live_bpy):  # noqa: F811
    from mixar.modules.space_mixie_chat.core import rules
    scene = _scene(session_id='sid')
    live_bpy.data.scenes.append(scene)
    monkeypatch.setattr(turn_events, 'arm', lambda: None)
    monkeypatch.setattr(rules, 'rules_snapshot', lambda scene: {'v': 1})
    calls, timers, results = [], [], []
    monkeypatch.setattr(turn_transport, 'command', lambda *a, **kw: calls.append((a, kw)))
    # The send path seals the user's BYOK credential before dispatching; the
    # platform path dispatches at once with no key fields.
    monkeypatch.setitem(sys.modules, 'mixar.modules.byok.core.turn_credentials', SimpleNamespace(
        prepare=lambda dispatch, method='chat', action=None: dispatch({}, None)))
    monkeypatch.setattr(command_retry, '_register_timer',
                        lambda fn, delay: timers.append((fn, delay)))
    handler = turn_transport.create_turn_handler(scene.name)
    assert handler.start_input_stream('sid', 'respond', text='go')
    command_id = calls[0][1]['command_id']
    # Watch the settle callback: a result must not fire before the retry.
    sid, _settle = turn_events._commands[command_id]
    turn_events._commands[command_id] = (sid, lambda s, r: results.append(r))
    yield SimpleNamespace(scene=scene, calls=calls, timers=timers, results=results,
                          command_id=command_id, handler=handler)
    turn_transport._handlers.clear()
    turn_events.reset()


def _ack(call, result):
    call[0][2](result)
    turn_events._drain()


def test_busy_ack_resends_once_with_the_same_command_id(sent):
    _ack(sent.calls[0], BUSY)
    assert sent.results == []  # no agent.command.result on the first -32017
    assert len(sent.calls) == 1 and [d for _, d in sent.timers] == [7.0]
    sent.timers[0][0]()  # the timer fires on the main thread
    assert len(sent.calls) == 2
    first, again = sent.calls
    assert again[1]['command_id'] == sent.command_id
    assert again[0][0] == first[0][0] and again[0][1] is first[0][1]  # same payload
    # A second refusal surfaces the error; there is no third send.
    _ack(again, BUSY)
    assert len(sent.calls) == 2 and len(sent.timers) == 1
    assert sent.results and sent.results[0]['ok'] is False


def test_busy_ack_without_a_hint_waits_three_seconds(sent):
    _ack(sent.calls[0], {'code': -32017, 'message': 'busy'})
    assert [d for _, d in sent.timers] == [3.0]


def test_stop_cancels_the_pending_resend(sent):
    _ack(sent.calls[0], BUSY)
    turn_events.drop_scene(sent.scene.name)  # what Stop does
    sent.timers[0][0]()
    assert len(sent.calls) == 1


def test_stop_before_the_retry_is_armed_arms_nothing(sent):
    sent.calls[0][0][2](BUSY)  # ack on the WS thread
    turn_events.drop_scene(sent.scene.name)
    turn_events._drain()
    assert sent.timers == [] and len(sent.calls) == 1


def test_other_errors_still_surface_at_once(sent):
    _ack(sent.calls[0], {'code': -32603, 'message': 'boom'})
    assert sent.timers == [] and sent.results[0]['ok'] is False


def test_resend_that_cannot_send_surfaces_the_error(sent, monkeypatch):
    _ack(sent.calls[0], BUSY)

    def offline(*a, **kw):
        raise RuntimeError('Agent is reconnecting')

    monkeypatch.setattr(turn_transport, 'command', offline)
    sent.timers[0][0]()
    turn_events._drain()
    assert sent.results and sent.results[0]['message'] == 'Agent is reconnecting'
