# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pure timing contracts for sparse camera beats."""

from pathlib import Path
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core.frame_math import (  # noqa: E402
    clamp_frame_delta,
    effective_fps,
    frames_per_beat,
    next_beat_frame,
    seconds_from_frame,
)


def test_beat_spacing_uses_blenders_effective_fps():
    assert effective_fps(24, 1.0) == 24.0
    assert effective_fps(30, 1.001) == pytest.approx(29.97003)
    assert frames_per_beat(1.0, 30, 1.001) == 30


def test_beat_spacing_never_collapses_to_zero_frames():
    assert frames_per_beat(0.0, 24) == 1
    assert frames_per_beat(0.001, 24) == 1


def test_next_beat_starts_on_scene_start_then_advances_from_latest():
    assert next_beat_frame([], frame_start=101, stride=24) == 101
    assert next_beat_frame([101, 149, 125], frame_start=101, stride=24) == 173


def test_seconds_are_relative_to_the_first_sparse_beat():
    assert seconds_from_frame(148, origin_frame=100, fps=24) == 2.0


def test_strip_delta_clamps_as_one_unit_without_changing_spacing():
    assert clamp_frame_delta([25, 49, 73], -40, minimum_frame=1) == -24
    assert clamp_frame_delta([25, 49, 73], 12, minimum_frame=1) == 12
    assert clamp_frame_delta(
        [1048570, 1048574],
        20,
        minimum_frame=1,
    ) == 0
    assert clamp_frame_delta([], 20, minimum_frame=1) == 0


@pytest.mark.parametrize("fps,base", [(0, 1), (-24, 1), (24, 0)])
def test_invalid_frame_rates_fail_loudly(fps, base):
    with pytest.raises(ValueError):
        effective_fps(fps, base)
