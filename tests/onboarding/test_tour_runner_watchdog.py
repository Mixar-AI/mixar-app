# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tour runner's two safety nets: the stall watchdog (a clock that
stops advancing, or reports ``ended()`` before the terminal beat, must not
freeze the tour) and the consumed gate (a gate whose jump no-ops must not
re-arm and rerun its ``auto_action`` on every timeout).

Also pins ``TourRunner.__init__`` refusing a table with a gate that cannot
jump forward, and ``skip_beat`` voiding an early gate satisfaction.
"""

from __future__ import annotations

import dataclasses
import logging

import pytest

from mixar.modules.onboarding.core.tour import runner as runner_mod
from mixar.modules.onboarding.core.tour.beats import Beat, Gate, Tour
from mixar.modules.onboarding.core.tour.runner import (
    STALL_SECONDS,
    STATUS_ENDED,
    STATUS_GATED,
    STATUS_RUNNING,
    TourRunner,
)
from tour_doubles import GATE_WALL_MS, TOUR, Harness


@pytest.fixture
def h():
    return Harness()


@pytest.fixture
def warnings(monkeypatch, caplog):
    monkeypatch.setattr(runner_mod.logger, "propagate", True)
    caplog.set_level(logging.WARNING, logger=runner_mod.logger.name)
    return caplog


# ---------------------------------------------------------------------------
# stall watchdog: a clock that stops advancing
# ---------------------------------------------------------------------------

def test_stalled_clock_skips_the_beat_after_stall_seconds(h, warnings):
    h.runner.start()
    h.run_to(500)
    # The clock is running but no longer moves (the audio handle clamped).
    h.wall.advance(STALL_SECONDS - 0.1)
    h.runner.tick()
    assert h.runner.beat.id == "a" and warnings.records == []
    h.wall.advance(0.2)
    h.runner.tick()
    assert h.runner.beat.id == "opt" and h.runner.status == STATUS_RUNNING
    assert h.clock.seeks[-1] == 2000
    assert h.names == ["a0", "a1", "opt0"]
    assert len(warnings.records) == 1
    assert "stalled" in warnings.records[0].getMessage()


def test_watchdog_stays_quiet_while_the_clock_advances(h, warnings):
    h.runner.start()
    for _ in range(40):                     # 10 s of wall, clock moving
        h.clock.step(100)
        h.wall.advance(0.25)
        h.runner.tick()
    assert h.runner.beat.id == "opt" and h.clock.pos == 4000
    assert warnings.records == []


def test_watchdog_ignores_time_spent_user_paused(h):
    h.runner.start()
    h.run_to(500)
    h.runner.set_user_paused(True)
    h.wall.advance(60.0)
    h.runner.tick()
    h.runner.set_user_paused(False)
    h.runner.tick()
    assert h.runner.beat.id == "a"
    h.wall.advance(STALL_SECONDS - 0.1)
    h.runner.tick()
    assert h.runner.beat.id == "a"
    h.wall.advance(0.2)
    h.runner.tick()
    assert h.runner.beat.id == "opt"


def test_watchdog_ignores_time_spent_gated(h):
    h.runner.start()
    h.run_to(8000)
    assert h.runner.status == STATUS_GATED
    h.wall.advance(GATE_WALL_MS / 1000 + 5.0)
    h.runner.tick()                          # the gate deadline, not a stall
    assert h.runner.beat.id == "after" and h.runner.status == STATUS_RUNNING
    h.runner.tick()                          # same ms as before the gate: fresh
    assert h.runner.beat.id == "after"
    h.wall.advance(STALL_SECONDS)
    h.runner.tick()
    assert h.runner.beat.id == "end"         # now a genuine stall


def test_stalled_gated_beat_before_clip_end_takes_the_auto_path(h):
    h.runner.start()
    h.run_to(6000)
    assert h.runner.beat.id == "gate"
    h.wall.advance(STALL_SECONDS)
    h.runner.tick()
    assert h.runner.beat.id == "after"
    assert h.actions[-2:] == [("auto", {"x": 1}), ("after0", {})]


def test_stalled_terminal_beat_ends_the_tour(h, warnings):
    h.runner.start()
    h.run_to(8000)
    h.runner.satisfy_gate()
    h.clock.pos = 10500
    h.runner.tick()
    assert h.runner.beat.id == "end" and h.ends == 0
    h.wall.advance(STALL_SECONDS)
    h.runner.tick()
    assert h.runner.status == STATUS_ENDED and h.ends == 1
    assert "ending" in warnings.records[0].getMessage()


def test_terminal_end_wait_is_not_a_stall():
    tour = Tour("t", (
        Beat("a", 0, 1000),
        Beat("z", 1000, 2000, end_after_wall_ms=int((STALL_SECONDS + 2) * 1000)),
    ))
    hh = Harness(tour)
    hh.runner.start()
    hh.run_to(2000)
    assert hh.runner.beat.id == "z" and hh.clock.running is False
    hh.wall.advance(STALL_SECONDS + 0.5)
    hh.runner.tick()
    assert hh.ends == 0                      # still waiting out end_after_wall_ms
    hh.wall.advance(2.0)
    hh.runner.tick()
    assert hh.ends == 1


# ---------------------------------------------------------------------------
# stall watchdog: a clock whose ended() flips early
# ---------------------------------------------------------------------------

def test_clock_ended_on_a_non_terminal_beat_skips_it(h, warnings):
    h.runner.start()
    h.run_to(500)
    h.clock.is_ended = True
    h.runner.tick()
    assert h.runner.beat.id == "opt" and h.runner.status == STATUS_RUNNING
    assert h.names == ["a0", "a1", "opt0"]
    assert "clock ended" in warnings.records[0].getMessage()


def test_clock_ended_early_still_reaches_the_end(h):
    h.runner.start()
    h.run_to(500)
    h.clock.is_ended = True
    for _ in range(10):
        if h.runner.status == STATUS_ENDED:
            break
        h.runner.tick()
        h.wall.advance(TOUR.beats[-1].end_after_wall_ms / 1000)
    assert h.runner.status == STATUS_ENDED and h.ends == 1
    # Every table action fired once, in order, plus the gate's auto action.
    table = [name for b in TOUR.beats for _at, name, _a in b.actions]
    assert [n for n in h.names if n != "auto"] == table
    assert h.names.count("auto") == 1


# ---------------------------------------------------------------------------
# consumed gates
# ---------------------------------------------------------------------------

def _with_backward_gate(hh, beat_id, advance_to):
    """Rewrite one beat's gate after construction (``__init__`` refuses it)."""
    beats = list(hh.runner.beats)
    i = next(k for k, b in enumerate(beats) if b.id == beat_id)
    beats[i] = dataclasses.replace(
        beats[i], gate=dataclasses.replace(beats[i].gate, advance_to=advance_to))
    hh.runner.beats = tuple(beats)


