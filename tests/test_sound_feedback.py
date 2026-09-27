# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transient confirmation never leaves an idle redraw timer behind."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mixar.modules.space_mixie_chat.core import sound_feedback as feedback
from mixar.modules.space_mixie_chat.constants import SOUND_FEEDBACK_TIMING

GROW, HOLD, SHRINK = SOUND_FEEDBACK_TIMING


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
    monkeypatch.setattr(feedback, '_reduce_motion', False)
    monkeypatch.setattr(feedback.time, 'monotonic', lambda: 0.0)
    return timers, active


def test_expand_hold_collapse_then_idle(animation):
    feedback.show()
    assert feedback.expansion(0) == 0
    assert 0 < feedback.expansion(GROW / 2) < 1
    assert feedback.expansion(GROW + HOLD / 2) == 1
    assert 0 < feedback.expansion(GROW + HOLD + SHRINK / 2) < 1
    assert feedback.expansion(GROW + HOLD + SHRINK + .01) == 0


def test_reduce_motion_shows_the_label_for_exactly_the_hold(animation):
    feedback.show(reduce_motion=True)
    assert feedback.expansion(GROW / 2) == 0
    assert feedback.expansion(GROW) == 1
    assert feedback.expansion(GROW + HOLD - .01) == 1
    assert feedback.expansion(GROW + HOLD) == 0
    assert feedback.expansion(GROW + HOLD + SHRINK / 2) == 0
    # The draw site's explicit flag still overrides the one captured by show().
    assert 0 < feedback.expansion(GROW / 2, reduce_motion=False) < 1


def test_reduce_motion_timer_wakes_only_at_the_hold_edges(animation, monkeypatch):
    feedback.show(reduce_motion=True)
    assert feedback._tick() == pytest.approx(GROW)
    monkeypatch.setattr(feedback.time, 'monotonic', lambda: GROW)
    assert feedback._tick() == pytest.approx(HOLD)
    monkeypatch.setattr(feedback.time, 'monotonic', lambda: GROW + HOLD)
    assert feedback._tick() is None
    assert feedback._started is None
    assert feedback.redraw.call_count == 4  # show + one per edge + the final collapse.


def test_tweened_timer_ticks_at_60hz(animation):
    feedback.show()
    assert feedback._tick() == pytest.approx(1 / 60)


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
