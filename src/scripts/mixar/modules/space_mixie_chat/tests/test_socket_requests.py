# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Requests remain bounded and replies keep flowing during large writes."""
import threading
from queue import Full

import pytest
from mixar.modules.space_mixie_chat.core.jsonrpc_client import JSONRPCWebSocketClient
from mixar.modules.space_mixie_chat.core.socket_writer import start_writer
from mixar.modules.space_mixie_chat.core.question_ref import pending_interrupt_id
from types import SimpleNamespace


def client():
    return JSONRPCWebSocketClient('http://unused', 'test')


def test_timeout_and_late_response_invoke_callback_once():
    socket = client()
    values = []
    rid = socket.send_request('agent.chat', {}, values.append, timeout=-1)
    socket._expire_pending()
    socket._handle_message({'jsonrpc':'2.0', 'id':rid, 'result':{'accepted':True}})
    assert len(values) == 1 and values[0]['data']['uncertain']
    assert not socket._pending_callbacks and not socket._pending_deadlines


def test_full_outbound_queue_rejects_without_leaking_callback():
    socket = client()
    for _ in range(128):
        socket.send_request('system.ping', {})
    with pytest.raises(Full):
        socket.send_request('agent.chat', {}, lambda value: None)
    assert not socket._pending_callbacks


def test_response_routing_does_not_wait_for_a_blocked_send():
    socket = client()
    entered, release = threading.Event(), threading.Event()
    def send(frame):
        entered.set()
        assert release.wait(2)
    socket._ws = SimpleNamespace(send=send, close=lambda: None)
    socket._running.set()
    values = []
    rid = socket.send_request('agent.chat', {}, values.append)
    stopped, writer = start_writer(socket)
    try:
        assert entered.wait(1)
        socket._handle_message({'jsonrpc':'2.0', 'id':rid, 'result':{'accepted':True}})
        assert values == [{'accepted':True}]
    finally:
        stopped.set()
        release.set()
        writer.join(1)


def test_typed_answer_addresses_latest_pending_interrupt():
    scene = SimpleNamespace(mixie_chat_messages=[
        SimpleNamespace(sender='AGENT', input_type='choice', interrupt_id='older'),
        SimpleNamespace(sender='AGENT', input_type='', interrupt_id='answered'),
        SimpleNamespace(sender='AGENT', input_type='text', interrupt_id='latest'),
        SimpleNamespace(sender='USER', input_type='', interrupt_id=''),
    ])
    assert pending_interrupt_id(scene) == 'latest'


def test_queue_byte_limit_counts_utf8_and_releases_after_dequeue():
    from mixar.modules.space_mixie_chat.core.socket_queue import SocketQueue
    queue = SocketQueue(maxsize=10, maxbytes=6)
    queue.put_nowait('éé')
    with pytest.raises(Full):
        queue.put_nowait('abc')
    assert queue.queued_bytes == 4
    assert queue.get_nowait() == 'éé'
    queue.put_nowait('abc')
    assert queue.queued_bytes == 3