def test_noop_jump_consumes_the_gate_and_never_rearms(h):
    _with_backward_gate(h, "gate", "a")
    h.runner.start()
    h.run_to(8000)
    assert h.runner.status == STATUS_GATED
    h.wall.advance(GATE_WALL_MS / 1000)
    h.runner.tick()
    assert h.names.count("auto") == 1
    assert h.runner.beat.id == "gate" and h.runner.status == STATUS_RUNNING
    assert h.clock.running and h.runner.gate_seconds_left() is None
    assert h.runner.gate_active() is False
    # The beat is now plain: at the same ms the next beat (which enters at
    # this clip end) is entered instead of re-gating, and the auto action
    # does not run again.
    h.runner.tick()
    assert h.runner.beat.id == "after" and h.names[-1] == "after0"
    assert h.runner.status == STATUS_RUNNING and h.names.count("auto") == 1
    h.run_to(9500)
    assert h.runner.beat.id == "after" and h.runner.status == STATUS_RUNNING
    assert h.names.count("auto") == 1 and "after1" in h.names


def test_consumed_gate_with_a_gap_plays_on_to_the_next_beat():
    # The gated line ends before the next beat enters: after the no-op
    # jump the clock keeps playing through the gap and enters it on time.
    tour = Tour("t", (
        Beat("a", 0, 1000, actions=((0, "a0", {}),)),
        Beat("g", 1000, 2000, gate=Gate("chk", "a", auto_advance_wall_ms=1000,
                                       auto_action=("auto", {}))),
        Beat("z", 3000, 4000, actions=((3000, "z0", {}),)),
    ))
    hh = Harness(Tour("t", (tour.beats[0], dataclasses.replace(tour.beats[1], gate=None),
                            tour.beats[2])))
    hh.runner.beats = tour.beats
    hh.runner.start()
    hh.run_to(2000)
    assert hh.runner.status == STATUS_GATED
    hh.wall.advance(1.0)
    hh.runner.tick()
    assert hh.runner.beat.id == "g" and hh.runner.status == STATUS_RUNNING
    hh.wall.advance(1.0)
    hh.runner.tick()                          # same ms, still under STALL_SECONDS
    assert hh.runner.beat.id == "g" and hh.runner.status == STATUS_RUNNING
    hh.run_to(3000)
    assert hh.runner.beat.id == "z" and hh.names == ["a0", "auto", "z0"]


