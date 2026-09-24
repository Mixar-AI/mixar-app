# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later


"""The interactive tour's beat state machine (``runner.TourRunner``):
start, ticking, clock jumps, gates and user pause.

``test_tour_runner_flow.py`` covers skip, the terminal beat, ``state()``,
skip ranges and the ``MIXAR_INTRO`` end-to-end runs. The doubles live in
``tour_doubles.py``.
"""

from __future__ import annotations

import pytest

from mixar.modules.onboarding.core.tour.beats import Beat, Gate, Tour
from mixar.modules.onboarding.core.tour.runner import (
    STATUS_GATED,
    STATUS_IDLE,
    STATUS_RUNNING,
)
from tour_doubles import GATE_WALL_MS, LINEAR, TOUR, Harness


@pytest.fixture
def h():
    return Harness()


# ---------------------------------------------------------------------------
# start / basic ticking
# ---------------------------------------------------------------------------

def test_idle_until_started(h):
    assert h.runner.status == STATUS_IDLE
    assert h.runner.beat is None
    h.runner.tick()
    assert h.runner.index == -1 and h.actions == [] and h.clock.calls == []


def test_start_seeks_zero_resumes_and_enters_first_beat(h):
    h.runner.start()
    assert h.clock.calls[:2] == [("seek", 0), ("resume",)]
    assert h.runner.status == STATUS_RUNNING
    assert h.runner.index == 0 and h.runner.beat.id == "a"
    # Only the action pinned at enter_ms has fired, exactly once.
    assert h.actions == [("a0", {})]


def test_actions_fire_once_across_repeated_ticks(h):
    h.runner.start()
    for _ in range(5):
        h.runner.tick()
    assert h.names == ["a0"]
    h.clock.step(999)
    h.runner.tick()
    assert h.names == ["a0"]              # a1 is at 1000, not yet due
    h.clock.step(1)
    for _ in range(5):
        h.runner.tick()
    assert h.actions == [("a0", {}), ("a1", {"k": 1})]


def test_action_args_are_copied(h):
    h.runner.start()
    h.actions[0][1]["mutated"] = True
    assert TOUR.beats[0].actions[0][2] == {}


def test_clock_jump_fires_every_skipped_beats_actions_in_order():
    hh = Harness(LINEAR)
    hh.runner.start()
    assert hh.names == ["a0"]
    # Jump straight from beat "a" to the middle of "d": "a1", "b0", "b1",
    # "c0" and "d0" all belong to beats the clock passed over; "d1" is not
    # due yet.
    hh.clock.pos = 6500
    hh.runner.tick()
    assert hh.names == ["a0", "a1", "b0", "b1", "c0", "d0"]
    assert hh.runner.beat.id == "d" and hh.runner.index == 3
    assert hh.runner.status == STATUS_RUNNING
    for _ in range(3):
        hh.runner.tick()
    assert hh.names == ["a0", "a1", "b0", "b1", "c0", "d0"]   # still once
    hh.clock.pos = 7500
    hh.runner.tick()
    assert hh.names[-1] == "d1" and hh.names.count("d1") == 1


def test_clock_jump_past_a_gated_beats_end_still_gates(h):
    h.runner.start()
    h.clock.pos = 8000          # == gate.clip_end_ms == after.enter_ms
    h.runner.tick()
    assert h.runner.beat.id == "gate"
    assert h.runner.status == STATUS_GATED
    assert "after0" not in h.names
    assert h.names == ["a0", "a1", "opt0", "g0"]


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------

def test_reaching_clip_end_of_gated_beat_pauses_and_counts_down(h):
    h.runner.start()
    h.run_to(7500)
    assert h.runner.beat.id == "gate" and h.runner.status == STATUS_RUNNING
    assert h.runner.gate_seconds_left() is None
    pauses = h.clock.count("pause")
    h.run_to(8000)
    assert h.runner.status == STATUS_GATED
    assert h.clock.running is False
    assert h.clock.count("pause") == pauses + 1
    assert h.runner.gate_seconds_left() == pytest.approx(GATE_WALL_MS / 1000)
    h.wall.advance(1.0)
    assert h.runner.gate_seconds_left() == pytest.approx(GATE_WALL_MS / 1000 - 1)
    # Ticking while gated (before the deadline) neither moves nor advances.
    h.runner.tick()
    assert h.runner.status == STATUS_GATED and h.runner.beat.id == "gate"
    h.wall.advance(10.0)
    assert h.runner.gate_seconds_left() == 0.0


def test_gate_stays_gated_when_next_beat_enters_at_clip_end(h):
    # gate.clip_end_ms == after.enter_ms: the gate must win over the
    # "last beat whose enter_ms <= ms" rule or it could never engage.
    h.runner.start()
    h.run_to(8000, step=1000)
    assert h.runner.beat.id == "gate"
    assert h.runner.status == STATUS_GATED
    assert h.runner.state()["gate"] == "chk"


def test_satisfy_gate_during_gate_jumps_to_advance_to(h):
    h.runner.start()
    h.run_to(8000)
    assert h.runner.status == STATUS_GATED
    assert h.runner.satisfy_gate() is True
    assert h.runner.status == STATUS_RUNNING
    assert h.runner.beat.id == "after"
    assert h.clock.seeks[-1] == 8000 and h.clock.running is True
    assert h.names[-1] == "after0" and "auto" not in h.names
    assert h.runner.gate_seconds_left() is None
    assert h.runner.satisfy_gate() is False      # "after" has no gate


