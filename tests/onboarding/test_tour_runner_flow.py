# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later


"""The interactive tour's beat state machine (``runner.TourRunner``):
"Skip step", the terminal beat, ``state()``, skip ranges, and the real
``MIXAR_INTRO`` table run end to end with a hand-stepped clock.

``test_tour_runner.py`` covers start, ticking, gates and user pause. The
doubles live in ``tour_doubles.py``.
"""

from __future__ import annotations

import pytest

from mixar.modules.onboarding.core.tour.beats import MIXAR_INTRO
from mixar.modules.onboarding.core.tour.runner import (
    STATUS_ENDED,
    STATUS_GATED,
    STATUS_IDLE,
    STATUS_RUNNING,
)
from tour_doubles import END_WALL_MS, GATE_WALL_MS, Harness


@pytest.fixture
def h():
    return Harness()


# ---------------------------------------------------------------------------
# skip_beat
# ---------------------------------------------------------------------------

def test_skip_beat_from_running_jumps_to_next_beat(h):
    h.runner.start()
    h.run_to(500)
    h.runner.skip_beat()
    assert h.runner.beat.id == "opt"
    assert h.clock.seeks[-1] == 2000 and h.clock.running
    # The beat left behind fires the actions it never reached, then the
    # target's entry action.
    assert h.names == ["a0", "a1", "opt0"]
    assert h.runner.status == STATUS_RUNNING


def test_skip_beat_from_gate_runs_auto_path(h):
    h.runner.start()
    h.run_to(8000)
    assert h.runner.status == STATUS_GATED
    h.runner.skip_beat()
    assert h.runner.beat.id == "after" and h.runner.status == STATUS_RUNNING
    assert h.actions[-2:] == [("auto", {"x": 1}), ("after0", {})]


def test_skip_beat_on_gated_beat_before_clip_end_runs_auto_path(h):
    h.runner.start()
    h.run_to(6000)
    h.runner.skip_beat()
    assert h.runner.beat.id == "after"
    assert h.actions[-2:] == [("auto", {"x": 1}), ("after0", {})]


def test_skip_beat_on_last_beat_ends(h):
    h.runner.start()
    h.run_to(8000)
    h.runner.satisfy_gate()
    h.clock.pos = 10500
    h.runner.tick()
    assert h.runner.beat.id == "end"
    h.runner.skip_beat()
    assert h.runner.status == STATUS_ENDED and h.ends == 1
    h.runner.skip_beat()
    assert h.ends == 1


# ---------------------------------------------------------------------------
# terminal beat / end
# ---------------------------------------------------------------------------

def test_terminal_beat_pauses_then_ends_after_wall_delay(h):
    h.runner.start()
    h.run_to(8000)
    h.runner.satisfy_gate()
    h.run_to(11500)
    assert h.runner.beat.id == "end" and h.clock.running
    assert h.names[-1] == "end0"
    pauses = h.clock.count("pause")
    h.run_to(12000)
    assert h.clock.running is False
    assert h.clock.count("pause") == pauses + 1
    assert h.runner.status == STATUS_RUNNING and h.ends == 0
    h.wall.advance(END_WALL_MS / 1000 - 0.01)
    h.runner.tick()
    assert h.ends == 0
    h.wall.advance(0.02)
    h.runner.tick()
    assert h.runner.status == STATUS_ENDED and h.ends == 1
    for _ in range(3):
        h.runner.tick()
    h.runner.end()
    assert h.ends == 1


def test_terminal_beat_ends_when_clock_reports_ended(h):
    h.runner.start()
    h.run_to(8000)
    h.runner.satisfy_gate()
    h.clock.pos = 10000
    h.runner.tick()
    assert h.runner.beat.id == "end"
    h.clock.is_ended = True
    h.runner.tick()
    assert h.clock.running is False
    h.wall.advance(END_WALL_MS / 1000)
    h.runner.tick()
    assert h.runner.status == STATUS_ENDED and h.ends == 1


def test_user_pause_extends_end_deadline(h):
    h.runner.start()
    h.run_to(8000)
    h.runner.satisfy_gate()
    h.clock.pos = 12000
    h.runner.tick()                       # end deadline armed, clock paused
    assert h.runner.beat.id == "end" and h.clock.running is False
    h.runner.set_user_paused(True)
    h.wall.advance(60.0)
    h.runner.tick()
    assert h.ends == 0
    h.runner.set_user_paused(False)
    h.runner.tick()
    assert h.ends == 0
    h.wall.advance(END_WALL_MS / 1000)
    h.runner.tick()
    assert h.ends == 1


def test_end_is_idempotent_and_pauses_clock(h):
    h.runner.start()
    h.runner.end()
    assert h.runner.status == STATUS_ENDED and h.ends == 1
    assert h.clock.calls[-1] == ("pause",)
    h.runner.end()
    h.runner.tick()
    h.runner.set_user_paused(True)
    assert h.ends == 1 and h.runner.user_paused is False


def test_end_fires_on_end_even_if_clock_pause_raises():
    hh = Harness()
    hh.runner.start()

    def boom():
        raise RuntimeError("no clock")

    hh.clock.pause = boom
    with pytest.raises(RuntimeError):
        hh.runner.end()
    assert hh.ends == 1 and hh.runner.status == STATUS_ENDED