def test_noop_jump_from_satisfy_gate_consumes_too(h):
    _with_backward_gate(h, "gate", "a")
    h.runner.start()
    h.run_to(8000)
    assert h.runner.satisfy_gate() is True
    assert h.runner.status == STATUS_RUNNING and h.runner.beat.id == "gate"
    h.wall.advance(GATE_WALL_MS / 1000 * 3)
    h.runner.tick()
    assert h.runner.status == STATUS_RUNNING and "auto" not in h.names
    assert h.runner.satisfy_gate() is False


def test_consumed_gate_on_terminal_beat_falls_through_to_the_end():
    tour = Tour("t", (
        Beat("a", 0, 1000),
        Beat("z", 1000, 2000, gate=Gate("chk", "a", auto_advance_wall_ms=1000,
                                       auto_action=("auto", {}))),
    ))
    with pytest.raises(ValueError):
        Harness(tour)
    hh = Harness(Tour("t", (tour.beats[0], dataclasses.replace(tour.beats[1], gate=None))))
    hh.runner.beats = tour.beats
    hh.runner.start()
    hh.run_to(2000)
    assert hh.runner.status == STATUS_GATED
    hh.wall.advance(1.0)
    hh.runner.tick()
    assert hh.names == ["auto"] and hh.runner.status == STATUS_RUNNING
    hh.runner.tick()                          # terminal beat at its clip end
    assert hh.clock.running is False and hh.ends == 0
    hh.wall.advance(tour.beats[1].end_after_wall_ms / 1000)
    hh.runner.tick()
    assert hh.runner.status == STATUS_ENDED and hh.ends == 1
    assert hh.names == ["auto"]


# ---------------------------------------------------------------------------
# __init__ validation
# ---------------------------------------------------------------------------

def _runner(tour, skipped_ids=()):
    return TourRunner(tour, Harness().clock, on_action=lambda *_: None,
                      on_end=lambda: None, skipped_ids=skipped_ids)


def test_init_rejects_backward_self_and_missing_gate_targets():
    with pytest.raises(ValueError, match="advance forward"):
        _runner(Tour("t", (Beat("a", 0, 1000),
                           Beat("b", 1000, 2000, gate=Gate("c", "a")))))
    with pytest.raises(ValueError, match="advance forward"):
        _runner(Tour("t", (Beat("a", 0, 1000, gate=Gate("c", "a")),
                           Beat("b", 1000, 2000))))
    with pytest.raises(ValueError, match="not a playable beat"):
        _runner(Tour("t", (Beat("a", 0, 1000, gate=Gate("c", "zzz")),
                           Beat("b", 1000, 2000))))


def test_init_rejects_gate_target_dropped_by_the_skip_plan():
    tour = Tour("t", (
        Beat("a", 0, 1000, gate=Gate("c", "opt")),
        Beat("opt", 1000, 2000, optional=True),
        Beat("z", 2000, 3000),
    ))
    _runner(tour)                              # fine while "opt" plays
    with pytest.raises(ValueError, match="not a playable beat"):
        _runner(tour, skipped_ids=("opt",))


# ---------------------------------------------------------------------------
# skip_beat and gates
# ---------------------------------------------------------------------------

def test_skip_beat_voids_an_early_gate_satisfaction(h):
    h.runner.start()
    h.run_to(6000)
    assert h.runner.satisfy_gate() is True
    assert h.runner._gate_satisfied_early is True
    h.runner.skip_beat()
    assert h.runner._gate_satisfied_early is False
    assert h.runner.beat.id == "after"
    # No second jump when the clock later passes the old gate's clip end.
    h.run_to(8500)
    assert h.runner.beat.id == "after" and h.names.count("after0") == 1


def test_skip_beat_on_gated_beat_before_clip_end_runs_the_auto_path(h):
    """Documented: "Skip step" during a gated beat's line does not wait for
    the clip end; it performs the gate action the tour's own way and jumps
    (same as the wall deadline)."""
    h.runner.start()
    h.run_to(6000)
    assert h.runner.status == STATUS_RUNNING and h.runner.gate_active()
    h.runner.skip_beat()
    assert h.runner.beat.id == "after" and h.runner.status == STATUS_RUNNING
    assert h.actions[-2:] == [("auto", {"x": 1}), ("after0", {})]
    assert h.clock.seeks[-1] == 8000 and h.clock.running