def test_satisfy_gate_before_clip_end_waits_for_the_line_to_finish(h):
    # Acting while the instruction is still playing must not cut it off:
    # the jump is deferred to the clip end, and no pause happens there.
    h.runner.start()
    h.run_to(6000)
    assert h.runner.beat.id == "gate" and h.runner.status == STATUS_RUNNING
    assert h.runner.gate_active()
    assert h.runner.satisfy_gate() is True
    assert h.runner.beat.id == "gate" and h.runner.status == STATUS_RUNNING
    pauses = h.clock.count("pause")
    h.run_to(8000)
    assert h.runner.beat.id == "after"
    assert h.runner.status == STATUS_RUNNING
    assert h.clock.count("pause") == pauses
    assert h.clock.pos == 8000 and h.clock.running
    assert h.names == ["a0", "a1", "opt0", "g0", "after0"]


def test_satisfy_gate_outside_a_gated_beat_is_a_noop(h):
    assert h.runner.satisfy_gate() is False
    h.runner.start()
    assert h.runner.gate_active() is False
    assert h.runner.satisfy_gate() is False
    assert h.runner.beat.id == "a"


def test_wall_deadline_fires_auto_action_then_jumps(h):
    h.runner.start()
    h.run_to(8000)
    h.wall.advance(GATE_WALL_MS / 1000 - 0.01)
    h.runner.tick()
    assert h.runner.status == STATUS_GATED
    h.wall.advance(0.02)
    h.runner.tick()
    assert h.runner.status == STATUS_RUNNING
    assert h.runner.beat.id == "after"
    assert h.actions[-2:] == [("auto", {"x": 1}), ("after0", {})]
    assert h.clock.seeks[-1] == 8000 and h.clock.running


def test_gate_without_auto_action_just_jumps():
    tour = Tour("t", (
        Beat("a", 0, 1000, gate=Gate("chk", "b", auto_advance_wall_ms=1000)),
        Beat("b", 1000, 2000, actions=((1000, "b0", {}),)),
    ))
    hh = Harness(tour)
    hh.runner.start()
    hh.run_to(1000)
    assert hh.runner.status == STATUS_GATED
    hh.wall.advance(1.0)
    hh.runner.tick()
    assert hh.runner.beat.id == "b" and hh.names == ["b0"]


# ---------------------------------------------------------------------------
# user pause
# ---------------------------------------------------------------------------

def test_user_pause_while_running_pauses_clock_and_freezes_ticks(h):
    h.runner.start()
    h.run_to(500)
    h.runner.set_user_paused(True)
    assert h.runner.user_paused and h.clock.running is False
    assert h.clock.calls[-1] == ("pause",)
    # Even if the clock were to move, a paused runner does nothing.
    h.clock.pos = 1500
    h.runner.tick()
    assert h.names == ["a0"]
    h.runner.set_user_paused(False)
    assert h.clock.calls[-1] == ("resume",) and h.clock.running
    h.runner.tick()
    assert h.names == ["a0", "a1"]


def test_user_pause_is_idempotent(h):
    h.runner.start()
    n = len(h.clock.calls)
    h.runner.set_user_paused(False)
    assert len(h.clock.calls) == n
    h.runner.set_user_paused(True)
    h.runner.set_user_paused(True)
    assert h.clock.count("pause") == 1


def test_user_pause_freezes_gate_deadline(h):
    h.runner.start()
    h.run_to(8000)
    assert h.runner.status == STATUS_GATED
    h.wall.advance(1.0)
    before = h.runner.gate_seconds_left()
    h.runner.set_user_paused(True)
    h.wall.advance(30.0)
    h.runner.tick()                   # deadline long past, but paused
    assert h.runner.status == STATUS_GATED
    assert "auto" not in h.names
    h.runner.set_user_paused(False)
    # Unpausing while gated must NOT resume the clock ...
    assert h.clock.running is False
    assert h.runner.status == STATUS_GATED
    # ... and the deadline is extended by exactly the paused duration.
    assert h.runner.gate_seconds_left() == pytest.approx(before)
    h.wall.advance(before - 0.01)
    h.runner.tick()
    assert h.runner.status == STATUS_GATED
    h.wall.advance(0.02)
    h.runner.tick()
    assert h.runner.status == STATUS_RUNNING and h.runner.beat.id == "after"


def test_satisfy_gate_while_user_paused_does_not_resume_clock(h):
    h.runner.start()
    h.run_to(8000)
    h.runner.set_user_paused(True)
    assert h.runner.satisfy_gate() is True
    assert h.runner.beat.id == "after" and h.runner.status == STATUS_RUNNING
    assert h.clock.pos == 8000 and h.clock.running is False
    h.runner.set_user_paused(False)
    assert h.clock.running is True




def test_gate_countdown_freezes_while_user_paused():
    """The published countdown must not fall while paused (pinned by the
    QA scenario's pause_freezes_gate step)."""
    h = Harness(TOUR)
    h.runner.start()
    h.run_to(8000)
    assert h.runner.status == STATUS_GATED
    before = h.runner.gate_seconds_left()
    h.runner.set_user_paused(True)
    h.wall.advance(3.0)
    h.runner.tick()
    assert h.runner.gate_seconds_left() == pytest.approx(before)
    h.runner.set_user_paused(False)
    assert h.runner.gate_seconds_left() == pytest.approx(before)