# ---------------------------------------------------------------------------
# state()
# ---------------------------------------------------------------------------

def test_state_keys_and_values(h):
    keys = {"tour", "status", "index", "beat", "ms", "paused", "gate",
            "gate_seconds_left"}
    s = h.runner.state()
    assert set(s) == keys
    assert s == {"tour": "synthetic", "status": STATUS_IDLE, "index": -1,
                 "beat": "", "ms": 0, "paused": False, "gate": "",
                 "gate_seconds_left": None}
    h.runner.start()
    h.run_to(8000)
    s = h.runner.state()
    assert set(s) == keys
    assert s["status"] == STATUS_GATED and s["beat"] == "gate"
    assert s["index"] == 2 and s["ms"] == 8000 and s["gate"] == "chk"
    assert s["gate_seconds_left"] == pytest.approx(GATE_WALL_MS / 1000)
    h.runner.set_user_paused(True)
    assert h.runner.state()["paused"] is True


# ---------------------------------------------------------------------------
# skip ranges
# ---------------------------------------------------------------------------

def test_skipped_optional_beat_is_dropped_and_seeked_over():
    hh = Harness(skipped_ids=("opt",))
    assert [b.id for b in hh.runner.beats] == ["a", "gate", "after", "end"]
    assert len(hh.runner.skip_ranges) == 1
    r = hh.runner.skip_ranges[0]
    assert (r.start_ms, r.resume_ms) == (2000, 5000)
    hh.runner.start()
    hh.run_to(1500)
    assert hh.names == ["a0", "a1"]
    hh.clock.pos = 2500                   # inside the range
    hh.runner.tick()
    assert hh.clock.seeks[-1] == 5000 and hh.clock.pos == 5000
    assert hh.runner.beat.id == "gate" and hh.runner.index == 1
    assert hh.runner.last_ms == 5000
    assert hh.names == ["a0", "a1", "g0"]
    assert "opt0" not in hh.names


def test_skip_range_start_is_inclusive_and_resume_exclusive():
    hh = Harness(skipped_ids=("opt",))
    hh.runner.start()
    hh.clock.pos = 2000
    hh.runner.tick()
    assert hh.clock.seeks[-1] == 5000
    n = len(hh.clock.seeks)
    hh.runner.tick()                      # at resume_ms: no further seek
    assert len(hh.clock.seeks) == n


def test_skipping_non_optional_beat_is_rejected():
    with pytest.raises(ValueError):
        Harness(skipped_ids=("gate",))


# ---------------------------------------------------------------------------
# MIXAR_INTRO end to end
# ---------------------------------------------------------------------------

def test_mixar_intro_smoke_run():
    hh = Harness(MIXAR_INTRO)
    r = hh.runner
    gate_beats = []
    r.start()
    for _ in range(20000):
        if r.status == STATUS_ENDED:
            break
        hh.clock.step(500)
        hh.wall.advance(0.5)
        r.tick()
        if r.status == STATUS_GATED:
            if r.beat.id not in gate_beats:
                gate_beats.append(r.beat.id)
            # Let the wall deadline win: the tour performs the action itself.
            hh.wall.advance(r.beat.gate.auto_advance_wall_ms / 1000)
            r.tick()
            assert r.status == STATUS_RUNNING
    else:
        pytest.fail("tour did not end")

    assert hh.ends == 1
    assert r.status == STATUS_ENDED
    assert r.beat.id == MIXAR_INTRO.beats[-1].id

    expected_gates = [b.id for b in MIXAR_INTRO.beats if b.gate is not None]
    assert gate_beats == expected_gates

    names = hh.names
    for required in ("ensure_zen", "island_open", "island_expand", "island_tab",
                     "drawer_set", "moodboard_add_demo_image",
                     "ui_mode", "tour_cleanup"):
        assert required in names, required
    assert names.count("island_tab") >= 5
    assert names[0] == "ensure_zen"
    assert names[-1] == "tour_cleanup"
    first = {n: names.index(n) for n in set(names)}
    assert (first["ensure_zen"] < first["island_open"] < first["island_expand"]
            < first["island_tab"] < first["drawer_set"]
            < first["moodboard_add_demo_image"]
            < first["ui_mode"] < first["tour_cleanup"])

    # Every table action fired exactly once through the natural path (the
    # gates' auto_actions come on top of those).
    table = [(name, args) for b in MIXAR_INTRO.beats for _at, name, args in b.actions]
    autos = [b.gate.auto_action for b in MIXAR_INTRO.beats
             if b.gate is not None and b.gate.auto_action is not None]
    assert sorted(map(repr, hh.actions)) == sorted(
        map(repr, table + [(n, dict(a)) for n, a in autos]))


def test_mixar_intro_smoke_run_with_user_satisfying_every_gate():
    hh = Harness(MIXAR_INTRO)
    r = hh.runner
    r.start()
    for _ in range(20000):
        if r.status == STATUS_ENDED:
            break
        hh.clock.step(500)
        hh.wall.advance(0.5)
        r.tick()
        if r.status == STATUS_GATED:
            assert r.satisfy_gate()
    else:
        pytest.fail("tour did not end")
    assert hh.ends == 1
    table = [(name, args) for b in MIXAR_INTRO.beats for _at, name, args in b.actions]
    assert hh.actions == table
