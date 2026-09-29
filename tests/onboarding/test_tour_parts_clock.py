# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A pack's parts play as one clock and hold before a part that has not
downloaded yet, resuming when it lands."""

import sys
from unittest.mock import MagicMock

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock(name="requests")

from mixar.modules.onboarding.core.tour import clock, clock_parts  # noqa: E402

PARTS = [(0, 1000, "p0"), (1000, 3000, "p1"), (3000, 3500, "p2")]


class FakeTime:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make(monkeypatch, ready):
    ft = FakeTime()
    monkeypatch.setattr(clock.time, "monotonic", ft)
    c = clock_parts.SilentPartsClock(PARTS, ready=ready)
    return c, ft


def test_crosses_into_a_ready_part(monkeypatch):
    c, ft = make(monkeypatch, lambda k: True)
    c.resume()
    ft.t += 0.5
    assert 450 <= c.position_ms() <= 550
    ft.t += 0.8                      # past part 0's end
    pos = c.position_ms()
    assert 1000 <= pos <= 1400 and not c.waiting
    ft.t += 2.5                      # part 1 runs out …
    assert c.position_ms() == 3000   # … and part 2 begins at its own zero
    ft.t += 0.6
    assert c.position_ms() == 3500 and c.ended()


def test_holds_before_a_missing_part_then_continues(monkeypatch):
    ready = {0: True, 1: False, 2: True}
    c, ft = make(monkeypatch, lambda k: ready[k])
    c.resume()
    ft.t += 1.5
    assert c.position_ms() == 999 and c.waiting
    ft.t += 5.0
    assert c.position_ms() == 999 and c.waiting and not c.ended()
    ready[1] = True
    assert c.position_ms() >= 1000 and not c.waiting
    ft.t += 0.3
    assert 1250 <= c.position_ms() <= 1350


def test_seek_into_a_missing_part_holds_there(monkeypatch):
    ready = {0: True, 1: True, 2: False}
    c, ft = make(monkeypatch, lambda k: ready[k])
    c.resume()
    c.seek_ms(3100)
    assert c.position_ms() == 2999 and c.waiting
    ready[2] = True
    assert c.position_ms() >= 3000 and not c.waiting


def test_pause_and_rate_reach_the_inner_clock(monkeypatch):
    c, ft = make(monkeypatch, lambda k: True)
    c.resume()
    c.set_rate(2.0)
    ft.t += 0.25
    assert 450 <= c.position_ms() <= 550
    c.pause()
    ft.t += 1.0
    assert 450 <= c.position_ms() <= 550


def test_make_clock_builds_parts_clocks():
    silent = clock.make_clock(PARTS, 3500, silent=True)
    assert isinstance(silent, clock_parts.PartsClock)
    assert silent.duration_ms == 3500
