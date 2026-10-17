# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A command the server never answers probes the path in seconds, not at the idle watchdog."""
import json
import threading
import time
from queue import Empty
from types import SimpleNamespace

from mixar.modules.space_mixie_chat.constants import (
    WS_ACK_MIN_UPLINK_BPS,
    WS_ACK_TIMEOUT,
    WS_LIVENESS_PROBE_GRACE,
    WS_LIVENESS_TIMEOUT,
)
from mixar.modules.space_mixie_chat.core import socket_liveness, turn_events
from mixar.modules.space_mixie_chat.core.jsonrpc_client import JSONRPCWebSocketClient
from mixar.modules.space_mixie_chat.core.socket_writer import start_writer


def client():
    c = JSONRPCWebSocketClient('http://unused', 'test')
    c._diag.begin()
    c._connected = True
    c._last_recv_time = c._last_reply_time = time.time()
    c.aborted = threading.Event()
    c._ws = SimpleNamespace(sock=None, send=lambda frame: None, shutdown=c.aborted.set)
    return c


def sent(c):
    """Play the writer: everything queued leaves; returns the frames."""
    frames = []
    while True:
        try:
            frame = c._outbound.get_nowait()
        except Empty:
            frame = None
        if frame is not None:
            frames.append(json.loads(frame))
            socket_liveness.uploaded(c, len(frame))
        else:
            socket_liveness.drained(c)
            return frames


def age(c, seconds):
    """Pretend ``seconds`` passed with no inbound traffic since every send."""
    c._last_recv_time -= seconds
    c._last_reply_time -= seconds
    if c._last_send_progress:
        c._last_send_progress -= seconds
    c._upload_clear_at -= seconds
    for rid, at in c._awaiting_ack.items():
        if at is not None:
            c._awaiting_ack[rid] = at - seconds
    if c._liveness_probe_started is not None:
        c._liveness_probe_started -= seconds


def test_unanswered_command_probes_then_aborts_a_dead_path():
    c = client()
    c.send_request('agent.chat', {}, lambda value: None, expect_ack=True)
    sent(c)
    age(c, WS_ACK_TIMEOUT + 1)
    assert not socket_liveness.tick(c)
    assert [f['method'] for f in sent(c)] == ['system.ping']
    age(c, WS_LIVENESS_PROBE_GRACE + 1)
    assert socket_liveness.tick(c)
    assert c.aborted.is_set() and not c._connected
    assert c._diag.current.reason == 'ack_timeout'


def test_the_probe_answered_keeps_the_socket():
    c = client()
    c.send_request('agent.chat', {}, lambda value: None, expect_ack=True)
    sent(c)
    age(c, WS_ACK_TIMEOUT + 1)
    socket_liveness.tick(c)
    probe = sent(c)[-1]
    age(c, WS_LIVENESS_PROBE_GRACE + 1)
    c._last_recv_time = time.time()
    c._handle_message({'jsonrpc': '2.0', 'id': probe['id'], 'result': {'pong': True}})
    assert not socket_liveness.tick(c)
    assert not c.aborted.is_set() and c._liveness_probe_started is None


def test_server_frames_alone_do_not_prove_the_upstream():
    # Dead one way: the server's pings and events keep arriving, ours vanish.
    c = client()
    c.send_request('agent.chat', {}, lambda value: None, expect_ack=True)
    sent(c)
    age(c, WS_ACK_TIMEOUT + 1)
    c._last_recv_time = time.time()  # a server ping just arrived
    socket_liveness.tick(c)
    assert c._liveness_probe_why == 'unanswered'
    sent(c)
    age(c, WS_LIVENESS_PROBE_GRACE + 1)
    c._last_recv_time = time.time()
    c._handle_message({'jsonrpc': '2.0', 'method': 'agent.turn.event', 'params': {}})
    assert socket_liveness.tick(c)


def test_an_unanswered_keepalive_ping_probes_an_idle_socket():
    c = client()
    c._send_ping()
    sent(c)
    age(c, WS_ACK_TIMEOUT + 1)
    c._last_recv_time = time.time()  # downstream still flowing
    socket_liveness.tick(c)
    assert c._liveness_probe_why == 'unanswered'


def test_no_probe_before_the_frame_left_or_after_its_answer():
    c = client()
    rid = c.send_request('agent.chat', {}, lambda value: None, expect_ack=True)
    age(c, WS_ACK_TIMEOUT + 1)  # still queued: a slow upload ahead of it is not silence
    assert not socket_liveness.tick(c) and c._liveness_probe_started is None
    sent(c)
    c._handle_message({'jsonrpc': '2.0', 'id': rid, 'result': {'state': 'accepted'}})
    age(c, WS_ACK_TIMEOUT + 1)
    assert not socket_liveness.tick(c) and c._liveness_probe_started is None
    sent(c)  # the writer's next idle tick forgets the answered command
    assert not c._awaiting_ack


def test_plain_requests_wait_for_the_idle_watchdog():
    c = client()
    c.send_request('agent.request_status', {}, lambda value: None)
    sent(c)
    age(c, WS_ACK_TIMEOUT + 1)
    assert not socket_liveness.tick(c) and c._liveness_probe_started is None
    age(c, WS_LIVENESS_TIMEOUT)
    socket_liveness.tick(c)
    sent(c)
    age(c, WS_LIVENESS_PROBE_GRACE + 1)
    assert socket_liveness.tick(c)
    assert c._diag.current.reason == 'liveness_timeout'


