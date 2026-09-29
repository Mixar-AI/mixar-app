# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parts play as one timeline; parts open on prepare(), never in draw."""

import sys
from unittest.mock import MagicMock

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock(name="requests")

from mixar.modules.onboarding.core.tour import video_parts  # noqa: E402


class FakeTex:
    opened = []

    def __init__(self, path):
        self.path = path
        self.width, self.height = 1280, 720
        self.duration_ms = 1000
        self.asked = []
        self.closed = False
        FakeTex.opened.append(path)

    def texture_for_ms(self, ms):
        self.asked.append(ms)
        return f"tex:{self.path}@{ms}"

    def close(self):
        self.closed = True


PARTS = [(0, 5000, "p0"), (5000, 9000, "p1"), (9000, 12000, "p2")]


def test_index_and_relative_frame_time(monkeypatch):
    monkeypatch.setattr(video_parts, "MovieTexture", FakeTex)
    FakeTex.opened.clear()
    m = video_parts.PartsMovie(PARTS)
    assert m.duration_ms == 12000
    m.prepare(0)
    assert FakeTex.opened == ["p0"]
    assert m.texture_for_ms(400) == "tex:p0@400"
    m.prepare(5200)
    assert m.texture_for_ms(5200) == "tex:p1@200"
    assert m.texture_for_ms(11999) is not None      # unprepared: holds a frame, no open
    assert "p2" not in FakeTex.opened


def test_next_part_preopens_near_the_boundary_and_old_parts_close(monkeypatch):
    monkeypatch.setattr(video_parts, "MovieTexture", FakeTex)
    FakeTex.opened.clear()
    m = video_parts.PartsMovie(PARTS)
    m.prepare(0)
    m.prepare(3900)                    # within PREOPEN_AHEAD_MS of 5000
    assert FakeTex.opened == ["p0", "p1"]
    m.prepare(9600)
    assert FakeTex.opened == ["p0", "p1", "p2"]
    assert all(t.closed for k, t in m._open.items() if k == 0) or 0 not in m._open
    m.close()
    assert m._open == {}
