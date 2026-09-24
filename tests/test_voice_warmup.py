# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
import importlib
import base64
import json
import sys
import threading
import time
from unittest.mock import Mock
from types import SimpleNamespace
import pytest

from test_voice_transport import transport_module, Socket, auth  # noqa: F401


def token(expiry):
    payload = base64.urlsafe_b64encode(json.dumps({'exp': expiry}).encode()).decode().rstrip('=')
    return 'header.' + payload + '.signature'


VALID = token(time.time() + 3600)


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
    warmup.prepare('https://example.com', VALID)
    warm = warmup._candidate
    wait_prepared(warm)
    assert sock.sent == ['{"type":"prepare","protocol_version":1}']
    worker = module.Transport('https://example.com', VALID, 'test')
    worker.feed(b'\x01\x02')
    worker.stop()
    worker.run()
    warm.thread.join(2)
    assert not warm.thread.is_alive()
    assert connect.call_count == 1
    assert worker.timings['warm_connection'] is True
    assert b'\x01\x02' in sock.sent and sock.closed
    assert warmup.take('https://example.com', VALID) is None


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
    warmup.prepare('https://example.com', VALID)
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
    warmup.prepare('https://example.com', VALID)
    warm = warmup._candidate
    wait_prepared(warm)
    worker = module.Transport('https://example.com', VALID, 'test')
    worker.feed(b'\x01\x02')
    worker.stop()
    worker.run()
    warm.thread.join(2)
    assert connect.call_count == 2 and old.closed
    assert not any(isinstance(x, bytes) for x in old.sent)
    assert [x for x in fresh.sent if isinstance(x, bytes)] == [b'\x01\x02']


@pytest.mark.parametrize('advance', [100, 121])
def test_expiring_prepared_token_refreshes_before_start_without_losing_audio(transport_module, monkeypatch, advance):
    module = transport_module
    warmup = load_warmup(module, monkeypatch)
    lifetime = importlib.import_module(warmup.__package__ + '.token_lifetime')
    now = [1000.0]
    monkeypatch.setattr(lifetime, 'time', SimpleNamespace(time=lambda: now[0]))
    original_token = token(1120)
    creds = auth(monkeypatch, current=original_token)
    old, fresh = Socket(), Socket()
    old.events = ['{"type":"prepared","expires_in_seconds":300}']
    connect = Mock(side_effect=[old, fresh])
    monkeypatch.setattr(module.websocket, 'create_connection', connect)
    warmup.prepare('https://example.com', original_token)
    warm = warmup._candidate
    wait_prepared(warm)
    assert warm.expires - time.monotonic() <= 90
    now[0] += advance
    worker = module.Transport('https://example.com', original_token, 'test')
    worker.feed(bytes(32000))
    worker.stop()
    worker.run()
    warm.thread.join(2)
    creds.refresh_access_token.assert_called_once()
    assert connect.call_args.kwargs['header']['Authorization'] == 'Bearer fresh'
    assert old.sent == ['{"type":"prepare","protocol_version":1}'] and old.closed
    assert b''.join(x for x in fresh.sent if isinstance(x, bytes)) == bytes(32000)
    assert [e['type'] for e in list(worker.events.queue)] == ['ready', 'final']


def test_prepared_identity_uses_token_rotated_during_handshake(transport_module, monkeypatch):
    module = transport_module
    warmup = load_warmup(module, monkeypatch)
    rotated = token(time.time() + 7200)
    sock = Socket()
    sock.events = ['{"type":"prepared","expires_in_seconds":300}', '{"type":"pong"}']
    def connect(opener):
        opener.token = rotated
        return sock
    monkeypatch.setattr(module.Transport, '_connect', connect)
    warmup.prepare('https://example.com', VALID)
    warm = warmup._candidate
    wait_prepared(warm)
    assert warmup.take('https://example.com', rotated) is sock
    warm.thread.join(2)
    sock.close()


@pytest.mark.parametrize('value', ['opaque', token(True), token('123'), token(float('inf')), token(None)])
def test_unknown_expiry_is_not_usable_for_preparation(value):
    from mixar.modules.space_mixie_chat.core.voice_input.token_lifetime import remaining
    assert remaining(value) is None


def test_expiry_during_takeover_ping_does_not_transfer_socket(transport_module, monkeypatch):
    module = transport_module
    warmup = load_warmup(module, monkeypatch)
    sock = Socket()
    sock.events = ['{"type":"prepared","expires_in_seconds":300}', '{"type":"pong"}']
    monkeypatch.setattr(module.websocket, 'create_connection', Mock(return_value=sock))
    warmup.prepare('https://example.com', VALID)
    warm = warmup._candidate
    wait_prepared(warm)
    monkeypatch.setattr(warmup, 'remaining', Mock(side_effect=[31, 29]))
    assert warmup.take('https://example.com', VALID) is None
    warm.thread.join(2)
    assert sock.closed and not warm.transferred


def test_proactive_refresh_rejection_does_not_refresh_twice(transport_module, monkeypatch):
    import websocket
    module = transport_module
    old = token(time.time() - 1)
    creds = auth(monkeypatch, current=old)
    connect = Mock(side_effect=websocket.WebSocketBadStatusException('denied', status_code=403))
    monkeypatch.setattr(module.websocket, 'create_connection', connect)
    worker = module.Transport('https://example.com', old, 'test')
    worker.run()
    creds.refresh_access_token.assert_called_once()
    assert connect.call_count == 1
    assert [e['type'] for e in list(worker.events.queue)] == ['error']
