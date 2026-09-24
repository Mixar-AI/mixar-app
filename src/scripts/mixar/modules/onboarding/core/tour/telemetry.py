# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the telemetry funnel.

Three content-free events, one per stage, through the shared analytics
``capture`` (consent-gated, auth-gated, fail-open): ``started`` when the
modal begins, ``step`` on every beat entry, ``finished`` once with how the
tour ended. Properties are the tour id, beat ids and indices, an outcome
enum and elapsed seconds — never text, paths or scene content. Each call
swallows its own errors so telemetry can never break the tour.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# ``finished`` outcomes.
OUTCOME_COMPLETED = "completed"   # the terminal beat ran out
OUTCOME_EXITED = "exited"         # Exit / Escape → Leave
OUTCOME_FAILED = "failed"         # the session gave up (asset, clock, error)
OUTCOMES = (OUTCOME_COMPLETED, OUTCOME_EXITED, OUTCOME_FAILED)


def _capture(event: str, properties: dict) -> None:
    try:
        from mixar.modules.common.analytics.capture import capture

        capture(event, properties)
    except Exception as exc:  # noqa: BLE001 - telemetry is fail-open
        logger.debug("Tour telemetry %s failed: %s", event, exc)


def started(tour_id: str) -> None:
    """The tour modal began playing ``tour_id``."""
    try:
        from mixar.modules.common.analytics.constants import EVENT_TOUR_STARTED

        _capture(EVENT_TOUR_STARTED, {"tour_id": str(tour_id)})
    except Exception as exc:  # noqa: BLE001
        logger.debug("Tour telemetry started failed: %s", exc)


def step(tour_id: str, beat_id: str, index: int) -> None:
    """The runner entered beat ``beat_id`` (``index`` in the table)."""
    try:
        from mixar.modules.common.analytics.constants import EVENT_TOUR_STEP

        _capture(EVENT_TOUR_STEP, {
            "tour_id": str(tour_id),
            "beat_id": str(beat_id),
            "index": int(index),
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug("Tour telemetry step failed: %s", exc)


def finished(tour_id: str, outcome: str, beat_id: str, elapsed_s: float) -> None:
    """The tour ended: ``outcome`` is one of ``OUTCOMES`` (anything else is
    reported as ``failed``), ``beat_id`` the beat it ended on, ``elapsed_s``
    wall seconds since ``started``."""
    try:
        from mixar.modules.common.analytics.constants import EVENT_TOUR_FINISHED

        if outcome not in OUTCOMES:
            outcome = OUTCOME_FAILED
        try:
            elapsed = round(max(0.0, float(elapsed_s)), 1)
        except (TypeError, ValueError):
            elapsed = 0.0
        _capture(EVENT_TOUR_FINISHED, {
            "tour_id": str(tour_id),
            "outcome": outcome,
            "beat_id": str(beat_id),
            "elapsed_s": elapsed,
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug("Tour telemetry finished failed: %s", exc)
