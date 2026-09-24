# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The video card glides between targets, reveals its controls on demand
and fades in on start (``core/tour/card_motion.py``, pure Python)."""

import sys
from unittest.mock import MagicMock

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock(name="requests")

import pytest  # noqa: E402

from mixar.modules.onboarding.core.tour import config  # noqa: E402
from mixar.modules.onboarding.core.tour.card_motion import CardMotion  # noqa: E402

A = (10.0, 20.0, 310.0, 190.0)
B = (500.0, 400.0, 1060.0, 715.0)
DT = 1.0 / 30.0


def test_first_target_snaps_without_a_glide():
    m = CardMotion()
    assert m.rect is None
    assert m.step(DT, A, False)
    assert m.rect == A and m.settled


def test_new_target_is_approached_exponentially_then_snaps():
    m = CardMotion()
    m.step(DT, A, False)
    m.step(DT, B, False)
    assert m.rect != A and m.rect != B
    for cur, a, b in zip(m.rect, A, B):
        assert min(a, b) <= cur <= max(a, b)
    ticks = 0
    while not m.settled and ticks < 300:
        m.step(DT, B, False)
        ticks += 1
    assert m.rect == B
    # ~8/s rate: within 0.5 px of a 560 px move needs ~0.9 s, not seconds.
    assert ticks < 45


def test_a_settled_card_reports_no_change():
    m = CardMotion()
    m.step(DT, A, False)
    for _ in range(int(2.0 / DT)):
        m.step(DT, A, False)
    assert m.alpha == 1.0 and m.controls_alpha == 0.0
    assert m.step(DT, A, False) is False


def test_controls_reveal_and_hide_with_easing():
    m = CardMotion()
    m.step(DT, A, True)
    first = m.controls_alpha
    assert 0.0 < first < 1.0
    for _ in range(60):
        m.step(DT, A, True)
    assert m.controls_alpha == 1.0
    m.step(DT, A, False)
    assert 0.0 < m.controls_alpha < 1.0
    for _ in range(60):
        m.step(DT, A, False)
    assert m.controls_alpha == 0.0


def test_card_fades_in_over_card_fade_seconds():
    m = CardMotion()
    assert m.alpha == 0.0
    steps = 0
    while m.alpha < 1.0 and steps < 1000:
        m.step(DT, A, False)
        steps += 1
    assert m.alpha == 1.0
    assert steps * DT == pytest.approx(config.CARD_FADE_SECONDS, abs=DT * 1.5)


def test_reset_forgets_everything():
    m = CardMotion()
    m.step(DT, A, True)
    m.fade_out()
    m.reset()
    assert m.rect is None and m.target is None
    assert m.alpha == 0.0 and m.controls_alpha == 0.0
    assert not m.fading_out and not m.faded_out


def test_fade_out_eases_alpha_to_zero_then_reports_faded_out():
    m = CardMotion()
    for _ in range(60):
        m.step(DT, A, False)
    assert m.alpha == 1.0 and not m.faded_out
    m.fade_out()
    assert m.fading_out and not m.faded_out      # nothing moves until a step
    assert m.step(DT, A, False) is True
    assert 0.0 < m.alpha < 1.0
    steps = 1
    while not m.faded_out and steps < 1000:
        assert m.step(DT, A, False) is True       # still changing
        steps += 1
    assert m.faded_out and m.alpha == 0.0
    assert steps * DT == pytest.approx(config.CARD_FADE_OUT_SECONDS, abs=DT * 1.5)
    # Settled at nothing: no more changes, and the fade-in never restarts.
    assert m.step(DT, A, False) is False
    assert m.alpha == 0.0


def test_fade_out_is_idempotent_and_wins_over_a_pending_fade_in():
    m = CardMotion()
    m.step(DT, A, False)                          # alpha barely above 0
    m.fade_out()
    m.fade_out()
    m.step(DT, A, False)
    assert m.fading_out
    for _ in range(60):
        m.step(DT, A, False)
    assert m.faded_out
