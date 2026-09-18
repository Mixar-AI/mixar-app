# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test doubles shared by the tour runner tests.

A hand-stepped ``FakeClock`` (position moves only through ``step()`` and
only while running; every pause/resume/seek is recorded), a settable
``Wall`` time, a ``Harness`` wiring both into a ``TourRunner`` with a
recording action sink, and two synthetic tours: ``TOUR`` (plain, optional,
gated and terminal beats) and ``LINEAR`` (gate-free, for clock jumps).
"""

from __future__ import annotations

from mixar.modules.onboarding.core.tour.beats import Beat, Gate, Tour
from mixar.modules.onboarding.core.tour.runner import TourRunner


class FakeClock:
    """Position advances only through ``step()`` and only while running."""

    def __init__(self):
        self.pos = 0
        self.running = False
        self.calls = []
        self.is_ended = False

    def position_ms(self):
        return self.pos

    def pause(self):
        self.running = False
        self.calls.append(("pause",))

    def resume(self):
        self.running = True
        self.calls.append(("resume",))

    def seek_ms(self, ms):
        self.pos = ms
        self.calls.append(("seek", ms))

    def ended(self):
        return self.is_ended

    # helpers
    def step(self, ms):
        if self.running:
            self.pos += ms

    @property
    def seeks(self):
        return [c[1] for c in self.calls if c[0] == "seek"]

    def count(self, kind):
        return sum(1 for c in self.calls if c[0] == kind)


class Wall:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


GATE_WALL_MS = 3000
END_WALL_MS = 2000

TOUR = Tour("synthetic", (
    Beat("a", 0, 2000, actions=((0, "a0", {}), (1000, "a1", {"k": 1}))),
    Beat("opt", 2000, 5000, optional=True, actions=((2000, "opt0", {}),)),
    Beat("gate", 5000, 8000, actions=((5000, "g0", {}),),
         gate=Gate("chk", "after", auto_advance_wall_ms=GATE_WALL_MS,
                   auto_action=("auto", {"x": 1}))),
    Beat("after", 8000, 10000, actions=((8000, "after0", {}), (9000, "after1", {}))),
    Beat("end", 10000, 12000, actions=((10000, "end0", {}),),
         end_after_wall_ms=END_WALL_MS),
))


class Harness:
    def __init__(self, tour=TOUR, skipped_ids=()):
        self.clock = FakeClock()
        self.wall = Wall()
        self.actions = []
        self.ends = 0
        self.runner = TourRunner(
            tour, self.clock,
            on_action=lambda name, args: self.actions.append((name, args)),
            on_end=self._on_end,
            skipped_ids=skipped_ids,
            wall=self.wall,
        )

    def _on_end(self):
        self.ends += 1

    @property
    def names(self):
        return [n for n, _ in self.actions]

    def run_to(self, ms, step=500):
        """Step the clock to ``ms`` (inclusive), ticking each step."""
        while self.clock.pos < ms:
            self.clock.step(min(step, ms - self.clock.pos))
            self.runner.tick()
        return self.runner


LINEAR = Tour("linear", (
    Beat("a", 0, 2000, actions=((0, "a0", {}), (1000, "a1", {}))),
    Beat("b", 2000, 4000, actions=((2000, "b0", {}), (3000, "b1", {}))),
    Beat("c", 4000, 6000, actions=((4000, "c0", {}),)),
    Beat("d", 6000, 8000, actions=((6000, "d0", {}), (7500, "d1", {}))),
))

