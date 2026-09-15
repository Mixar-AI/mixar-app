# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Behavioral socket ingress tests: order, replay, teardown and delivery identity."""
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from _open_run_support import _scene, clean_state, live_bpy
from mixar.modules.space_mixie_chat.core import turn_events as events


@pytest.fixture
def env(monkeypatch, live_bpy):
    scene = _scene(session_id='sid')
    scene.mixie_run_open, scene.mixie_run_id = True, 'run'
    live_bpy.data.scenes.append(scene)
    begun, rendered, replay = [], [], []
    monkeypatch.setattr(events, 'arm', lambda: None)
    monkeypatch.setattr(events, '_begin_scene_turn', lambda s, r: begun.append((s.name, r)))
    def apply(scene, turn, payload):
        rendered.append(payload)
        if payload.get('type') == 'turn_end':
            turn.complete = True
    monkeypatch.setattr(events, '_apply', apply)
    def recover(turn):
        turn.recovering = True
        replay.append(turn.cursor)
    monkeypatch.setattr(events, '_request_replay', recover)
    events.bind(scene)
    return SimpleNamespace(scene=scene, begun=begun, rendered=rendered, replay=replay)


def started(tid='turn', sid='sid', run='run', **extra):
    events.handle_turn_notification('agent.turn.started', {
        'session_id': sid, 'turn_id': tid, 'run_id': run, **extra,
    })


def event(seq, payload=None, tid='turn'):
    events.handle_turn_notification('agent.turn.event', {
        'session_id': 'sid', 'turn_id': tid, 'seq': seq,
        'event': payload or {'bubble_id': 'bubble', 'content': {'append': str(seq)}},
    })


def test_all_frames_wait_for_main_thread_and_preserve_order(env):
    started()
    event(0)
    event(1)
    assert env.begun == env.rendered == []
    events._drain()
    assert env.begun == [('Scene', 'run')]
    assert [p['content']['append'] for p in env.rendered] == ['0', '1']


def test_live_frame_arriving_during_drain_cannot_overtake_buffer(env, monkeypatch):
    original = events._apply
    def apply(scene, turn, payload):
        if not env.rendered:
            event(2)
        original(scene, turn, payload)
    monkeypatch.setattr(events, '_apply', apply)
    started()
    event(0)
    event(1)
    events._drain()
    assert [p['content']['append'] for p in env.rendered] == ['0', '1', '2']


def test_abort_before_start_callback_cannot_revive_turn(env):
    started()
    event(0)
    events.drop_scene('Scene')
    events._drain()
    assert env.begun == env.rendered == []


def test_teardown_drops_later_frames(env):
    started()
    event(0)
    events._drain()
    events.drop_scene('Scene')
    event(1)
    events._drain()
    assert len(env.rendered) == 1


def test_sequence_gap_recovers_from_last_rendered_cursor(env):
    started()
    event(0)
    event(2)
    events._drain()
    assert len(env.rendered) == 1
    assert env.replay == [0]
    event(0)  # overlapping replay is ignored
    event(1)
    event(2)
    events._drain()
    assert [p['content']['append'] for p in env.rendered] == ['0', '1', '2']


def test_duplicate_started_does_not_reset_cursor(env):
    started()
    event(0)
    events._drain()
    started(replay=True)
    event(0)
    event(1)
    events._drain()
    assert len(env.begun) == 1
    assert len(env.rendered) == 2


def test_completion_waits_for_missing_tail(env):
    started()
    event(0)
    events.handle_turn_notification('agent.turn.ended', {
        'session_id': 'sid', 'turn_id': 'turn', 'status': 'completed', 'last_seq': 2,
    })
    events._drain()
    assert not events._turns['turn'].complete
    assert env.replay == [0]
    event(2, {'type': 'turn_end', 'status': 'completed'})
    event(1)
    events._drain()
    assert events._turns['turn'].complete
    assert len(env.rendered) == 3


def test_completed_turn_never_reopens_on_duplicate_replay(env):
    started()
    event(0, {'type': 'turn_end', 'status': 'completed'})
    events._drain()
    started(replay=True)
    event(0, {'type': 'turn_end', 'status': 'completed'})
    events._drain()
    assert len(env.begun) == len(env.rendered) == 1


def test_unknown_session_and_turn_dropped(env):
    started(sid='unknown')
    event(0, tid='unknown')
    events._drain()
    assert env.begun == env.rendered == []


def test_unexpected_old_run_start_after_new_send_is_dropped(env):
    events.drop_scene('Scene')
    events.expect(env.scene, 'new-command')
    env.scene.mixie_run_open = False
    started()
    started(tid='new-command', run='')
    events._drain()
    assert env.begun == [('Scene', '')]


def test_replacement_scene_with_same_name_does_not_receive_old_turn(env, live_bpy):
    live_bpy.data.scenes.clear()
    live_bpy.data.scenes.append(_scene(session_id='sid'))
    started()
    events._drain()
    assert env.begun == []


