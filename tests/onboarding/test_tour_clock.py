# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tour clock: the silent wall clock's contract and ``make_clock``'s
environment overrides.

``aud`` is a MagicMock under this suite, so ``AudClock`` itself is not
exercised here; ``make_clock`` is pinned through a patched ``AudClock``.
"""

from __future__ import annotations

import time

import pytest

from mixar.modules.onboarding.core.tour import clock as clock_mod
from mixar.modules.onboarding.core.tour import config
from mixar.modules.onboarding.core.tour.clock import (
    AudClock,
    BaseClock,
    WallClock,
    make_clock,
)


class FakeMonotonic:
    def __init__(self, start: float = 100.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def mono(monkeypatch):
    fake = FakeMonotonic()
    monkeypatch.setattr(time, "monotonic", fake)
    return fake


class TestWallClock:
    def test_starts_paused_at_zero(self, mono):
        c = WallClock(duration_ms=10000)
        assert c.paused is True
        assert c.position_ms() == 0
        mono.advance(5.0)
        assert c.position_ms() == 0, "a paused clock does not advance"

    def test_advances_with_monotonic_time_once_resumed(self, mono):
        c = WallClock(duration_ms=10000)
        c.resume()
        assert c.paused is False
        mono.advance(1.5)
        assert c.position_ms() == 1500
        mono.advance(0.25)
        assert c.position_ms() == 1750

    def test_rate_scales_elapsed_time(self, mono):
        c = WallClock(duration_ms=60000, rate=2.0)
        c.resume()
        mono.advance(1.0)
        assert c.position_ms() == 2000

    def test_set_rate_keeps_position_continuous(self, mono):
        c = WallClock(duration_ms=60000)
        c.resume()
        mono.advance(1.0)
        c.set_rate(4.0)
        assert c.position_ms() == 1000
        mono.advance(0.5)
        assert c.position_ms() == 3000
        assert c.rate == 4.0

    def test_set_rate_rejects_non_positive(self, mono):
        c = WallClock(duration_ms=60000)
        c.set_rate(0)
        c.set_rate(-1)
        assert c.rate == 1.0

    def test_pause_freezes_and_resume_continues(self, mono):
        c = WallClock(duration_ms=60000)
        c.resume()
        mono.advance(2.0)
        c.pause()
        assert c.paused is True
        assert c.position_ms() == 2000
        mono.advance(10.0)
        assert c.position_ms() == 2000
        c.resume()
        mono.advance(1.0)
        assert c.position_ms() == 3000

    def test_pause_and_resume_are_idempotent(self, mono):
        c = WallClock(duration_ms=60000)
        c.pause()
        c.pause()
        c.resume()
        mono.advance(1.0)
        c.resume()   # a second resume must not restart the timer
        mono.advance(1.0)
        assert c.position_ms() == 2000

    def test_seek_moves_forward_and_backward(self, mono):
        c = WallClock(duration_ms=60000)
        c.resume()
        mono.advance(1.0)
        c.seek_ms(30000)
        assert c.position_ms() == 30000
        mono.advance(0.5)
        assert c.position_ms() == 30500
        c.seek_ms(5000)
        assert c.position_ms() == 5000, "an explicit seek may go backwards"
        c.seek_ms(-10)
        assert c.position_ms() == 0

    def test_seek_while_paused_holds_until_resume(self, mono):
        c = WallClock(duration_ms=60000)
        c.seek_ms(8000)
        mono.advance(3.0)
        assert c.position_ms() == 8000
        c.resume()
        mono.advance(1.0)
        assert c.position_ms() == 9000

    def test_position_never_runs_backwards_without_a_seek(self, mono):
        c = WallClock(duration_ms=60000)
        c.resume()
        mono.advance(1.0)
        assert c.position_ms() == 1000
        # A misbehaving time source jumping back is clamped to the last value.
        mono.advance(-0.5)
        assert c.position_ms() == 1000

    def test_ended_at_duration(self, mono):
        c = WallClock(duration_ms=3000)
        c.resume()
        mono.advance(2.999)
        assert c.ended() is False
        mono.advance(0.001)
        assert c.ended() is True
        mono.advance(10.0)
        assert c.position_ms() == 3000, "position clamps to the duration"

    def test_unknown_duration_never_ends(self, mono):
        c = WallClock(duration_ms=None)
        c.resume()
        mono.advance(1e6)
        assert c.ended() is False
        assert c.duration_ms is None

    def test_close_is_a_no_op(self, mono):
        c = WallClock(duration_ms=1000)
        c.close()
        assert isinstance(c, BaseClock)


class TestMakeClock:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        monkeypatch.delenv(config.ENV_SILENT, raising=False)
        monkeypatch.delenv(config.ENV_CLOCK_RATE, raising=False)

    def test_env_silent_forces_wall_clock(self, monkeypatch, mono):
        def never(*_a, **_k):
            raise AssertionError("AudClock must not be built when ENV_SILENT is set")

        monkeypatch.setattr(clock_mod, "AudClock", never)
        monkeypatch.setenv(config.ENV_SILENT, "1")
        c = make_clock("/nonexistent/founder.mp4", 160000, silent=False)
        assert isinstance(c, WallClock)
        assert c.paused is True
        assert c.position_ms() == 0
        assert c.duration_ms == 160000

    def test_env_silent_zero_overrides_silent_arg(self, monkeypatch, mono):
        built = {}

        def fake_aud(path, duration_ms, rate=1.0):
            built["args"] = (path, duration_ms, rate)
            return WallClock(duration_ms, rate)

        monkeypatch.setattr(clock_mod, "AudClock", fake_aud)
        monkeypatch.setenv(config.ENV_SILENT, "0")
        make_clock("/x.mp4", 1000, silent=True)
        assert built["args"] == ("/x.mp4", 1000, 1.0)

    def test_silent_arg_without_env(self, monkeypatch, mono):
        def never(*_a, **_k):
            raise AssertionError("silent=True must skip AudClock")

        monkeypatch.setattr(clock_mod, "AudClock", never)
        assert isinstance(make_clock("/x.mp4", 1000, silent=True), WallClock)

    def test_aud_failure_falls_back_to_wall_clock(self, monkeypatch, mono):
        def broken(*_a, **_k):
            raise RuntimeError("no audio device")

        monkeypatch.setattr(clock_mod, "AudClock", broken)
        c = make_clock("/x.mp4", 2000, silent=False)
        assert isinstance(c, WallClock)
        assert c.duration_ms == 2000

    def test_env_rate_overrides_argument(self, monkeypatch, mono):
        monkeypatch.setenv(config.ENV_SILENT, "1")
        monkeypatch.setenv(config.ENV_CLOCK_RATE, "4")
        c = make_clock("/x.mp4", 100000, silent=True, rate=1.0)
        assert c.rate == 4.0
        c.resume()
        mono.advance(1.0)
        assert c.position_ms() == 4000

    @pytest.mark.parametrize("bad", ["abc", "0", "-2", "  "])
    def test_env_rate_invalid_is_ignored(self, monkeypatch, mono, bad):
        monkeypatch.setenv(config.ENV_SILENT, "1")
        monkeypatch.setenv(config.ENV_CLOCK_RATE, bad)
        c = make_clock("/x.mp4", 100000, silent=True, rate=1.5)
        assert c.rate == 1.5

    def test_empty_path_uses_wall_clock(self, monkeypatch, mono):
        def never(*_a, **_k):
            raise AssertionError("no path, no audio")

        monkeypatch.setattr(clock_mod, "AudClock", never)
        assert isinstance(make_clock("", 1000), WallClock)


class TestAudClockInterface:
    def test_subclasses_base_and_matches_runner_protocol(self):
        for name in ("position_ms", "pause", "resume", "seek_ms", "set_rate",
                     "ended", "close"):
            assert callable(getattr(AudClock, name))
        assert issubclass(AudClock, BaseClock)
