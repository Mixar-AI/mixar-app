# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``video.estimate_fps``: the audio track length is trusted only when it
agrees with the video.

A trimmed audio tail made the estimated fps too high and ``duration_ms``
too short; the clock then clamped at that ceiling and a mid-table beat
could never end. ``MovieTexture`` itself needs a real ``bpy`` and is not
exercised here.
"""

from __future__ import annotations

import logging

import pytest

from mixar.modules.onboarding.core.tour import config, video
from mixar.modules.onboarding.core.tour.video import (
    estimate_fps,
    frame_index_for_ms,
)

# The founder take: 2743 frames at 24 fps, audio 114.22 s.
FRAMES = 2743
AUDIO_S = 114.2175


@pytest.fixture
def warnings(monkeypatch, caplog):
    """Records of the module logger (which does not propagate by default)."""
    monkeypatch.setattr(video.logger, "propagate", True)
    monkeypatch.setattr(video, "_fallback_warned", False)
    caplog.set_level(logging.DEBUG, logger=video.logger.name)
    return caplog


def test_intact_audio_snaps_to_the_standard_rate(warnings):
    assert estimate_fps(FRAMES, AUDIO_S) == 24.0
    assert warnings.records == []


def test_no_audio_uses_fallback_silently(warnings):
    assert estimate_fps(FRAMES, None) == config.VIDEO_FPS_FALLBACK
    assert estimate_fps(FRAMES, 0.0) == config.VIDEO_FPS_FALLBACK
    assert estimate_fps(0, AUDIO_S) == config.VIDEO_FPS_FALLBACK
    assert warnings.records == []


def test_absurd_rate_falls_back_and_warns(warnings):
    # One second of audio for a two-minute movie: 2743 fps.
    assert estimate_fps(FRAMES, 1.0) == config.VIDEO_FPS_FALLBACK
    assert [r.levelno for r in warnings.records] == [logging.WARNING]
    assert "fallback" in warnings.records[0].getMessage()


def test_audio_much_shorter_than_the_video_falls_back(warnings):
    # A 15 % trimmed tail implies 28.3 fps: plausible in range, but the
    # audio is shorter than 90 % of the video at the fallback rate.
    trimmed = FRAMES / config.VIDEO_FPS_FALLBACK * 0.85
    assert estimate_fps(FRAMES, trimmed) == config.VIDEO_FPS_FALLBACK
    assert [r.levelno for r in warnings.records] == [logging.WARNING]
    assert "shorter than the video" in warnings.records[0].getMessage()


def test_audio_just_below_the_bound_falls_back_and_just_above_is_kept(warnings):
    video_s = FRAMES / config.VIDEO_FPS_FALLBACK
    assert estimate_fps(FRAMES, video_s * 0.89) == config.VIDEO_FPS_FALLBACK
    # A 5 % trim is within the bound: the (slightly high) estimate stands
    # and the runner's stall watchdog is the net for the short duration.
    kept = estimate_fps(FRAMES, video_s * 0.95)
    assert kept != config.VIDEO_FPS_FALLBACK
    assert kept == pytest.approx(FRAMES / (video_s * 0.95))


def test_rates_near_the_fallback_are_trusted_faster_ones_are_not(warnings):
    # The bound is relative to the fallback rate, which is the rate the
    # asset is expected to have: a 25 fps take (audio 4 % shorter than the
    # video at 24 fps) is accepted, a 30 fps take (20 % shorter) is not
    # told apart from a trimmed tail and falls back — the fallback's longer
    # duration keeps the table reachable, which is the property that matters.
    assert estimate_fps(2500, 100.0) == 25.0
    assert warnings.records == []
    assert estimate_fps(3000, 100.0) == config.VIDEO_FPS_FALLBACK
    assert len(warnings.records) == 1


def test_fallback_warns_once_then_logs_debug(warnings):
    trimmed = FRAMES / config.VIDEO_FPS_FALLBACK * 0.5
    estimate_fps(FRAMES, trimmed)
    estimate_fps(FRAMES, trimmed)
    estimate_fps(FRAMES, 1.0)
    levels = [r.levelno for r in warnings.records]
    assert levels == [logging.WARNING, logging.DEBUG, logging.DEBUG]


def test_fallback_duration_covers_the_whole_beat_table():
    # With the fallback rate the clock ceiling is the movie's full length,
    # so a beat table timed to the video can always reach its last clip end.
    fps = estimate_fps(FRAMES, FRAMES / config.VIDEO_FPS_FALLBACK * 0.5)
    duration_ms = int(round(FRAMES / fps * 1000.0))
    assert duration_ms == pytest.approx(FRAMES / config.VIDEO_FPS_FALLBACK * 1000, abs=1)
    assert frame_index_for_ms(duration_ms, fps, FRAMES) == FRAMES
