# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""A refused deferred retry keeps its action and can be clicked again."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from mixar.modules.space_mixie_chat.core import retry_action as retry


@pytest.fixture
def fixture(monkeypatch):
    action = SimpleNamespace(value='retry_failed_tasks')
    message = SimpleNamespace(bubble_id='retry', action_items=[action])
    scene = SimpleNamespace(session_uid=42, mixie_session_id='session',
                            mixie_chat_messages=[message])
    timers, notices, calls = [], [], []
    monkeypatch.setattr(retry, 'bpy', SimpleNamespace(
        data=SimpleNamespace(scenes=[scene]),
        context=SimpleNamespace(temp_override=lambda **kw: nullcontext()),
        app=SimpleNamespace(timers=SimpleNamespace(
            register=lambda fn, **kw: timers.append(fn)))))
    monkeypatch.setattr(retry, '_notify_failure', lambda sc: notices.append((sc, retry.FAILURE_MESSAGE)))
    monkeypatch.setattr(retry, 'redraw_chat_areas', lambda: None)
    monkeypatch.setattr(retry.parked_resume, 'send_continue', lambda sc: calls.append(sc) or True)
    retry._pending.clear()
    yield SimpleNamespace(scene=scene, message=message, timers=timers, notices=notices, calls=calls)
    retry._pending.clear()


def test_success_is_deferred_and_duplicate_clicks_send_once(fixture):
    f = fixture
    retry.schedule_retry(f.scene, 'retry')
    retry.schedule_retry(f.scene, 'retry')
    assert f.message.action_items and not f.calls
    assert len(f.timers) == 1
    assert f.timers.pop()() is None
    assert f.calls == [f.scene]
    assert not f.message.action_items and not f.notices and not retry._pending


def test_refusal_keeps_chip_shows_notice_and_allows_successful_retry(fixture, monkeypatch):
    f = fixture
    monkeypatch.setattr(retry.parked_resume, 'send_continue', lambda sc: False)
    retry.schedule_retry(f.scene, 'retry')
    assert f.timers.pop()() is None
    assert f.message.action_items
    assert f.notices == [(f.scene, retry.FAILURE_MESSAGE)]
    assert not retry._pending
    monkeypatch.setattr(retry.parked_resume, 'send_continue', lambda sc: True)
    retry.schedule_retry(f.scene, 'retry')
    f.timers.pop()()
    assert not f.message.action_items


@pytest.mark.parametrize('change', ['scene', 'session', 'message', 'action'])
def test_stale_timer_does_not_send_into_a_different_conversation(fixture, change):
    f = fixture
    retry.schedule_retry(f.scene, 'retry')
    if change == 'scene':
        retry.bpy.data.scenes.clear()
    elif change == 'session':
        f.scene.mixie_session_id = 'different'
    elif change == 'message':
        f.scene.mixie_chat_messages.clear()
    else:
        f.message.action_items.clear()
    f.timers.pop()()
    assert not f.calls and not f.notices and not retry._pending
