# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise the dictation worker with controlled auth, sockets and elapsed time."""
import importlib.util
import json
import queue
from pathlib import Path
import sys
import threading
from types import SimpleNamespace, ModuleType
from unittest.mock import Mock

import pytest
import websocket

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def transport_module(monkeypatch):
    path = ROOT / 'src/scripts/mixar/modules/space_mixie_chat/core/voice_input/transport.py'
    package = ModuleType('mixar.modules.space_mixie_chat.core.voice_input')
    package.__path__ = [str(path.parent)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    spec = importlib.util.spec_from_file_location(
        package.__name__ + '._transport_tests', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Socket:
    def __init__(self, cap=180):
        self.events = [json.dumps({'type': 'ready', 'max_duration_seconds': cap}),
                       json.dumps({'type': 'final', 'dictation_id': 'test', 'text': 'Hello'})]
        self.sent = []
        self.closed = False

    def recv(self):
        return self.events.pop(0)

    def send(self, value):
        self.sent.append(value)

    send_binary = send

    def settimeout(self, _):
        pass

    def close(self, **_):
        self.closed = True


def auth(monkeypatch, *, current='old', success=True):
    credentials = {'token': current}
    def refresh():
        if success:
            credentials['token'] = 'fresh'
        return {'success': success}
    module = SimpleNamespace(get_access_token=lambda: credentials['token'],
                             refresh_access_token=Mock(side_effect=refresh))
    monkeypatch.setitem(sys.modules, 'mixar.modules.auth.core.auth', module)
    return module


@pytest.mark.parametrize('status', [401, 403])
def test_auth_rejection_refreshes_once_before_start_or_audio(transport_module, monkeypatch, status):
    module = transport_module
    creds = auth(monkeypatch)
    sock = Socket()
    connect = Mock(side_effect=[websocket.WebSocketBadStatusException('denied', status_code=status), sock])
    monkeypatch.setattr(module.websocket, 'create_connection', connect)
    worker = module.Transport('https://uat1.mixar.app', 'old', 'test')
    worker.feed(b'\x00\x00')
    worker.stop()
    worker.run()
    assert creds.refresh_access_token.call_count == 1
    assert [call.kwargs['header']['Authorization'] for call in connect.call_args_list] == ['Bearer old', 'Bearer fresh']
    assert json.loads(sock.sent[0])['type'] == 'start'
    assert sock.sent[1:] == [b'\x00\x00', '{"type":"stop"}']
    assert [e['type'] for e in list(worker.events.queue)] == ['ready', 'final']
    assert sock.closed and worker.token == ''


@pytest.mark.parametrize('case', ['refresh_denied', 'second_rejected', 'server_error', 'cancelled'])
def test_failed_handshakes_never_replay_or_loop(transport_module, monkeypatch, case):
    module = transport_module
    creds = auth(monkeypatch, success=case != 'refresh_denied')
    failure = websocket.WebSocketBadStatusException('denied', status_code=503 if case == 'server_error' else 403)
    connect = Mock(side_effect=failure)
    monkeypatch.setattr(module.websocket, 'create_connection', connect)
    worker = module.Transport('https://uat1.mixar.app', 'old', 'test')
    if case == 'cancelled':
        worker.cancel()
    worker.run()
    assert connect.call_count == (2 if case == 'second_rejected' else 1)
    assert creds.refresh_access_token.call_count == (0 if case in ('server_error', 'cancelled') else 1)
    assert all(e['type'] == 'error' for e in list(worker.events.queue))
    assert worker.token == ''


def test_concurrent_refresh_reuses_new_stored_token(transport_module, monkeypatch):
    module = transport_module
    creds = auth(monkeypatch, current='already-rotated')
    connect = Mock(side_effect=[websocket.WebSocketBadStatusException('denied', status_code=403), Socket()])
    monkeypatch.setattr(module.websocket, 'create_connection', connect)
    module.Transport('https://uat1.mixar.app', 'old', 'test').run()
    creds.refresh_access_token.assert_not_called()
    assert connect.call_args.kwargs['header']['Authorization'] == 'Bearer already-rotated'


def test_connection_loss_after_ready_does_not_refresh_or_reconnect(transport_module, monkeypatch):
    module = transport_module
    creds = auth(monkeypatch)
    sock = Socket()
    sock.events[1] = ''
    connect = Mock(return_value=sock)
    monkeypatch.setattr(module.websocket, 'create_connection', connect)
    worker = module.Transport('https://uat1.mixar.app', 'old', 'test')
    worker.run()
    assert connect.call_count == 1
    creds.refresh_access_token.assert_not_called()
    assert [e['type'] for e in list(worker.events.queue)] == ['ready', 'error']
    assert sock.closed


@pytest.mark.parametrize('cap', [300, 600])
def test_long_advertised_recording_survives_old_deadline_and_returns_final(transport_module, monkeypatch, cap):
    module = transport_module
    sock = Socket(cap)
    now = [0.0]
    worker = module.Transport('https://uat1.mixar.app', 'old', 'test')
    original = sock.recv
    def recv():
        if now[0] < cap and len(sock.events) == 1:
            now[0] += 50
            if now[0] >= cap:
                worker.stop()
            raise websocket.WebSocketTimeoutException()
        return original()
    sock.recv = recv
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(module.websocket, 'create_connection', Mock(return_value=sock))
    worker.run()
    assert [e['type'] for e in list(worker.events.queue)] == ['ready', 'final']
    assert '{"type":"stop"}' in sock.sent


def test_missing_final_still_times_out_after_stop(transport_module, monkeypatch):
    module = transport_module
    sock = Socket(600)
    now = [0.0]
    original = sock.recv
    def recv():
        if len(sock.events) == 2:
            return original()
        now[0] += 10
        raise websocket.WebSocketTimeoutException()
    sock.recv = recv
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(module.websocket, 'create_connection', Mock(return_value=sock))
    worker = module.Transport('https://uat1.mixar.app', 'old', 'test')
    worker.stop()
    worker.run()
    assert [e['type'] for e in list(worker.events.queue)] == ['ready', 'error']
    assert now[0] == 40 and sock.closed


def test_auth_retry_over_real_local_websocket(transport_module, monkeypatch):
    from http import HTTPStatus
    # Optional test server from the backend environment, not a client dependency.
    serve = pytest.importorskip('websockets.sync.server').serve

    module = transport_module
    creds = auth(monkeypatch)
    authorizations = []
    received = []
    def authorize(connection, request):
        token = request.headers.get('Authorization')
        authorizations.append(token)
        if token != 'Bearer fresh':
            return connection.respond(HTTPStatus.FORBIDDEN, 'Expired access token')

    def handle(connection):
        received.append(json.loads(connection.recv())['type'])
        connection.send(json.dumps({'type': 'ready', 'max_duration_seconds': 180}))
        received.append(connection.recv())
        received.append(json.loads(connection.recv())['type'])
        connection.send(json.dumps({'type': 'final', 'dictation_id': 'test', 'text': 'Hello'}))

    with serve(handle, '127.0.0.1', 0, process_request=authorize) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.socket.getsockname()[1]
            worker = module.Transport(f'http://127.0.0.1:{port}', 'old', 'test')
            worker.feed(b'\x00\x00')
            worker.stop()
            worker.run()
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert authorizations == ['Bearer old', 'Bearer fresh']
    assert received == ['start', b'\x00\x00', 'stop']
    assert [e['type'] for e in list(worker.events.queue)] == ['ready', 'final']
    creds.refresh_access_token.assert_called_once()


def test_coordinator_keeps_capture_after_old_240_second_deadline(monkeypatch):
    path = ROOT / 'src/scripts/mixar/modules/space_mixie_chat/core/voice.py'
    # Isolate the timer from Blender registration, retaining its real lifecycle
    # logic and actual constants. Only capture, context and draft identity vary.
    monkeypatch.setitem(sys.modules,
                        'mixar.modules.space_mixie_chat.core.voice_input.composer',
                        SimpleNamespace(Draft=object))
    spec = importlib.util.spec_from_file_location(
        'mixar.modules.space_mixie_chat.core._voice_timer_tests', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    auth(monkeypatch, current='valid')
    scene = SimpleNamespace(mixie_chat_input='Keep this')
    context = SimpleNamespace(scene=scene, window_manager=SimpleNamespace(
        windows=[SimpleNamespace(as_pointer=lambda: 123)]))
    monkeypatch.setitem(sys.modules, 'bpy', SimpleNamespace(context=context))
    capture = object()
    monkeypatch.setitem(sys.modules, 'aud', SimpleNamespace(
        _mixar_capture_open=lambda: capture, _mixar_capture_read=lambda _: b''))
    now = [10.0]
    module.time = SimpleNamespace(monotonic=lambda: now[0])
    module._identity = lambda _: 'same-chat'
    module._attachments = lambda _: ()
    module._status = Mock()
    module._toast = Mock()
    module._finish = Mock()
    events = queue.Queue()
    events.put({'type': 'ready', 'max_duration_seconds': 600})
    state = SimpleNamespace(scene=scene, window=123, began=0, auth_checked=10,
                            deadline=240, capture=capture, recording_at=10, ready=False,
                            max_seconds=180, state='Listening',
                            draft=SimpleNamespace(base='Keep this', identity='same-chat'),
                            attachments=(), transport=SimpleNamespace(events=events))
    module._session = state
    assert module._tick() == module.VOICE_EVENT_POLL_S
    assert state.capture is capture and state.state == 'Listening'
    now[0] = 310.0
    assert module._tick() == module.VOICE_EVENT_POLL_S
    assert state.capture is capture
    module._finish.assert_not_called()
    module._toast.assert_not_called()


def test_stopped_opening_audio_is_sent_in_order_after_ready(transport_module, monkeypatch):
    module = transport_module
    sock = Socket()
    ready = json.loads(sock.events[0])
    ready['max_startup_buffer_seconds'] = 20
    sock.events[0] = json.dumps(ready)
    worker = module.Transport('https://uat1.mixar.app', 'valid', 'test')
    first = bytes([1, 2]) * 1600
    second = bytes([3, 4]) * 1600
    worker.feed(first)
    worker.feed(second)
    worker.stop()
    monkeypatch.setattr(module.websocket, 'create_connection', Mock(return_value=sock))
    worker.run()
    assert json.loads(sock.sent[0])['buffered_audio_seconds'] == .2
    assert sock.sent[1:] == [first, second, '{"type":"stop"}']
    assert worker.audio.empty()


def test_cancel_before_ready_never_uploads_buffered_audio(transport_module, monkeypatch):
    module = transport_module
    sock = Socket()
    worker = module.Transport('https://uat1.mixar.app', 'valid', 'test')
    worker.feed(bytes(3200))
    recv = sock.recv
    def ready():
        worker.cancel()
        return recv()
    sock.recv = ready
    monkeypatch.setattr(module.websocket, 'create_connection', Mock(return_value=sock))
    worker.run()
    assert not any(isinstance(x, bytes) for x in sock.sent)
    assert worker.audio.empty() and sock.closed


def test_audio_buffer_is_bounded_by_bytes_not_number_of_reads(transport_module):
    buf = transport_module.AudioBuffer(20)
    data = bytes(20 * 32000)
    buf.feed(data)
    with pytest.raises(queue.Full):
        buf.feed(b'\x00\x00')
    assert buf.bytes_pending == len(data)
    received = b''
    while not buf.empty():
        received += buf.get_nowait()
    assert received == data
    buf.feed(b'\x01\x02')
    buf.clear()
    assert buf.empty()
