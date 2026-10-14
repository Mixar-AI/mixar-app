# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Model changes must settle before a send; stale reads cannot undo a write."""
from types import SimpleNamespace

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import bpy
import pytest

from mixar.modules.byok.core import preference_client as client, preference_state as state
from mixar.modules.byok.ui.operators import agent_model_ops as ops
from mixar.modules.space_mixie_chat.core import composer_send


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    state.clear()
    monkeypatch.setattr(state, '_redraw', lambda: None)
    monkeypatch.setattr(ops, '_redraw', lambda: None)
    monkeypatch.setattr(ops, '_notify_failure', lambda *args: None)
    yield
    state.clear()


@pytest.fixture
def transport(monkeypatch):
    import bpy  # Other suites may replace the module during collection.
    requests = SimpleNamespace(saves=[], deletes=[], gets=[], timers=[])
    monkeypatch.setattr(client, 'save_preference', lambda **kw: requests.saves.append(kw))
    monkeypatch.setattr(client, 'delete_preference', lambda **kw: requests.deletes.append(kw))
    monkeypatch.setattr(client, 'fetch_preference', lambda **kw: requests.gets.append(kw))
    monkeypatch.setattr(bpy.app.timers, 'register',
                        lambda cb, **kw: requests.timers.append(cb))
    return requests


def pick(model):
    op = ops.MIXAR_OT_agent_model_set()
    op.provider, op.model, op.label, op.thinking_level = 'openai', model, model, ''
    op.report = lambda *args: None
    return op.execute(SimpleNamespace(window_manager=SimpleNamespace()))


def payload(model):
    return {'items': [{'role': 'default', 'provider': 'openai', 'model': model}],
            'byok_active': False}


def test_only_one_write_can_run_and_failure_restores_confirmed_pick(transport):
    state.apply_from_payload(payload('original'))
    assert pick('A') == {'FINISHED'}
    assert pick('B') == {'CANCELLED'}
    reset = ops.MIXAR_OT_agent_model_reset()
    reset.report = lambda *args: None
    assert reset.execute(SimpleNamespace(window_manager=None)) == {'CANCELLED'}
    assert len(transport.saves) == 1 and not transport.deletes
    transport.saves[0]['on_done'](False, None, 'rejected A')
    assert state.snapshot()['mixar_agent_model_id'] == 'original'
    assert not state.mutation_pending()
    assert pick('B') == {'FINISHED'}
    transport.saves[1]['on_done'](False, None, 'rejected B')
    assert state.snapshot()['mixar_agent_model_id'] == 'original'


def test_pending_change_blocks_send_before_any_transport_work(transport, monkeypatch):
    assert pick('A') == {'FINISHED'}
    scene = SimpleNamespace(mixie_chat_mode='AGENT', mixie_chat_input='keep my draft')
    monkeypatch.setattr(composer_send, 'get_session_manager',
                        lambda: pytest.fail('send crossed pending-model barrier'))
    allowed, reason = composer_send.can_send(scene)
    assert not allowed and 'Saving agent model' in reason
    assert scene.mixie_chat_input == 'keep my draft'
    # Actual backend PUT response is a single view, not a GET envelope.
    transport.saves[0]['on_done'](True, payload('A')['items'][0], None)
    assert not composer_send.model_change_pending(scene)
    assert state.snapshot()['mixar_agent_model_id'] == 'A'


def test_generate_and_library_do_not_wait_for_agent_model(transport):
    pick('A')
    for mode in ('GENERATE', 'LIBRARY'):
        assert not composer_send.model_change_pending(SimpleNamespace(mixie_chat_mode=mode))


def test_get_started_before_write_cannot_overwrite_confirmed_model(transport):
    state.refresh()
    old_get = transport.gets[0]['on_done']
    pick('B')
    state.refresh()  # no reads during the write
    assert len(transport.gets) == 1
    transport.saves[0]['on_done'](True, payload('B')['items'][0], None)
    old_get(True, payload('original'), None)
    assert state.snapshot()['mixar_agent_model_id'] == 'B'


def test_only_latest_read_can_change_byok_state(transport):
    state.refresh()
    state.refresh()
    transport.gets[1]['on_done'](True, payload('B'), None)
    transport.gets[0]['on_done'](True, dict(payload('original'), byok_active=True), None)
    assert state.snapshot()['mixar_agent_model_id'] == 'B'
    assert not state.snapshot()['mixar_agent_model_byok_active']


def test_failed_byok_refresh_retries_without_catalog_change(transport):
    state.apply_from_payload({'items': [], 'byok_active': True})
    state.refresh()
    transport.gets[0]['on_done'](False, None, 'temporary network failure')
    assert state.snapshot()['mixar_agent_model_byok_active']
    assert len(transport.timers) == 1
    transport.timers[0]()
    assert len(transport.gets) == 2
    transport.gets[1]['on_done'](True, {'items': [], 'byok_active': False}, None)
    assert not state.snapshot()['mixar_agent_model_byok_active']


@pytest.mark.parametrize('invalidate', ['logout', 'new_read', 'write'])
def test_new_work_cancels_old_retry(transport, invalidate):
    state.refresh()
    transport.gets[0]['on_done'](False, None, 'offline')
    if invalidate == 'logout':
        state.clear()
    elif invalidate == 'new_read':
        state.refresh()
    else:
        pick('B')
    count = len(transport.gets)
    transport.timers[0]()
    assert len(transport.gets) == count


def test_old_account_completion_cannot_unlock_new_account_write(transport):
    pick('A')
    state.clear()
    pick('B')
    transport.saves[0]['on_done'](True, payload('A')['items'][0], None)
    assert state.mutation_pending()
    assert state.snapshot()['mixar_agent_model_id'] == 'B'
    assert not transport.gets


def test_reset_blocks_send_until_delete_ack(transport):
    state.apply_from_payload(payload('A'))
    op = ops.MIXAR_OT_agent_model_reset()
    op.report = lambda *args: None
    assert op.execute(SimpleNamespace(window_manager=None)) == {'FINISHED'}
    assert state.mutation_pending()
    transport.deletes[0]['on_done'](False, None, 'rejected')
    assert not state.mutation_pending()
    assert state.snapshot()['mixar_agent_model_id'] == 'A'
