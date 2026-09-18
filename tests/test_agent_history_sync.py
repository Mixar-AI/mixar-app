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
