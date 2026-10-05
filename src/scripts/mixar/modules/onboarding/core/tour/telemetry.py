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
enum, elapsed seconds and two language codes — never text, paths or scene
content. Each call swallows its own errors so telemetry can never break
the tour.

``started`` carries ``language`` (the code the user chose) and
``narration`` (the code actually playing: ``en`` while a language pack is
still missing, so the two together measure how often a pack was ready in
time).
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


def started(tour_id: str, language: str = "en", narration: str = "en", *,
            tour_run_id: str = "") -> None:
    """The tour modal began playing ``tour_id`` for a user who chose
    ``language``, narrated in ``narration`` (both tour language codes)."""
    try:
        from mixar.modules.common.analytics.constants import EVENT_TOUR_STARTED

        properties = {
            "tour_id": str(tour_id),
            "language": str(language or "en"),
            "narration": str(narration or "en"),
        }
        if tour_run_id:
            properties['tour_run_id'] = str(tour_run_id)
        _capture(EVENT_TOUR_STARTED, properties)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Tour telemetry started failed: %s", exc)


def step(tour_id: str, beat_id: str, index: int, *, tour_run_id: str = "") -> None:
    """The runner entered beat ``beat_id`` (``index`` in the table)."""
    try:
        from mixar.modules.common.analytics.constants import EVENT_TOUR_STEP

        properties = {
            "tour_id": str(tour_id),
            "beat_id": str(beat_id),
            "index": int(index),
        }
        if tour_run_id:
            properties['tour_run_id'] = str(tour_run_id)
        _capture(EVENT_TOUR_STEP, properties)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Tour telemetry step failed: %s", exc)


def finished(tour_id: str, outcome: str, beat_id: str, elapsed_s: float, *,
             tour_run_id: str = "", step_index: int = -1) -> None:
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
        properties = {
            "tour_id": str(tour_id),
            "outcome": outcome,
            "beat_id": str(beat_id),
            "elapsed_s": elapsed,
        }
        if tour_run_id:
            properties.update({
                'tour_run_id': str(tour_run_id),
                'step_index': int(step_index),
                'drop_off': outcome != OUTCOME_COMPLETED,
            })
        _capture(EVENT_TOUR_FINISHED, properties)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Tour telemetry finished failed: %s", exc)
