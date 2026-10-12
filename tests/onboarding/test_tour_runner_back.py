# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The video card's Back control (``TourRunner.back_beat``).

Contract: like a player's previous-track button, Back restarts the current
beat, or goes to the previous beat when pressed within ``BACK_RESTART_MS``
of the beat's start. Actions cannot be undone, so the target beat's and
every later beat's actions and gates are re-armed and replay forward.
"""

from __future__ import annotations

import pytest

from mixar.modules.onboarding.core.tour.beats import Beat, Tour
from mixar.modules.onboarding.core.tour.config import BACK_RESTART_MS
from mixar.modules.onboarding.core.tour.runner import (
    STATUS_ENDED,
    STATUS_GATED,
    STATUS_RUNNING,
)
from tour_doubles import GATE_WALL_MS, LINEAR, Harness


# A beat long enough to be pressed well past BACK_RESTART_MS.
LONG = Tour("long", (
    Beat("a", 0, 2000, actions=((0, "a0", {}),)),
    Beat("b", 2000, 8000, actions=((2000, "b0", {}),)),
    Beat("c", 8000, 10000, actions=((8000, "c0", {}),)),
))


@pytest.fixture
def h():
    return Harness(LINEAR)


def test_back_late_in_a_beat_restarts_it():
    hh = Harness(LONG)
    hh.runner.start()
    hh.run_to(2000 + BACK_RESTART_MS + 500)  # well past "b"'s start
    assert hh.runner.beat.id == "b"
    hh.runner.back_beat()
    assert hh.runner.beat.id == "b"
    assert hh.clock.seeks[-1] == 2000 and hh.clock.running
    assert hh.runner.status == STATUS_RUNNING
    assert hh.names == ["a0", "b0", "b0"]


def test_back_early_in_a_beat_goes_to_the_previous_one(h):
    h.runner.start()
    h.run_to(4500)  # 500 ms into "c"
    h.runner.back_beat()
    assert h.runner.beat.id == "b"
    assert h.clock.seeks[-1] == 2000
    # "b" replays its entry action now; its later action replays on time.
    assert h.names[-1] == "b0"
    h.run_to(3000)
    assert h.names[-1] == "b1"


def test_back_rearms_actions_of_every_rewound_beat(h):
    h.runner.start()
    h.run_to(6500)  # "d", d0 fired
    assert h.names.count("c0") == 1 and h.names.count("d0") == 1
    h.runner.back_beat()  # early in "d" → "c"
    h.run_to(6500)
    assert h.names.count("c0") == 2 and h.names.count("d0") == 2
    # Beats before the target are not replayed.
    assert h.names.count("a0") == 1 and h.names.count("b0") == 1


def test_back_on_the_first_beat_restarts_it(h):
    h.runner.start()
    h.run_to(500)
    h.runner.back_beat()
    assert h.runner.beat.id == "a" and h.clock.seeks[-1] == 0


def test_back_while_user_paused_stays_paused(h):
    h.runner.start()
    h.run_to(4500)
    h.runner.set_user_paused(True)
    h.runner.back_beat()
    assert h.runner.beat.id == "b" and not h.clock.running
    h.runner.set_user_paused(False)
    assert h.clock.running


def test_back_from_a_gate_replays_the_line_and_rearms_the_gate():
    hh = Harness()
    hh.runner.start()
    hh.run_to(8000)
    assert hh.runner.status == STATUS_GATED and hh.runner.beat.id == "gate"
    hh.runner.back_beat()
    assert hh.runner.beat.id == "gate" and hh.runner.status == STATUS_RUNNING
    assert hh.clock.seeks[-1] == 5000 and hh.clock.running
    hh.run_to(8000)
    assert hh.runner.status == STATUS_GATED
    hh.wall.advance(GATE_WALL_MS / 1000.0 + 0.1)
    hh.runner.tick()
    assert hh.runner.beat.id == "after"


def test_back_after_a_skipped_gate_rearms_it():
    hh = Harness()
    hh.runner.start()
    hh.run_to(8000)
    hh.runner.skip_beat()  # auto path → "after"
    assert hh.runner.beat.id == "after"
    hh.runner.back_beat()  # early in "after" → "gate"
    assert hh.runner.beat.id == "gate"
    hh.run_to(8000)
    assert hh.runner.status == STATUS_GATED


def test_back_after_the_end_does_nothing(h):
    h.runner.start()
    h.runner.end()
    seeks = list(h.clock.seeks)
    h.runner.back_beat()
    assert h.runner.status == STATUS_ENDED and h.clock.seeks == seeks
