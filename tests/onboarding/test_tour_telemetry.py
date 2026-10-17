# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The interactive tour's telemetry funnel (``core/tour/telemetry.py``):
three content-free events through the shared ``capture``, never raising."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock(name="requests")

import pytest  # noqa: E402

# The package re-exports ``capture`` the function, so reach the module by name.
capture_mod = importlib.import_module("mixar.modules.common.analytics.capture")
from mixar.modules.common.analytics.constants import (  # noqa: E402
    EVENT_TOUR_FINISHED,
    EVENT_TOUR_STARTED,
    EVENT_TOUR_STEP,
    IGNORED_OPERATORS,
)
from mixar.modules.onboarding.core.tour import telemetry  # noqa: E402
from mixar.modules.onboarding.core.tour.config import OP_TOUR  # noqa: E402

ALLOWED_VALUE_TYPES = (str, int, float, bool)


@pytest.fixture
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(capture_mod, "capture",
                        lambda event, properties=None, *, context=None:
                        seen.append((event, dict(properties or {}))))
    return seen


def test_event_names_are_the_tour_funnel():
    assert EVENT_TOUR_STARTED == "onboarding.tour_started"
    assert EVENT_TOUR_STEP == "onboarding.tour_step"
    assert EVENT_TOUR_FINISHED == "onboarding.tour_finished"
    # The modal itself is machinery; the funnel replaces its operator event.
    assert OP_TOUR in IGNORED_OPERATORS


def test_started_step_finished_carry_only_ids_numbers_and_enums(events):
    telemetry.started("mixar-intro", "fr", "en")
    telemetry.step("mixar-intro", "find-island", 3)
    telemetry.finished("mixar-intro", "completed", "outro", 118.26)
    assert events == [
        (EVENT_TOUR_STARTED, {"tour_id": "mixar-intro", "language": "fr", "narration": "en"}),
        (EVENT_TOUR_STEP, {"tour_id": "mixar-intro", "beat_id": "find-island", "index": 3}),
        (EVENT_TOUR_FINISHED, {"tour_id": "mixar-intro", "outcome": "completed",
                               "beat_id": "outro", "elapsed_s": 118.3}),
    ]
    for _name, props in events:
        for key, value in props.items():
            assert isinstance(value, ALLOWED_VALUE_TYPES), key
            assert key not in ("text", "prompt", "path", "label", "caption")


@pytest.mark.parametrize("outcome", ["completed", "exited", "failed"])
def test_finished_outcomes(events, outcome):
    telemetry.finished("t", outcome, "b", 1)
    assert events[-1][1]["outcome"] == outcome


def test_finished_coerces_unknown_outcome_and_bad_elapsed(events):
    telemetry.finished("t", "wandered off", "b", "soon")
    assert events[-1][1]["outcome"] == telemetry.OUTCOME_FAILED
    assert events[-1][1]["elapsed_s"] == 0.0
    telemetry.finished("t", "exited", "b", -5)
    assert events[-1][1]["elapsed_s"] == 0.0


def test_a_capture_failure_never_reaches_the_tour(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("queue on fire")
    monkeypatch.setattr(capture_mod, "capture", boom)
    telemetry.started("t")
    telemetry.step("t", "b", 0)
    telemetry.finished("t", "completed", "b", 2.0)


def test_started_defaults_to_english_for_both_codes(events):
    telemetry.started("t")
    assert events == [(EVENT_TOUR_STARTED, {"tour_id": "t", "language": "en", "narration": "en"})]


def test_replays_have_separate_correlation_and_no_extra_dropoff_event(events):
    for run, outcome in [('first-run', 'exited'), ('replay', 'completed')]:
        telemetry.started('t', tour_run_id=run)
        telemetry.step('t', 'find-island', 3, tour_run_id=run)
        telemetry.finished('t', outcome, 'find-island', 12,
                           tour_run_id=run, step_index=3)
    assert len(events) == 6
    assert {name for name, _ in events} == {
        EVENT_TOUR_STARTED, EVENT_TOUR_STEP, EVENT_TOUR_FINISHED}
    assert [props['tour_run_id'] for _, props in events] == ['first-run'] * 3 + ['replay'] * 3
    assert events[2][1]['drop_off'] is True
    assert events[5][1]['drop_off'] is False
    assert events[2][1]['step_index'] == 3
