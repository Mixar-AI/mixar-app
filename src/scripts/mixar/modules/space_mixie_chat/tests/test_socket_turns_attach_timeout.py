# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A reconnect's ``agent.attach`` whose reply never arrives is not a verdict (#2061).

Prod 2026-11-10 (app 4.4.3, session c9218157, turn ded9ce6b): during a 150 s
``await_generation`` the downstream path died. Socket #2 sent ``agent.attach``;
the server attached the running turn and answered at once, but the client
received only the handshake reply. Its request deadline (35 s) fired before
the 50 s idle watchdog dropped the socket, so the reply was the CLIENT-made
timeout ``{"code": -32020, "data": {"uncertain": True}}`` (no ``disconnected``).
``_request_replay`` read it as "unavailable": the turn was settled, the tab went
IDLE, socket #3 never re-attached and the backend's next scripts were refused
with "Agent session not active", ending the turn.

The socket here is the real JSON-RPC client: its own deadline sweep produces
the timeout payload and its own response routing delivers the late answer.
"""
import json

import pytest

from _open_run_support import clean_state, live_bpy  # noqa: F401 — fixtures
from test_socket_turns import _real_request_replay, attach, env, event, settle  # noqa: F401
from mixar.modules.common.agent_rpc import client as agent_rpc
from mixar.modules.space_mixie_chat.core import turn_events as events, turn_resume
from mixar.modules.space_mixie_chat.core.jsonrpc_client import JSONRPCWebSocketClient
from mixar.modules.space_mixie_chat.core.session import SessionManager
from mixar.modules.space_mixie_chat.constants import SessionState


def _sent(socket):
    """Frames the client queued on this socket, oldest first."""
    frames = []
    while not socket._outbound.empty():
        frames.append(json.loads(socket._outbound.get_nowait()))
    return frames


def _attaches(frames):
    return [f for f in frames if f.get('method') == 'agent.attach']


def _deadline_passes(socket):
    """35 s go by with no answer: the socket's own sweep fires the timeouts."""
    with socket._pending_lock:
        for key in socket._pending_deadlines:
            socket._pending_deadlines[key] = 0.0
    socket._expire_pending()


@pytest.fixture
def wire(env, settle, monkeypatch):
    """A running turn (cursor 0, BUSY, run open) and a switchable socket."""
    sockets = []
    settle.rendered = env.rendered
    monkeypatch.setattr(events, '_request_replay', _real_request_replay)
    monkeypatch.setattr(agent_rpc, 'get_client', lambda: sockets[-1])
    monkeypatch.setattr(turn_resume, 'check_orphaned_turns', lambda: None)
    # The scene really is busy, as the gate on backend scripts sees it.
    SessionManager.set_state(settle.scene, SessionState.BUSY)
    SessionManager.set_run(settle.scene, 'run', True)

    def connect():
        """A new socket completes its handshake; on_connected runs reconnect()."""
        socket = JSONRPCWebSocketClient('http://unused', 'test')
        sockets.append(socket)
        events.reconnect()
        return socket, _sent(socket)

    settle.connect = connect
    return settle


def test_a_timed_out_attach_keeps_the_turn_and_reattaches_on_the_next_socket(wire):
    turn = events._turns['turn']
    assert turn.cursor == 0 and not turn.complete

    # Socket #2: the attach (and agent.status) go out; no answer ever arrives.
    socket2, frames = wire.connect()
    [attach] = _attaches(frames)
    assert attach['params'] == {'session_id': 'sid', 'turn_id': 'turn', 'after_seq': 0}
    _deadline_passes(socket2)
    events._drain()

    # Not a verdict: the turn is still live and backend scripts are accepted.
    assert not turn.complete
    assert wire.notices == []  # no "The connection lost part of this response"
    assert wire.scene.mixie_chat_state == 'BUSY' and wire.scene.mixie_run_open
    assert SessionManager.has_active_session('sid')

    # Socket #3: the next connection attaches the same turn from the rendered cursor.
    socket3, frames = wire.connect()
    [attach] = _attaches(frames)
    assert attach['params'] == {'session_id': 'sid', 'turn_id': 'turn', 'after_seq': 0}

    # The server answers this time, and the turn finishes normally.
    socket3._handle_message({'jsonrpc': '2.0', 'id': attach['id'], 'result': {
        'turn_id': 'turn', 'run_id': 'run', 'status': 'running', 'replay_available': True,
        'last_seq': 0}})
    event(1)
    event(2, {'type': 'turn_end', 'status': 'completed'})
    events._drain()
    assert turn.complete and turn.attach_failures == 0
    assert wire.notices == []
    assert [p.get('type') for p in wire.rendered if isinstance(p, dict)][-1] == 'turn_end'