def test_a_starved_thread_or_an_unsent_probe_restarts_the_grace():
    c = client()
    c.send_request('agent.chat', {}, lambda value: None, expect_ack=True)
    sent(c)
    age(c, WS_ACK_TIMEOUT + 1)
    socket_liveness.tick(c)
    age(c, WS_LIVENESS_PROBE_GRACE + 1)
    assert not socket_liveness.tick(c)  # the probe ping is still queued
    sent(c)
    age(c, WS_LIVENESS_PROBE_GRACE + 1)
    assert not socket_liveness.tick(c, starved=True)
    assert not c.aborted.is_set()
    age(c, WS_LIVENESS_PROBE_GRACE + 1)
    assert socket_liveness.tick(c)


def test_a_shrinking_send_backlog_is_a_live_slow_uplink(monkeypatch):
    # C1 2026-10-15: a 246 KB frame sat in the kernel at 16 KB/s; the probe
    # waited behind it and the live socket was torn down as it finished.
    backlog = [246_000]
    monkeypatch.setattr(socket_liveness, 'send_backlog', lambda ws: backlog[0])
    c = client()
    c.send_request('agent.chat', {'image': 'x' * 1000}, lambda value: None, expect_ack=True)
    sent(c)
    socket_liveness.progress(c)
    for _ in range(4):  # 20 s of uploading, no inbound frame at all
        age(c, WS_LIVENESS_PROBE_GRACE)
        backlog[0] -= 80_000
        socket_liveness.progress(c)
        assert not socket_liveness.tick(c)
        sent(c)
    assert not c.aborted.is_set()


def test_a_stuck_send_backlog_is_a_dead_path(monkeypatch):
    monkeypatch.setattr(socket_liveness, 'send_backlog', lambda ws: 246_000)
    c = client()
    c.send_request('agent.chat', {}, lambda value: None, expect_ack=True)
    sent(c)
    socket_liveness.progress(c)
    age(c, WS_ACK_TIMEOUT + 1)
    socket_liveness.tick(c)
    sent(c)
    age(c, WS_LIVENESS_PROBE_GRACE + 1)
    socket_liveness.progress(c)
    assert socket_liveness.tick(c)


def test_the_first_hop_acking_a_keepalive_proves_nothing(monkeypatch):
    # D5 2026-10-15: replies dead; the proxy acked each 88-byte ping, which
    # read as progress and held the probe off for 41 s.
    backlog = [88]
    monkeypatch.setattr(socket_liveness, 'send_backlog', lambda ws: backlog[0])
    c = client()
    c.send_request('agent.chat', {}, lambda value: None, expect_ack=True)
    sent(c)
    socket_liveness.progress(c)
    backlog[0] = 0
    socket_liveness.progress(c)
    assert c._last_send_progress == 0.0
    age(c, WS_ACK_TIMEOUT + 1)
    socket_liveness.tick(c)
    assert c._liveness_probe_why == 'unanswered'


def test_a_large_frame_gets_its_upload_time_before_any_fast_probe():
    # C1 2026-10-15 (second run): a local proxy took the whole frame at once,
    # so the kernel showed no backlog while it crawled out at 16 KB/s.
    c = client()  # no real socket: the backlog is unknown, as behind such a proxy
    size = 160_000
    c.send_request('agent.chat', {'image': 'x' * size}, lambda value: None, expect_ack=True)
    sent(c)
    socket_liveness.progress(c)
    age(c, WS_ACK_TIMEOUT + 1)
    c._send_ping()  # the keepalive queued behind it must not trip either
    sent(c)
    assert not socket_liveness.tick(c) and c._liveness_probe_started is None
    age(c, size / WS_ACK_MIN_UPLINK_BPS)
    socket_liveness.tick(c)
    assert c._liveness_probe_why == 'unanswered'


def test_a_turn_whose_result_is_due_probes_early(monkeypatch):
    # Accepted, then the path died before the result: no command is unanswered.
    monkeypatch.setattr(socket_liveness, 'send_backlog', lambda ws: 0)
    monkeypatch.setitem(turn_events._commands, 'cmd-1', ('session', None))
    c = client()
    socket_liveness.progress(c)
    age(c, WS_ACK_TIMEOUT + 1)
    socket_liveness.tick(c)
    assert c._liveness_probe_why == 'unanswered'
    turn_events._commands.pop('cmd-1')
    c2 = client()  # nothing due: only the idle watchdog applies
    socket_liveness.progress(c2)
    age(c2, WS_ACK_TIMEOUT + 1)
    assert not socket_liveness.tick(c2) and c2._liveness_probe_started is None


def test_writer_declares_a_dead_path_on_time(monkeypatch):
    monkeypatch.setattr(socket_liveness, 'WS_ACK_TIMEOUT', 0.3)
    monkeypatch.setattr(socket_liveness, 'WS_LIVENESS_PROBE_GRACE', 0.3)
    c = client()
    c._running.set()
    frames = []
    c._ws.send = frames.append  # sends "succeed" into a dead path; nothing comes back
    c.send_request('agent.chat', {}, lambda value: None, expect_ack=True)
    stopped, writer = start_writer(c)
    try:
        assert c.aborted.wait(3)
        writer.join(1)
        assert not writer.is_alive()
        assert [json.loads(f)['method'] for f in frames] == ['agent.chat', 'system.ping']
        assert c._diag.current.reason == 'ack_timeout'
    finally:
        stopped.set()
