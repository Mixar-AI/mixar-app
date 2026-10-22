# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the telemetry funnel.

Content-free events, one per stage, through the shared analytics
``capture`` (consent-gated, auth-gated, fail-open): ``started`` when the
modal begins, ``step`` on every beat entry, ``finished`` once with how the
tour ended, plus ``seen_state_error`` when the per-device seen file cannot
be read or written. Properties are the tour id, beat ids and indices, small
enums, elapsed seconds and two language codes — never text, paths or scene
content. Each call swallows its own errors so telemetry can never break
the tour.

``started`` carries ``language`` (the code the user chose) and
``narration`` (the code actually playing: ``en`` while a language pack is
still missing, so the two together measure how often a pack was ready in
time). ``started`` and ``finished`` carry ``start_source`` (what opened the
tour); ``finished`` carries the raw ``stop_reason`` beside its ``outcome``.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# ``finished`` outcomes.
OUTCOME_COMPLETED = "completed"      # the terminal beat ran out
OUTCOME_EXITED = "exited"            # Exit / Escape → Leave
OUTCOME_INTERRUPTED = "interrupted"  # the app, window or file went away; a cancel
OUTCOME_FAILED = "failed"            # the tour broke (an error, a failed start)
OUTCOMES = (OUTCOME_COMPLETED, OUTCOME_EXITED, OUTCOME_INTERRUPTED, OUTCOME_FAILED)

# ``TourSession.stop`` reasons, sent raw as ``stop_reason``.
STOP_COMPLETED = "completed"
STOP_EXITED = "exited"
STOP_QUIT = "quit"                    # the app is quitting (``exit_pre`` ran)
STOP_WINDOW_CLOSED = "window-closed"  # the modal was cancelled outside a quit
STOP_CANCELLED = "cancelled"          # Escape on the loading card; module unload
STOP_HOST_CLOSED = "host-closed"      # the host window lost its viewport
STOP_FILE_LOADED = "file-loaded"      # a .blend load (``load_pre``)
STOP_ERROR = "error"                  # a tick or event raised
STOP_START_FAILED = "start-failed"    # the session could not start
_OUTCOME_BY_REASON = {
    STOP_COMPLETED: OUTCOME_COMPLETED,
    STOP_EXITED: OUTCOME_EXITED,
    STOP_QUIT: OUTCOME_INTERRUPTED,
    STOP_WINDOW_CLOSED: OUTCOME_INTERRUPTED,
    STOP_CANCELLED: OUTCOME_INTERRUPTED,
    STOP_HOST_CLOSED: OUTCOME_INTERRUPTED,
    STOP_FILE_LOADED: OUTCOME_INTERRUPTED,
    STOP_ERROR: OUTCOME_FAILED,
    STOP_START_FAILED: OUTCOME_FAILED,
}
STOP_REASONS = tuple(_OUTCOME_BY_REASON)
STOP_UNKNOWN = "unknown"

# What opened the tour (``mixar.onboarding_tour``'s ``start_source``).
START_SOURCE_AUTO_SIGNIN = "auto_signin"  # the auth-success hook, first run
START_SOURCE_AUTO_MODE = "auto_mode"      # a Zen/Engine choice, first run
START_SOURCE_HELP_MENU = "help_menu"      # Help → Start tour
START_SOURCE_UNKNOWN = "unknown"          # invoked with no source
START_SOURCES = (START_SOURCE_AUTO_SIGNIN, START_SOURCE_AUTO_MODE,
                 START_SOURCE_HELP_MENU, START_SOURCE_UNKNOWN)

# ``seen_state_error`` ops; each is reported once per process.
SEEN_OP_READ = "read"
SEEN_OP_WRITE = "write"
_seen_errors_reported: set = set()


def outcome_for(reason: str) -> str:
    """The ``finished`` outcome of a stop ``reason`` (unknown → failed)."""
    return _OUTCOME_BY_REASON.get(reason, OUTCOME_FAILED)


def _source(start_source: str) -> str:
    return start_source if start_source in START_SOURCES else START_SOURCE_UNKNOWN


def _capture(event: str, properties: dict) -> None:
    try:
        from mixar.modules.common.analytics.capture import capture

        capture(event, properties)
    except Exception as exc:  # noqa: BLE001 - telemetry is fail-open
        logger.debug("Tour telemetry %s failed: %s", event, exc)


def started(tour_id: str, language: str = "en", narration: str = "en", *,
            tour_run_id: str = "", start_source: str = START_SOURCE_UNKNOWN) -> None:
    """The tour modal began playing ``tour_id`` for a user who chose
    ``language``, narrated in ``narration`` (both tour language codes)."""
    try:
        from mixar.modules.common.analytics.constants import EVENT_TOUR_STARTED

        properties = {
            "tour_id": str(tour_id),
            "language": str(language or "en"),
            "narration": str(narration or "en"),
            "start_source": _source(start_source),
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


def finished(tour_id: str, reason: str, beat_id: str, elapsed_s: float, *,
             tour_run_id: str = "", step_index: int = -1,
             start_source: str = START_SOURCE_UNKNOWN) -> None:
    """The tour ended for stop ``reason`` (one of ``STOP_REASONS``; anything
    else is sent as ``unknown`` with outcome ``failed``), on ``beat_id``,
    ``elapsed_s`` wall seconds after ``started``."""
    try:
        from mixar.modules.common.analytics.constants import EVENT_TOUR_FINISHED

        outcome = outcome_for(reason)
        try:
            elapsed = round(max(0.0, float(elapsed_s)), 1)
        except (TypeError, ValueError):
            elapsed = 0.0
        properties = {
            "tour_id": str(tour_id),
            "outcome": outcome,
            "stop_reason": reason if reason in STOP_REASONS else STOP_UNKNOWN,
            "start_source": _source(start_source),
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


def seen_state_error(op: str, exc: BaseException) -> None:
    """Reading/parsing (``op="read"``) or writing (``"write"``) the device's
    seen file failed. Only the exception's type name is sent — its message
    can hold the user's path. Once per op per process."""
    try:
        from mixar.modules.common.analytics.constants import (
            EVENT_ONBOARDING_SEEN_STATE_ERROR,
        )

        if op in _seen_errors_reported:
            return
        _seen_errors_reported.add(op)
        _capture(EVENT_ONBOARDING_SEEN_STATE_ERROR, {
            "op": op if op in (SEEN_OP_READ, SEEN_OP_WRITE) else STOP_UNKNOWN,
            "error": type(exc).__name__[:64],
        })
    except Exception as err:  # noqa: BLE001
        logger.debug("Tour telemetry seen_state_error failed: %s", err)