def test_a_late_reply_on_a_live_socket_does_not_settle_the_turn(wire):
    """A slow server (the reply lands after the deadline) is the same case:
    the late answer finds no callback and the stream that follows renders."""
    turn = events._turns['turn']
    socket2, frames = wire.connect()
    [attach] = _attaches(frames)
    _deadline_passes(socket2)
    socket2._handle_message({'jsonrpc': '2.0', 'id': attach['id'], 'result': {
        'turn_id': 'turn', 'status': 'running', 'replay_available': True, 'last_seq': 0}})
    event(1)
    events._drain()
    assert not turn.complete and turn.cursor == 1
    assert wire.notices == [] and SessionManager.has_active_session('sid')


def test_a_timeout_on_a_live_socket_asks_again_and_its_verdict_settles(wire):
    """A socket that stays up never reconnects, so nothing else would ask again:
    the turn would sit Busy with no request pending. It asks again on it."""
    turn = events._turns['turn']
    socket2, frames = wire.connect()
    [first] = _attaches(frames)
    _deadline_passes(socket2)
    [again] = _attaches(_sent(socket2))
    assert again['params'] == first['params'] and again['id'] != first['id']
    assert turn.attach_failures == 1 and not turn.complete

    # The first answer lands late and finds no callback; the second is a verdict.
    socket2._handle_message({'jsonrpc': '2.0', 'id': first['id'], 'result': {'status': 'unavailable'}})
    events._drain()
    assert not turn.complete
    socket2._handle_message({'jsonrpc': '2.0', 'id': again['id'], 'result': {'status': 'unavailable'}})
    events._drain()
    assert turn.complete and wire.scene.mixie_chat_state == 'IDLE'


def test_events_after_an_attach_prove_it_was_heard(wire):
    """Its replay streaming means the server got the attach; only the answer was
    lost. Many slow answers over one long turn never use up the retries."""
    turn = events._turns['turn']
    for seq in range(1, events._MAX_ATTACH_FAILURES + 3):
        socket, frames = wire.connect()
        assert len(_attaches(frames)) == 1
        event(seq)
        events._drain()
        _deadline_passes(socket)
        events._drain()
        assert _attaches(_sent(socket)) == []  # heard: nothing to ask again
        assert turn.attach_failures == 0 and not turn.complete and turn.cursor == seq
    assert wire.notices == [] and SessionManager.has_active_session('sid')


def test_timed_out_attaches_share_the_bounded_failure_budget(attach):
    """Still bounded: a server that never answers ends the turn after the cap,
    each timeout having asked again on the live socket."""
    from test_socket_turns import _verdicts
    turn, replies = attach
    timed_out = {'code': -32020, 'message': 'Request timed out; delivery is uncertain',
                 'data': {'uncertain': True}}
    _real_request_replay(turn)
    for n in range(events._MAX_ATTACH_FAILURES):
        replies[-1](timed_out)
        assert len(replies) == n + 2 and not turn.complete and _verdicts() == []
    replies[-1](timed_out)
    assert _verdicts() == ['resume_unavailable']
    assert len(replies) == events._MAX_ATTACH_FAILURES + 1  # no ask after the cap


def test_a_silent_socket_costs_one_retry(attach):
    """The #2061 shape: the deadline fires on a socket whose downstream is dead,
    then its teardown flushes the re-send. That socket's loss counts once, so
    an outage still gets three silent sockets before the turn settles."""
    from test_socket_turns import _verdicts
    turn, replies = attach
    timed_out = {'code': -32020, 'data': {'uncertain': True}}
    gone = {'code': -32020, 'data': {'uncertain': True, 'disconnected': True}}
    for n in range(events._MAX_ATTACH_FAILURES):
        _real_request_replay(turn)  # reconnect() on a new socket
        replies[-1](timed_out)      # 35 s: asks again on it
        replies[-1](gone)           # ~50 s: the teardown flushes the re-send
        assert turn.attach_failures == n + 1 and not turn.complete and _verdicts() == []
    _real_request_replay(turn)
    replies[-1](timed_out)
    assert _verdicts() == ['resume_unavailable']
