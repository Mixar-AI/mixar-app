# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The network worker enforces caps before Blender processes Ready."""
import json
from unittest.mock import Mock

import pytest
import websocket

from test_voice_transport import transport_module, Socket  # noqa: F401


@pytest.mark.parametrize('cap', [1, 3])
@pytest.mark.parametrize('already_stopped', [False, True])
def test_buffer_larger_than_ready_cap_sends_exact_prefix_and_stop(transport_module, monkeypatch, cap, already_stopped):
    module = transport_module
    sock = Socket(cap=cap)
    ready = json.loads(sock.events[0])
    ready['max_startup_buffer_seconds'] = 20
    sock.events[0] = json.dumps(ready)
    original_recv, original_send = sock.recv, sock.send
    def recv():
        if len(sock.events) == 1 and '{"type":"stop"}' not in sock.sent:
            raise websocket.WebSocketTimeoutException()
        return original_recv()
    def send(value):
        original_send(value)
        if value == '{"type":"stop"}':
            # The main-thread capture tick may race with the worker's cap.
            worker.feed(bytes(3200))
    sock.recv, sock.send = recv, send
    monkeypatch.setattr(module.websocket, 'create_connection', Mock(return_value=sock))
    worker = module.Transport('https://example.com', 'valid', 'test')
    audio = bytes(range(256)) * (125 * (cap + 1))
    # Deliberately make a frame boundary straddle the byte cap.
    worker.feed(audio[:16002])
    worker.feed(audio[16002:])
    if already_stopped:
        worker.stop()
    worker.run()
    sent = b''.join(x for x in sock.sent if isinstance(x, bytes))
    assert sent == audio[:cap * 32000]
    assert sock.sent[-1] == '{"type":"stop"}'
    assert sock.sent.count('{"type":"stop"}') == 1
    assert worker.audio.empty()
    assert [e['type'] for e in list(worker.events.queue)] == ['ready', 'max_duration_reached', 'final']
