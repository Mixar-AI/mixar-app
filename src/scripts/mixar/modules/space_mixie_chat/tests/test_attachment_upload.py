# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Chat images go up over HTTP; the command carries references, not base64."""

import base64
import types
from types import SimpleNamespace

import pytest
from _open_run_support import _scene, clean_state, live_bpy  # noqa: F401 — fixtures
from mixar.modules.space_mixie_chat.core import attachment_upload, turn_events, turn_transport

PNG = base64.b64encode(b'\x89PNG\r\n\x1a\nangel').decode()
JPEG = base64.b64encode(b'\xff\xd8\xffcat').decode()


def _image(b64, mime='image/png', name='angel'):
    block = {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{b64}'}}
    if name:
        block['name'] = name
    return block


@pytest.fixture
def uploads(monkeypatch):
    """Uploads succeed (ids by content) unless ``fail`` is set; the worker
    thread's hand-back runs inline so a test sees the swap at once."""
    state = SimpleNamespace(calls=[], fail=None, supported=True)

    def upload(session_id, mime, b64, name=''):
        state.calls.append((session_id, mime, name))
        if state.fail:
            raise state.fail
        return f'{len(state.calls):016x}'

    class _Thread:
        def __init__(self, target, **kw):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(attachment_upload, 'upload', upload)
    monkeypatch.setattr(attachment_upload.threading, 'Thread', _Thread)
    monkeypatch.setattr('mixar.modules.byok.core.byok_client.schedule_on_main',
                        lambda callback, *args: callback(*args))
    monkeypatch.setattr(attachment_upload, 'server_supports', lambda: state.supported)
    return state


@pytest.fixture
def transport(monkeypatch, live_bpy, uploads):
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


def test_offload_swaps_each_image_for_its_reference_and_uploads_a_repeat_once(uploads):
    payload = {'session_id': 'sid', 'content': [{'type': 'text', 'text': 'hi'}, _image(PNG),
                                                _image(JPEG, 'image/jpeg', name=''), _image(PNG)]}
    done = []
    backup = attachment_upload.offload('chat', payload, lambda: done.append(True))
    assert done == [True]
    assert [c[1] for c in uploads.calls] == ['image/png', 'image/jpeg']  # PNG uploaded once
    refs = payload['content'][1:]
    assert refs[0] == {'type': 'image_ref', 'image_ref': {'id': f'{1:016x}'}, 'name': 'angel'}
    assert refs[1] == {'type': 'image_ref', 'image_ref': {'id': f'{2:016x}'}}
    assert refs[2]['image_ref'] == refs[0]['image_ref']
    assert backup['content'][1] == _image(PNG)  # the inline originals, for a fallback


def test_a_failed_upload_leaves_every_image_inline(uploads):
    uploads.fail = OSError('offline')
    payload = {'session_id': 'sid', 'content': [_image(PNG), _image(JPEG, 'image/jpeg')]}
    done = []
    attachment_upload.offload('chat', payload, lambda: done.append(True))
    assert done == [True]
    assert [b['type'] for b in payload['content']] == ['image_url', 'image_url']


def test_nothing_is_uploaded_without_the_server_capability_or_images(uploads):
    uploads.supported = False
    assert not attachment_upload.wanted('chat', {'content': [_image(PNG)]})
    uploads.supported = True
    assert not attachment_upload.wanted('chat', {'content': [{'type': 'text', 'text': 'x'}]})
    assert not attachment_upload.wanted('chat', {'content': [{'type': 'image_url',
                                                              'image_url': {'url': 'https://x/y.png'}}]})
    assert attachment_upload.wanted('input', {'attachments': [_image(PNG)]})


def test_the_sent_and_held_frame_carries_references(transport):
    scene, calls = transport
    handler = turn_transport.create_turn_handler(scene.name)
    assert handler.start_input_stream('sid', 'submit', text='use this', attachments=[_image(PNG)])
    (method, payload, _ack), kw = calls[0]
    assert method == 'input'
    assert payload['attachments'] == [{'type': 'image_ref', 'image_ref': {'id': f'{1:016x}'},
                                       'name': 'angel'}]
    assert turn_events._outbox[kw['command_id']]['payload'] is payload  # resends carry refs too


def test_attachment_unavailable_resends_the_images_inline_once(transport, uploads):
    scene, calls = transport
    handler = turn_transport.create_turn_handler(scene.name)
    handler.start_input_stream('sid', 'submit', text='use this', attachments=[_image(PNG)])
    first = calls[0][1]['command_id']
    turn_events._consume('agent.command.result', {
        'command_id': first, 'ok': False, 'message': 'Attachment unavailable; send it again',
        'data': {'code': 'attachment_unavailable', 'image_id': f'{1:016x}'}})
    assert len(calls) == 2 and len(uploads.calls) == 1  # no second upload
    (_m, payload, _a), kw = calls[1]
    assert kw['command_id'] != first
    assert payload['attachments'] == [_image(PNG)]
    turn_events._consume('agent.command.result', {
        'command_id': kw['command_id'], 'ok': False,
        'data': {'code': 'attachment_unavailable'}})
    assert len(calls) == 2  # never a second retry


def test_stop_during_the_upload_sends_nothing(transport, monkeypatch):
    scene, calls = transport
    monkeypatch.setattr(turn_events, 'command_pending', lambda command_id: False)
    handler = turn_transport.create_turn_handler(scene.name)
    assert handler.start_input_stream('sid', 'submit', text='x', attachments=[_image(PNG)])
    assert calls == []


def test_the_handshake_flag_follows_the_server_capability():
    from mixar.modules.space_mixie_chat.core.socket_connection import SocketConnection
    for capabilities, expected in ((['agent_attachments_v1'], True), (['agent_history_v2'], False)):
        connection = types.SimpleNamespace()
        SocketConnection._set_server_capabilities(connection, {'server_capabilities': capabilities})
        assert connection.agent_attachments_by_reference is expected
