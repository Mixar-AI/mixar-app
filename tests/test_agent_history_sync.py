# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Discovery and sync failures use the real client loop without Blender/network."""
import importlib.util
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def module(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/common/agent_history'
    package = types.ModuleType('archive_sync_fixture')
    package.__path__ = [str(root)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    import importlib
    module = importlib.import_module(package.__name__ + '.core.sync')
    monkeypatch.setattr(module.store, 'root', lambda: tmp_path)
    return module


def test_scene_discovery_excludes_workspace_and_invalid_ids(module, monkeypatch):
    normal = types.SimpleNamespace(mixie_session_id='conversation-1')
    scenes = [normal, types.SimpleNamespace(mixie_session_id='agentlane:' + 'a' * 64),
              types.SimpleNamespace(mixie_session_id=''), types.SimpleNamespace(mixie_session_id='../bad')]
    monkeypatch.setitem(sys.modules, 'bpy', types.SimpleNamespace(data=types.SimpleNamespace(scenes=scenes)))
    dispatch = types.SimpleNamespace(run_on_main_thread=lambda callback: callback())
    monkeypatch.setitem(sys.modules, 'mixar.modules.space_mixie_chat.core.main_thread_executor', dispatch)
    get_scene = Mock(return_value='scene-history')
    monkeypatch.setitem(sys.modules, 'mixar.modules.operation_history.core.scene_key',
                        types.SimpleNamespace(get_scene_history_id=get_scene))
    sync = module.ArchiveSync(types.SimpleNamespace())
    assert sync._capture_scene_ids()
    assert sync.scene_ids == {'conversation-1': 'scene-history'}
    get_scene.assert_called_once_with(normal)


def test_capture_scene_ids_returns_false_when_collect_raises(module, monkeypatch):
    scenes = [types.SimpleNamespace(mixie_session_id='conversation-1')]
    monkeypatch.setitem(sys.modules, 'bpy', types.SimpleNamespace(data=types.SimpleNamespace(scenes=scenes)))
    def run_on_main_thread(callback):
        try:  # The real wrapper logs and swallows the callback's exception.
            callback()
        except Exception:
            pass
    dispatch = types.SimpleNamespace(run_on_main_thread=run_on_main_thread)
    monkeypatch.setitem(sys.modules, 'mixar.modules.space_mixie_chat.core.main_thread_executor', dispatch)
    monkeypatch.setitem(sys.modules, 'mixar.modules.operation_history.core.scene_key',
                        types.SimpleNamespace(get_scene_history_id=Mock(side_effect=RuntimeError('boom'))))
    monkeypatch.setattr(module, 'REQUEST_TIMEOUT', 0.5)
    sync = module.ArchiveSync(types.SimpleNamespace())
    sync.scene_ids = {'previous': 'scene-history'}
    started = time.monotonic()
    assert sync._capture_scene_ids() is False
    assert time.monotonic() - started < 0.3
    assert sync.scene_ids == {'previous': 'scene-history'}


def test_capture_scene_ids_stops_waiting_when_stopped(module, monkeypatch):
    dispatch = types.SimpleNamespace(run_on_main_thread=lambda callback: None)
    monkeypatch.setitem(sys.modules, 'mixar.modules.space_mixie_chat.core.main_thread_executor', dispatch)
    monkeypatch.setattr(module, 'REQUEST_TIMEOUT', 5)
    sync = module.ArchiveSync(types.SimpleNamespace())
    sync.stop()
    started = time.monotonic()
    assert sync._capture_scene_ids() is False
    assert time.monotonic() - started < 1.0


def test_warning_explains_protocol_failure_without_disk_advice(module, monkeypatch):
    notifications = Mock()
    monkeypatch.setitem(sys.modules, 'mixar.modules.common.notifications',
        types.SimpleNamespace(get_notification_store=lambda: notifications))
    sync = module.ArchiveSync(types.SimpleNamespace())
    sync._notice('archive_sync_rejected')
    sync._notice('archive_sync_rejected')
    notifications.push.assert_called_once()
    body = notifications.push.call_args.kwargs['body']
    assert 'server rejected' in body and 'disk' not in body and 'missing' not in body


@pytest.mark.parametrize('failure, expected', [
    (OSError(28, 'sensitive local path'), 'archive_disk_full'),
    (PermissionError(13, 'sensitive local path'), 'archive_permission_denied'),
    (ValueError('sensitive payload'), 'archive_validation_failed'),
])
def test_failed_write_is_not_acknowledged_and_recovery_clears_error(module, monkeypatch, failure, expected):
    sent = []
    client = types.SimpleNamespace(is_connected=True)
    sync = module.ArchiveSync(client)
    monkeypatch.setattr(sync, '_capture_scene_ids', lambda: True)
    monkeypatch.setattr(module.store, 'known_sessions', lambda owner: [])
    monkeypatch.setattr(module, 'POLL_SECONDS', 0)
    packet = {'session_id': 'conversation', 'status': 'available'}
    ack = {'session_id': 'conversation', 'epoch': 'a' * 32, 'seq': 1}
    writer = Mock(side_effect=[failure, ack])
    monkeypatch.setattr(module.store, 'write_batch', writer)
    notices = []
    original = sync._notice
    notifications = Mock()
    monkeypatch.setitem(sys.modules, 'mixar.modules.common.notifications',
        types.SimpleNamespace(get_notification_store=lambda: notifications))
    def notice(code):
        notices.append(code)
        original(code)
    monkeypatch.setattr(sync, '_notice', notice)
    def send(method, params, callback, timeout):
        sent.append(params)
        callback({'version': 1, 'owner_id': 'owner', 'sessions': [packet] if len(sent) < 3 else []})
        if len(sent) == 3:
            client.is_connected = False
        return 'request'
    client.send_request = send
    sync._run()
    assert [params['acknowledgements'] for params in sent] == [[], [], [ack]]
    assert notices == [expected] and sync.last_error is None
    assert 'sensitive' not in str(notifications.push.call_args)


def test_transient_failures_log_without_toasting(module, monkeypatch):
    notifications = Mock()
    monkeypatch.setitem(sys.modules, 'mixar.modules.common.notifications',
        types.SimpleNamespace(get_notification_store=lambda: notifications))
    sync = module.ArchiveSync(types.SimpleNamespace())
    sync._notice('archive_sync_timeout')
    sync._notice('archive_sync_unavailable')
    sync._notice('archive_sync_timeout')
    notifications.push.assert_not_called()
    assert sync.last_error == 'archive_sync_timeout'
    sync._notice('archive_disk_full')
    notifications.push.assert_called_once()


def test_slow_reply_is_awaited_not_rerequested(module, monkeypatch):
    """A reply arriving after the old 20s deadline is still consumed and acknowledged."""
    monkeypatch.setattr(module, 'REQUEST_TIMEOUT', 0.2)
    monkeypatch.setattr(module, 'POLL_SECONDS', 0)
    monkeypatch.setattr(module.store, 'known_sessions', lambda owner: [])
    ack = {'session_id': 'conversation', 'epoch': 'a' * 32, 'seq': 1}
    monkeypatch.setattr(module.store, 'write_batch', Mock(return_value=ack))
    sent = []
    client = types.SimpleNamespace(is_connected=True, agent_history_blobs_by_reference=True)
    def send(method, params, callback, timeout):
        sent.append(params)
        assert timeout == module.REPLY_WAIT_SECONDS
        packet = {'session_id': 'conversation', 'status': 'available', 'epoch': 'a' * 32, 'records': []}
        def late():
            time.sleep(1.2)  # well past the former 20s-scaled deadline of 0.2s
            callback({'version': 1, 'owner_id': 'owner', 'sessions': [packet] if len(sent) == 1 else []})
            if len(sent) == 2:
                client.is_connected = False
        threading.Thread(target=late, daemon=True).start()
        return 'request'
    client.send_request = send
    sync = module.ArchiveSync(client)
    monkeypatch.setattr(sync, '_capture_scene_ids', lambda: True)
    sync._run()
    assert [params['acknowledgements'] for params in sent] == [[], [ack]]
    assert all(params['blobs'] == 'reference' for params in sent)
    assert sync.last_error is None


def test_reference_mode_is_only_requested_when_the_server_offers_it(module, monkeypatch):
    monkeypatch.setattr(module, 'POLL_SECONDS', 0)
    monkeypatch.setattr(module.store, 'known_sessions', lambda owner: [])
    sent = []
    client = types.SimpleNamespace(is_connected=True)  # no v2 flag: older backend
    def send(method, params, callback, timeout):
        sent.append(params)
        client.is_connected = False
        callback({'version': 1, 'owner_id': 'owner', 'sessions': []})
        return 'request'
    client.send_request = send
    sync = module.ArchiveSync(client)
    monkeypatch.setattr(sync, '_capture_scene_ids', lambda: True)
    sync._run()
    assert 'blobs' not in sent[0]


def test_disconnect_ends_the_wait_and_drops_the_pending_callback(module, monkeypatch):
    monkeypatch.setattr(module, 'POLL_SECONDS', 0)
    monkeypatch.setattr(module.store, 'known_sessions', lambda owner: [])
    client = types.SimpleNamespace(is_connected=True, _pending_lock=threading.Lock(),
                                   _pending_callbacks={'request': object()}, _pending_deadlines={'request': 1})
    def send(method, params, callback, timeout):
        threading.Timer(0.3, lambda: setattr(client, 'is_connected', False)).start()
        return 'request'
    client.send_request = send
    sync = module.ArchiveSync(client)
    monkeypatch.setattr(sync, '_capture_scene_ids', lambda: True)
    started = time.monotonic()
    sync._run()
    assert time.monotonic() - started < 3
    assert sync.last_error == 'archive_sync_unavailable'
    assert client._pending_callbacks == {} and client._pending_deadlines == {}


def test_unfetchable_blob_is_not_acknowledged(module, monkeypatch):
    monkeypatch.setattr(module, 'POLL_SECONDS', 0)
    monkeypatch.setattr(module.store, 'known_sessions', lambda owner: [])
    writer = Mock(return_value={'session_id': 'conversation', 'epoch': 'a' * 32, 'seq': 1})
    monkeypatch.setattr(module.store, 'write_batch', writer)
    monkeypatch.setattr(module.blobs, 'materialize', Mock(side_effect=module.blobs.BlobUnavailable('archive_blob_hash_mismatch', 0)))
    sent = []
    client = types.SimpleNamespace(is_connected=True, agent_history_blobs_by_reference=True)
    def send(method, params, callback, timeout):
        sent.append(params)
        packet = {'session_id': 'conversation', 'status': 'available', 'epoch': 'a' * 32, 'records': [{}]}
        callback({'version': 1, 'owner_id': 'owner', 'sessions': [packet]})
        if len(sent) == 2:
            client.is_connected = False
        return 'request'
    client.send_request = send
    sync = module.ArchiveSync(client)
    monkeypatch.setattr(sync, '_capture_scene_ids', lambda: True)
    sync._run()
    writer.assert_not_called()
    assert [params['acknowledgements'] for params in sent] == [[], []]
    assert sync.last_error == 'archive_sync_unavailable'


def test_reply_guard_expires_without_disconnect(module, monkeypatch):
    monkeypatch.setattr(module, 'REPLY_WAIT_SECONDS', 1.5)
    monkeypatch.setattr(module, 'POLL_SECONDS', 0)
    monkeypatch.setattr(module.store, 'known_sessions', lambda owner: [])
    sent = []
    client = types.SimpleNamespace(is_connected=True, _pending_lock=threading.Lock(),
                                   _pending_callbacks={}, _pending_deadlines={})
    def send(method, params, callback, timeout):
        sent.append(params)
        if len(sent) == 2:
            client.is_connected = False
        return 'request'  # never answered
    client.send_request = send
    sync = module.ArchiveSync(client)
    monkeypatch.setattr(sync, '_capture_scene_ids', lambda: True)
    monkeypatch.setattr(sync, '_pause', lambda failures: None)
    notices = []
    monkeypatch.setattr(sync, '_notice', lambda code, level=None: notices.append(code))
    started = time.monotonic()
    sync._run()
    assert 1.5 <= time.monotonic() - started < 5
    assert notices[0] == 'archive_sync_timeout'
    assert client._pending_callbacks == {}


def test_v1_backend_packets_are_written_untouched(module, monkeypatch):
    """Without reference mode a payload carrying a `blob` key is ordinary data."""
    monkeypatch.setattr(module, 'POLL_SECONDS', 0)
    monkeypatch.setattr(module.store, 'known_sessions', lambda owner: [])
    monkeypatch.setattr(module.blobs, 'materialize', Mock(side_effect=AssertionError('must not run')))
    written = []
    monkeypatch.setattr(module.store, 'write_batch', lambda owner, packet, scene: written.append(packet) or
                        {'session_id': 'conversation', 'epoch': 'a' * 32, 'seq': 1})
    client = types.SimpleNamespace(is_connected=True)
    record = {'version': 1, 'kind': 'image', 'payload': {'blob': 'opaque'}}
    def send(method, params, callback, timeout):
        client.is_connected = False
        callback({'version': 1, 'owner_id': 'owner', 'sessions': [
            {'session_id': 'conversation', 'status': 'available', 'epoch': 'a' * 32,
             'records': [{'seq': 1, 'event_id': 'x', 'record': record}]}]})
        return 'request'
    client.send_request = send
    sync = module.ArchiveSync(client)
    monkeypatch.setattr(sync, '_capture_scene_ids', lambda: True)
    sync._run()
    assert written[0]['records'][0]['record'] is record and sync.last_error is None


def test_partial_batch_keeps_progress_and_backs_off(module, monkeypatch):
    monkeypatch.setattr(module, 'POLL_SECONDS', 2.0)
    monkeypatch.setattr(module.store, 'known_sessions', lambda owner: [])
    written = []
    def write_batch(owner, packet, scene):
        written.append([r['seq'] for r in packet['records']])
        return {'session_id': 'conversation', 'epoch': 'a' * 32, 'seq': packet['records'][-1]['seq']}
    monkeypatch.setattr(module.store, 'write_batch', write_batch)
    monkeypatch.setattr(module.blobs, 'materialize',
                        Mock(side_effect=module.blobs.BlobUnavailable('archive_blob_hash_mismatch', 2)))
    waits = []
    client = types.SimpleNamespace(is_connected=True, agent_history_blobs_by_reference=True)
    sent = []
    def send(method, params, callback, timeout):
        sent.append(params)
        records = [{'seq': n, 'event_id': 'x', 'record': {}} for n in (1, 2, 3)]
        callback({'version': 1, 'owner_id': 'owner', 'sessions': [
            {'session_id': 'conversation', 'status': 'available', 'epoch': 'a' * 32, 'records': records}]})
        if len(sent) == 3:
            client.is_connected = False
        return 'request'
    client.send_request = send
    sync = module.ArchiveSync(client)
    monkeypatch.setattr(sync, '_capture_scene_ids', lambda: True)
    monkeypatch.setattr(sync.stop_event, 'wait', lambda seconds=None: waits.append(seconds))
    sync._run()
    assert written == [[1, 2], [1, 2], [1, 2]]  # the prefix before the failing record is archived
    assert [a[0]['seq'] for a in (p['acknowledgements'] for p in sent) if a] == [2, 2]
    assert waits == [4.0, 8.0, 16.0]  # doubling from POLL_SECONDS after each failure
    assert sync.last_error == 'archive_sync_unavailable'


def test_stop_during_materialize_skips_the_write(module, monkeypatch):
    monkeypatch.setattr(module.store, 'known_sessions', lambda owner: [])
    writer = Mock()
    monkeypatch.setattr(module.store, 'write_batch', writer)
    client = types.SimpleNamespace(is_connected=True, agent_history_blobs_by_reference=True)
    sync = module.ArchiveSync(client)
    def materialize(packet, should_stop=None, **kw):
        sync.stop()
        raise module.blobs.BlobUnavailable('archive_sync_stopped', 1)
    monkeypatch.setattr(module.blobs, 'materialize', materialize)
    def send(method, params, callback, timeout):
        callback({'version': 1, 'owner_id': 'owner', 'sessions': [
            {'session_id': 'conversation', 'status': 'available', 'epoch': 'a' * 32,
             'records': [{'seq': 1, 'event_id': 'x', 'record': {}}, {'seq': 2, 'event_id': 'y', 'record': {}}]}]})
        return 'request'
    client.send_request = send
    monkeypatch.setattr(sync, '_capture_scene_ids', lambda: True)
    sync._run()
    writer.assert_not_called()
