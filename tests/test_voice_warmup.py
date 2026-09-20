# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
import importlib
import json
import sys
import threading
import time
from unittest.mock import Mock

from test_voice_transport import transport_module, Socket  # noqa: F401


def wait_prepared(warm):
    deadline = time.monotonic() + 2
    while warm.socket is None and time.monotonic() < deadline:
        time.sleep(.005)
    assert warm.socket is not None


def load_warmup(module, monkeypatch):
    parent = 'mixar.modules.space_mixie_chat.core.voice_input'
    monkeypatch.setitem(sys.modules, parent + '.transport', module)
    warmup = importlib.import_module(parent + '.warmup')
    warmup.shutdown()
    return warmup


def test_prepared_socket_is_consumed_once_without_second_handshake(transport_module, monkeypatch):
    module = transport_module
    warmup = load_warmup(module, monkeypatch)
    sock = Socket()
    sock.events[:0] = [json.dumps({'type': 'prepared', 'expires_in_seconds': 300}), '{"type":"pong"}']
    connect = Mock(return_value=sock)
    monkeypatch.setattr(module.websocket, 'create_connection', connect)
    warmup.prepare('https://example.com', 'valid')
    warm = warmup._candidate
    wait_prepared(warm)
    assert sock.sent == ['{"type":"prepare","protocol_version":1}']
    worker = module.Transport('https://example.com', 'valid', 'test')
    worker.feed(b'\x01\x02')
    worker.stop()
    worker.run()
    warm.thread.join(2)
    assert not warm.thread.is_alive()
    assert connect.call_count == 1
    assert worker.timings['warm_connection'] is True
    assert b'\x01\x02' in sock.sent and sock.closed
    assert warmup.take('https://example.com', 'valid') is None


def test_cancel_while_prepare_reply_pending_closes_socket(transport_module, monkeypatch):
    module = transport_module
    warmup = load_warmup(module, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    sock = Socket()
    def recv():
        entered.set()
        assert release.wait(2)
        return '{"type":"prepared","expires_in_seconds":300}'
    sock.recv = recv
    monkeypatch.setattr(module.websocket, 'create_connection', Mock(return_value=sock))
    warmup.prepare('https://example.com', 'valid')
    warm = warmup._candidate
    assert entered.wait(2)
    warmup.shutdown()
    release.set()
    warm.thread.join(2)
    assert sock.closed and warm.socket is None


def test_stale_prepared_socket_falls_back_before_start(transport_module, monkeypatch):
    module = transport_module
    warmup = load_warmup(module, monkeypatch)
    old, fresh = Socket(), Socket()
    old.events = ['{"type":"prepared","expires_in_seconds":300}', '']
    connect = Mock(side_effect=[old, fresh])
    monkeypatch.setattr(module.websocket, 'create_connection', connect)
    warmup.prepare('https://example.com', 'valid')
    warm = warmup._candidate
    wait_prepared(warm)
    worker = module.Transport('https://example.com', 'valid', 'test')
    worker.feed(b'\x01\x02')
    worker.stop()
    worker.run()
    warm.thread.join(2)
    assert connect.call_count == 2 and old.closed
    assert not any(isinstance(x, bytes) for x in old.sent)
    assert [x for x in fresh.sent if isinstance(x, bytes)] == [b'\x01\x02']