def test_command_results_correlate_by_id_in_any_order(env):
    result = []
    for cid in ('first', 'second'):
        events.expect(env.scene, cid, lambda scene, data: result.append((data['command_id'], data['ok'])))
    for cid, ok in [('second', False), ('first', True)]:
        events.handle_turn_notification('agent.command.result', {'command_id': cid, 'ok': ok})
    events._drain()
    assert result == [('second', False), ('first', True)]


def test_uncertain_ack_keeps_command_identity_for_recovery(env):
    events.expect(env.scene, 'command', lambda *_: None)
    events.handle_turn_notification('agent.command.result', {'command_id': 'command', 'ok': False, 'uncertain': True})
    events._drain()
    assert 'command' in events._commands


def test_bounded_ingress_returns_without_waiting(env, monkeypatch):
    monkeypatch.setattr(events, '_MAX_ITEMS', 2)
    started()
    event(0)
    event(1)
    assert len(events._inbox) == 2
    events._drain()
    assert env.replay == [0]


def test_begin_turn_clears_stale_placeholder(monkeypatch, live_bpy):
    from mixar.modules.space_mixie_chat.core import executor, message_helpers
    monkeypatch.setattr(executor, 'get_executor', lambda: MagicMock())
    monkeypatch.setattr(message_helpers, 'start_loader_animation', lambda: None)
    scene = _scene()
    stale = scene.mixie_chat_messages.add()
    stale.sender, stale.bubble_id = 'AGENT', 'temp_placeholder_old'
    events._begin_scene_turn(scene, 'run')
    assert scene.mixie_run_open and scene.mixie_chat_state == 'BUSY'
    placeholders = [m for m in scene.mixie_chat_messages if m.bubble_id.startswith('temp_placeholder_')]
    assert len(placeholders) == 1 and placeholders[0] is not stale


def test_failed_render_does_not_advance_cursor(env, monkeypatch):
    started()
    event(0)
    events._drain()
    original = events._apply
    monkeypatch.setattr(events, '_apply', lambda *args: (_ for _ in ()).throw(RuntimeError('render failed')))
    event(1)
    events._drain()
    assert events._turns['turn'].cursor == 0
    monkeypatch.setattr(events, '_apply', original)
    event(1)
    events._drain()
    assert events._turns['turn'].cursor == 1
    assert len(env.rendered) == 2


def test_recovery_status_preserves_pending_command_callback(env):
    callback = MagicMock()
    events.expect(env.scene, 'turn', callback)
    events._consume('agent.recovery.status', {'session_id': 'sid', 'info': {
        'turn_id': 'turn', 'run_id': 'run', 'replay_available': True}})
    events._consume('agent.command.result', {'command_id': 'turn', 'ok': True})
    callback.assert_called_once()


@pytest.mark.parametrize('info', [
    {'status': 'unavailable'},
    {'turn_id': 'turn', 'replay_available': False},
    {'turn_id': 'turn', 'replay_available': True},
])
def test_completed_background_delivery_survives_expired_journal(env, monkeypatch, info):
    started()
    event(0, {'type': 'turn_end', 'status': 'in_progress'})
    events._drain()
    unavailable = MagicMock()
    monkeypatch.setattr(events, '_replay_unavailable', unavailable)
    events._consume('agent.recovery.status', {'session_id': 'sid', 'info': info})
    unavailable.assert_not_called()
    assert env.scene.mixie_run_open and env.scene.mixie_run_id == 'run'
    started(tid='wakeup')
    events._drain()
    assert not events._turns['wakeup'].complete


@pytest.mark.parametrize('pending', ['turn', 'command', 'unknown_turn'])
def test_missing_delivery_is_not_hidden_by_open_run(env, monkeypatch, pending):
    started()
    if pending != 'turn':
        event(0, {'type': 'turn_end', 'status': 'in_progress'})
    events._drain()
    if pending == 'command':
        events.expect(env.scene, 'new-command')
    info = {'status': 'unavailable'}
    if pending == 'unknown_turn':
        info['turn_id'] = 'missed-wakeup'
    unavailable = MagicMock()
    monkeypatch.setattr(events, '_replay_unavailable', unavailable)
    events._consume('agent.recovery.status', {'session_id': 'sid', 'info': info})
    unavailable.assert_called_once()


def test_saved_completed_turn_does_not_require_retained_journal(env, monkeypatch):
    monkeypatch.setattr(events.turn_cursor, 'read', lambda *a: {
        'complete': True, 'run_id': 'run', 'run_open': True, 'state': 'IDLE'})
    unavailable = MagicMock()
    monkeypatch.setattr(events, '_replay_unavailable', unavailable)
    events._consume('agent.recovery.status', {'session_id': 'sid', 'info': {
        'turn_id': 'saved', 'replay_available': False}})
    unavailable.assert_not_called()
    assert env.scene.mixie_run_open and env.scene.mixie_chat_state == 'IDLE'
