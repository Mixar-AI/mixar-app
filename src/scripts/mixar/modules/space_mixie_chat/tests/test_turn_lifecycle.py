# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Delivery teardown and History reactivation regressions from PR #1485."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from _open_run_support import _scene, clean_state, live_bpy
from mixar.modules.space_mixie_chat.core import turn_events as events
from mixar.modules.space_mixie_chat.core import turn_transport as transport


@pytest.fixture
def timers(monkeypatch, live_bpy):
    registered = set()
    timer = SimpleNamespace(
        is_registered=lambda fn: fn in registered,
        register=lambda fn, **kw: registered.add(fn),
        unregister=lambda fn: registered.remove(fn),
    )
    monkeypatch.setattr(live_bpy.app, 'timers', timer)
    yield registered
    transport._handlers.clear()


def test_atexit_cleanup_never_accesses_bpy(monkeypatch):
    class FreedBlender:
        def __getattr__(self, name):
            raise AssertionError(f'bpy.{name} accessed after Blender shutdown')
    handler = transport.create_turn_handler('Deleted scene')
    handler._running = True
    events._turns['turn'] = events.Turn('sid', 'turn', 'run')
    events.handle_turn_notification('agent.turn.started', {'session_id': 'sid'})
    monkeypatch.setitem(sys.modules, 'bpy', FreedBlender())
    transport.cleanup_all_turn_handlers(app_exit=True)
    assert not handler._running
    assert not transport._handlers and not events._turns and not events._inbox


@pytest.mark.parametrize('cleanup_name', ['handlers', 'queue'])
def test_cleanup_unregisters_timer_and_can_rearm(timers, cleanup_name):
    from mixar.modules.space_mixie_chat.core.queue_processor import cleanup_event_queue
    cleanup = transport.cleanup_all_turn_handlers if cleanup_name == 'handlers' else cleanup_event_queue
    events.arm()
    events.arm()
    assert timers == {events._drain}
    events.handle_turn_notification('agent.turn.started', {'session_id': 'sid'})
    cleanup()
    cleanup()  # Properties and global shutdown can both call teardown.
    assert not timers and not events._inbox
    events.arm()
    assert timers == {events._drain}


def test_history_reopen_allows_prompt_and_replay_without_sending(monkeypatch, live_bpy, timers):
    from mixar.modules.space_mixie_chat.core import jsonrpc_client, turn_resume
    scene = _scene(session_id='history')
    live_bpy.data.scenes.append(scene)
    events.bind(scene)
    events._turns['old-turn'] = events.Turn('history', 'old-turn', 'run', cursor=2)
    events.drop_scene(scene.name)
    scene.mixie_session_id = 'other'
    events._turns['other-turn'] = events.Turn('other', 'other-turn', 'other-run')
    events.drop_scene(scene.name)
    # A queued status from the prior visit must not bypass the resume choice.
    events.handle_turn_notification('agent.recovery.status', {'session_id': 'history'})
    scene.mixie_session_id = 'history'
    events.reopen(scene)
    assert events._blocked == {'other'}
    assert 'old-turn' not in events._turns and 'other-turn' in events._turns
    assert not events._inbox and events._inbox_bytes == 0
    requests = []
    monkeypatch.setattr(turn_resume, 'bpy', live_bpy)
    monkeypatch.setattr(jsonrpc_client, 'get_jsonrpc_client', lambda: SimpleNamespace(
        send_request=lambda *args: requests.append(args)))
    turn_resume.check_orphaned_turns()
    assert requests[0][:2] == ('agent.status', {'session_ids': ['history']})
    begun, replay = [], []
    monkeypatch.setattr(events, '_begin_scene_turn', lambda *args: begun.append(args))
    monkeypatch.setattr(events, '_request_replay', lambda turn: replay.append(turn.turn_id))
    events._consume('agent.recovery.status', {'session_id': 'history', 'info': {
        'turn_id': 'old-turn', 'run_id': 'run', 'replay_available': True}})
    assert begun and replay == ['old-turn']


def test_late_resume_prompt_cannot_land_in_a_different_chat():
    from mixar.modules.space_mixie_chat.core.turn_resume import offer_resume_prompt
    scene = _scene(session_id='new-chat')
    scene.mixie_chat_messages = MagicMock()
    offer_resume_prompt(scene, 'old-chat', {'status': 'running'})
    scene.mixie_chat_messages.add.assert_not_called()
