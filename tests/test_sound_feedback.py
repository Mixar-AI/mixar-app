# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Transient confirmation never leaves an idle redraw timer behind."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mixar.modules.space_mixie_chat.core import sound_feedback as feedback
from mixar.modules.space_mixie_chat.constants import SOUND_FEEDBACK_TIMING


@pytest.fixture
def animation(monkeypatch):
    active = set()
    timers = SimpleNamespace(
        is_registered=lambda fn: fn in active,
        register=Mock(side_effect=lambda fn, **kw: active.add(fn)),
        unregister=Mock(side_effect=active.remove),
    )
    monkeypatch.setattr(feedback, 'bpy', SimpleNamespace(app=SimpleNamespace(timers=timers)))
    monkeypatch.setattr(feedback, 'redraw', Mock())
    monkeypatch.setattr(feedback, '_started', None)
    monkeypatch.setattr(feedback.time, 'monotonic', lambda: 10.0)
    return timers, active


def test_expand_hold_collapse_then_idle(animation):
    feedback.show()
    grow, hold, shrink = SOUND_FEEDBACK_TIMING
    assert feedback.expansion(10) == 0
    assert 0 < feedback.expansion(10 + grow / 2) < 1
    assert feedback.expansion(10 + grow + hold / 2) == 1
    assert 0 < feedback.expansion(10 + grow + hold + shrink / 2) < 1
    assert feedback.expansion(10 + grow + hold + shrink + .01) == 0


def test_reduce_motion_has_confirmation_without_tween(animation):
    feedback.show()
    assert feedback.expansion(10.01, reduce_motion=True) == 1
    assert feedback.expansion(10 + sum(SOUND_FEEDBACK_TIMING) + .01,
                              reduce_motion=True) == 0


def test_repeated_enable_uses_one_timer_and_mute_cancels(animation):
    timers, active = animation
    feedback.show()
    feedback.show()
    assert timers.register.call_count == 1
    feedback.cancel()
    assert not active
    assert feedback.expansion() == 0
    assert feedback._tick() is None
    feedback.cancel()  # Idempotent during unregister/reload.
    assert timers.unregister.call_count == 1


def test_expiry_redraws_collapsed_state_and_stops_timer(animation, monkeypatch):
    feedback.show()
    monkeypatch.setattr(feedback.time, 'monotonic', lambda: 20.0)
    assert feedback._tick() is None
    assert feedback._started is None
    assert feedback.expansion() == 0
    assert feedback.redraw.call_count == 2
