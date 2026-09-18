# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Archive disk protocol: no Blender import or backend dependencies required."""
import base64
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
import pytest


def encode_record(record):
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return {'id': hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def client_store(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/common/agent_history'
    package = types.ModuleType('archive_client_fixture')
    package.__path__ = [str(root)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    spec = importlib.util.spec_from_file_location(package.__name__ + '.core.store', root / 'core/store.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'root', lambda: tmp_path)
    return module


def packet(seq=1, text='Original script output', epoch='a' * 32):
    record = {'version': 1, 'run_id': 'run', 'task_id': 'worker', 'kind': 'message',
              'payload': {'id': 'message1', 'role': 'tool', 'text': text}}
    encoded = encode_record(record)
    return {'session_id': 'session', 'epoch': epoch, 'status': 'available',
            'records': [{'seq': seq, 'event_id': encoded['id'], 'record': record}]}


def test_fsync_replay_and_bounded_read(client_store):
    p = packet()
    ack = client_store.write_batch('owner', p, 'scene')
    assert ack['seq'] == 1
    assert client_store.write_batch('owner', p, 'scene') == ack
    path = client_store.root() / 'session/events/000001.jsonl'
    assert len(path.read_text().splitlines()) == 1
    manifest = json.loads((path.parents[1] / 'manifest.json').read_text())
    assert manifest['scene_history_id'] == 'scene'
    assert 'Original script output' in client_store.read('owner', 'session', message_id='message1')['records'][0]['text']
    with pytest.raises(ValueError, match='owner'):
        client_store.read('someone_else', 'session')
    with pytest.raises(ValueError):
        client_store.read('owner', '../escape')


def test_torn_tail_and_manifest_lag_recover(client_store):
    p = packet()
    client_store.write_batch('owner', p)
    root = client_store.root() / 'session'
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['cursors'] = {}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with open(root / 'events/000001.jsonl', 'ab') as handle:
        handle.write(b'{"seq":2')
    assert client_store.write_batch('owner', p)['seq'] == 1
    assert len((root / 'events/000001.jsonl').read_text().splitlines()) == 1
    assert client_store.write_batch('owner', packet(2, 'Second'))['seq'] == 2


def test_disk_failure_is_not_acknowledged(client_store, monkeypatch):
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(client_store, '_atomic', fail)
    with pytest.raises(OSError):
        client_store.write_batch('owner', packet())


def test_gap_and_unknown_version_are_explicit(client_store):
    p = packet()
    p['status'] = 'gap'; p['reason'] = 'expired'; p['records'] = []
    client_store.write_batch('owner', p)
    manifest = json.loads((client_store.root() / 'session/manifest.json').read_text())
    assert manifest['gaps'][0]['reason'] == 'expired'
    with pytest.raises(ValueError, match='sequence_gap'):
        client_store.write_batch('owner', packet(3))


def test_separate_image_blob_is_verified(client_store):
    import hashlib
    raw = b'image fixture'
    identifier = hashlib.sha256(raw).hexdigest()[:16]
    p = packet()
    record = p['records'][0]['record']
    record['kind'] = 'image'
    record['payload'] = {'id': identifier, 'mime': 'image/png', 'base64': base64.b64encode(raw).decode()}
    p['records'][0]['event_id'] = encode_record(record)['id']
    client_store.write_batch('owner', p)
    result = client_store.read('owner', 'session', image_id=identifier)
    assert base64.b64decode(result['image']['base64']) == raw
    result = client_store.read('owner', 'session')
    assert 'base64' not in result['records'][0]['text']



def test_conflicting_replay_is_not_acknowledged(client_store):
    client_store.write_batch('owner', packet())
    with pytest.raises(ValueError, match='replay_conflict'):
        client_store.write_batch('owner', packet(text='Different output'))


def test_missing_manifest_fails_closed(client_store):
    client_store.write_batch('owner', packet())
    (client_store.root() / 'session/manifest.json').unlink()
    with pytest.raises(ValueError, match='manifest_missing'):
        client_store.write_batch('different_owner', packet())


def test_rotation_and_multiple_epochs(client_store, monkeypatch):
    monkeypatch.setattr(client_store, 'SEGMENT_BYTES', 1)
    client_store.write_batch('owner', packet())
    client_store.write_batch('owner', packet(2, 'Second'))
    client_store.write_batch('owner', packet(1, 'New epoch', epoch='b' * 32))
    manifest = json.loads((client_store.root() / 'session/manifest.json').read_text())
    assert manifest['cursors'] == {'a' * 32: 2, 'b' * 32: 1}
    assert manifest['gaps'][0]['reason'] == 'delivery_epoch_changed'
    assert len(list((client_store.root() / 'session/events').glob('*.jsonl'))) == 3


def test_failed_final_manifest_write_recovers(client_store, monkeypatch):
    client_store.write_batch('owner', packet())
    atomic = client_store._atomic
    def fail_manifest(path, raw):
        if path.name == 'manifest.json':
            raise OSError('disk full')
        atomic(path, raw)
    monkeypatch.setattr(client_store, '_atomic', fail_manifest)
    with pytest.raises(OSError):
        client_store.write_batch('owner', packet(2, 'Second'))
    monkeypatch.setattr(client_store, '_atomic', atomic)
    assert client_store.write_batch('owner', packet(2, 'Second'))['seq'] == 2
    assert len((client_store.root() / 'session/events/000001.jsonl').read_text().splitlines()) == 2


def test_discovery_is_owner_scoped(client_store):
    client_store.write_batch('owner', packet())
    assert client_store.known_sessions('owner') == ['session']
    assert client_store.known_sessions('someone_else') == []


def test_socket_archive_negotiation_and_dispatch_contract():
    core = Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/space_mixie_chat/core'
    connection = (core / 'socket_connection.py').read_text()
    dispatch = (core / 'socket_dispatch.py').read_text()
    assert '"agent_history_v1"' in connection
    assert '"agent_history_v2"' in connection
    assert 'if self.agent_history_supported:' in connection
    assert 'result_sink=self._set_server_capabilities' in connection
    assert "if method == 'agent.history_read':" in dispatch


HANDSHAKE_RESULT = {
    "success": True, "server_version": "x", "connection_id": "c", "supported_methods": [],
    "server_capabilities": ["bidirectional_rpc", "batch_requests", "notifications", "scene_caching", "agent_history_v1", "agent_history_v2"],
    "agent_ws_v1": {"max_message_bytes": 33554432, "replay": True},
}


@pytest.mark.parametrize('result, history, reference, ws', [
    (HANDSHAKE_RESULT, True, True, True),
    ({**HANDSHAKE_RESULT, 'server_capabilities': ['bidirectional_rpc', 'agent_history_v1']}, True, False, True),
    ({**HANDSHAKE_RESULT, 'server_capabilities': ['bidirectional_rpc']}, False, False, True),
    ({'success': True}, False, False, False),
])
def test_handshake_server_capabilities_list_negotiates_archive(result, history, reference, ws):
    # The backend handshake reply carries server_capabilities as a flat list of strings.
    from mixar.modules.space_mixie_chat.core.socket_connection import SocketConnection
    connection = types.SimpleNamespace()
    SocketConnection._set_server_capabilities(connection, result)
    assert connection.agent_history_supported is history
    assert connection.agent_history_blobs_by_reference is reference
    assert connection.agent_ws_supported is ws
