# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The interactive tour's telemetry funnel (``core/tour/telemetry.py``):
content-free events through the shared ``capture``, never raising."""

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
    EVENT_ONBOARDING_SEEN_STATE_ERROR,
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
    telemetry.started("mixar-intro", "fr", "en", start_source="auto_signin")
    telemetry.step("mixar-intro", "find-island", 3)
    telemetry.finished("mixar-intro", "completed", "outro", 118.26,
                       start_source="auto_signin")
    assert events == [
        (EVENT_TOUR_STARTED, {"tour_id": "mixar-intro", "language": "fr", "narration": "en",
                              "start_source": "auto_signin"}),
        (EVENT_TOUR_STEP, {"tour_id": "mixar-intro", "beat_id": "find-island", "index": 3}),
        (EVENT_TOUR_FINISHED, {"tour_id": "mixar-intro", "outcome": "completed",
                               "stop_reason": "completed", "start_source": "auto_signin",
                               "beat_id": "outro", "elapsed_s": 118.3}),
    ]
    for _name, props in events:
        for key, value in props.items():
            assert isinstance(value, ALLOWED_VALUE_TYPES), key
            assert key not in ("text", "prompt", "path", "label", "caption")


# Every stop reason the session uses, and the outcome it reports. Quitting
# the app or closing a window mid-tour is an interruption, never a failure.
@pytest.mark.parametrize("reason, outcome", [
    ("completed", "completed"),
    ("exited", "exited"),
    ("quit", "interrupted"),
    ("window-closed", "interrupted"),
    ("cancelled", "interrupted"),
    ("host-closed", "interrupted"),
    ("file-loaded", "interrupted"),
    ("error", "failed"),
    ("start-failed", "failed"),
])
def test_finished_reports_the_raw_reason_and_its_outcome(events, reason, outcome):
    telemetry.finished("t", reason, "b", 1)
    assert events[-1][1]["stop_reason"] == reason
    assert events[-1][1]["outcome"] == outcome
    assert reason in telemetry.STOP_REASONS


def test_every_outcome_is_reachable_and_documented():
    assert set(telemetry.OUTCOMES) == {
        telemetry.outcome_for(reason) for reason in telemetry.STOP_REASONS}


def test_finished_coerces_unknown_reason_and_bad_elapsed(events):
    telemetry.finished("t", "wandered off", "b", "soon")
    assert events[-1][1]["outcome"] == telemetry.OUTCOME_FAILED
    assert events[-1][1]["stop_reason"] == "unknown"
    assert events[-1][1]["elapsed_s"] == 0.0
    telemetry.finished("t", "exited", "b", -5)
    assert events[-1][1]["elapsed_s"] == 0.0


@pytest.mark.parametrize("source", ["auto_signin", "auto_mode", "help_menu", "unknown"])
def test_start_source_rides_started_and_finished(events, source):
    telemetry.started("t", start_source=source)
    telemetry.finished("t", "exited", "b", 1, start_source=source)
    assert [props["start_source"] for _name, props in events] == [source, source]


def test_an_unknown_or_missing_start_source_is_unknown(events):
    telemetry.started("t", start_source="")
    telemetry.finished("t", "exited", "b", 1, start_source="/Users/ada/x")
    assert [props["start_source"] for _name, props in events] == ["unknown", "unknown"]


def test_seen_state_error_sends_the_type_name_once_per_op(events, monkeypatch):
    monkeypatch.setattr(telemetry, "_seen_errors_reported", set())
    secret = PermissionError(13, "Permission denied", "/Users/ada/onboarding_seen.json")
    telemetry.seen_state_error("read", secret)
    telemetry.seen_state_error("read", ValueError("again"))
    telemetry.seen_state_error("write", OSError("disk full at /Users/ada"))
    assert events == [
        (EVENT_ONBOARDING_SEEN_STATE_ERROR, {"op": "read", "error": "PermissionError"}),
        (EVENT_ONBOARDING_SEEN_STATE_ERROR, {"op": "write", "error": "OSError"}),
    ]
    assert EVENT_ONBOARDING_SEEN_STATE_ERROR == "onboarding.seen_state_error"


def test_a_capture_failure_never_reaches_the_tour(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("queue on fire")
    monkeypatch.setattr(capture_mod, "capture", boom)
    telemetry.started("t")
    telemetry.step("t", "b", 0)
    telemetry.finished("t", "completed", "b", 2.0)


def test_started_defaults_to_english_for_both_codes(events):
    telemetry.started("t")
    assert events == [(EVENT_TOUR_STARTED, {"tour_id": "t", "language": "en", "narration": "en",
                                            "start_source": "unknown"})]


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


def test_a_cancelled_modal_is_a_quit_only_after_exit_pre(monkeypatch):
    from mixar.modules.onboarding.core.tour import session_lifecycle
    monkeypatch.setattr(session_lifecycle, "_app_exiting", False)
    assert session_lifecycle.cancel_reason() == "window-closed"
    session_lifecycle.note_app_exiting()
    assert session_lifecycle.cancel_reason() == "quit"
