# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding State Machine

Reads and writes the two ``WindowManager`` properties that own the
session-scoped onboarding state. Using ``WindowManager`` (instead
of a Python singleton) gives us:

* Automatic reset on Blender restart — the "temporary opt-out"
  semantic comes for free.
* Inspectability from the Python console / devtools.
* Survival across module reloads during development.

Every transition funnels through ``transition_to``, which lets
``tour_driver.apply_step`` handle the side effects.
"""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.analytics.constants import (
    EVENT_ONBOARDING_FINISHED,
    EVENT_ONBOARDING_STARTED,
    EVENT_ONBOARDING_STEP,
)
from mixar.modules.onboarding.constants import (
    DEFAULT_STEP,
    STEP_COMPLETION,
    STEP_DONE,
    WM_PROP_OPTED_OUT,
    WM_PROP_STEP,
)
from mixar.modules.onboarding.core.steps import get_step

logger = get_logger(__name__)


def _capture_funnel(event: str, properties: dict, context=None) -> None:
    """Telemetry only — onboarding must never break because of it."""
    try:
        from mixar.modules.common.analytics.capture import capture
        capture(event, properties, context=context)
    except Exception as exc:
        logger.debug("Onboarding: telemetry capture skipped: %s", exc)


def _wm(context=None):
    return (context or bpy.context).window_manager


def get_step_id(context=None) -> str:
    return getattr(_wm(context), WM_PROP_STEP, DEFAULT_STEP) or DEFAULT_STEP


def set_step_id(step_id: str, context=None) -> None:
    setattr(_wm(context), WM_PROP_STEP, step_id)


def is_opted_out(context=None) -> bool:
    return bool(getattr(_wm(context), WM_PROP_OPTED_OUT, False))


def set_opted_out(value: bool, context=None) -> None:
    setattr(_wm(context), WM_PROP_OPTED_OUT, bool(value))


def transition_to(step_id: str, context=None) -> None:
    """Move the flow to ``step_id`` and let the tour driver handle
    side effects (sidebar tab switch, dialog invocation)."""
    from mixar.modules.onboarding.core import tour_driver

    previous = get_step_id(context)
    set_step_id(step_id, context)
    logger.info("Onboarding: %s → %s", previous, step_id)

    _capture_funnel(EVENT_ONBOARDING_STEP, {
        "from_step": previous,
        "to_step": step_id,
    }, context)

    # Reaching DONE means the tour is over for this user — record
    # them in the seen-list so it doesn't open again on next launch.
    # Both completion (advance from COMPLETION → DONE) and skip_tour
    # funnel through here, so this single hook covers both exits.
    if step_id == STEP_DONE and previous != STEP_DONE:
        try:
            completed = previous == STEP_COMPLETION and not is_opted_out(context)
        except Exception:
            completed = False
        _capture_funnel(EVENT_ONBOARDING_FINISHED, {
            "outcome": "completed" if completed else "skipped",
            "last_step": previous,
        }, context)
        _mark_current_user_seen(context)

    tour_driver.apply_step(step_id, context)


def _mark_current_user_seen(context=None) -> None:
    """Persist a 'seen onboarding' marker for the currently signed-in
    user. The email comes from ``scene.mixie_chat_user_id`` which the
    auth flow populates on every successful sign-in."""
    try:
        scene = (context or bpy.context).scene
        email = getattr(scene, "mixie_chat_user_id", "") if scene else ""
        if not email:
            return
        from mixar.modules.onboarding.core import persistence
        persistence.mark_user_seen_onboarding(email)
    except Exception as exc:
        logger.debug("Onboarding: mark-seen skipped: %s", exc)


def advance(context=None) -> None:
    """Continue from the current step to its declared next step."""
    current = get_step_id(context)
    step = get_step(current)
    if step is None:
        logger.warning("Onboarding: advance() from unknown step %r", current)
        return
    next_id = step.continue_step
    if next_id == current:
        return
    transition_to(next_id, context)


def go_back(context=None) -> None:
    """Return from the current step to its declared previous step."""
    current = get_step_id(context)
    step = get_step(current)
    if step is None:
        logger.warning("Onboarding: go_back() from unknown step %r", current)
        return
    prev_id = step.back_step
    if not prev_id or prev_id == current:
        return
    transition_to(prev_id, context)


def skip_tour(context=None) -> None:
    """Mark opted-out and park at DONE for the rest of the session."""
    set_opted_out(True, context)
    transition_to(STEP_DONE, context)


def reset(context=None) -> None:
    """Clear all onboarding state without rendering anything."""
    from mixar.modules.onboarding.core import tour_driver
    from mixar.modules.onboarding.core.overlay import (
        overlay_renderer,
        overlay_state,
    )

    tour_driver.cancel_active_pollers()
    overlay_state.clear()
    overlay_renderer.tag_redraw_all()
    set_opted_out(False, context)
    set_step_id(DEFAULT_STEP, context)
    tour_driver.redraw_moodboard_regions()
    logger.debug("Onboarding: state reset")


def begin(context=None) -> None:
    """Convenience used by Bootstrap: ensure state is sane (DEFAULT
    step, not opted out) before opening the welcome dialog. Tags
    every viewport for redraw so the dim film appears at the same
    instant the welcome popup does."""
    from mixar.modules.onboarding.core.overlay import (
        overlay_renderer,
        overlay_state,
    )

    try:
        restarted = get_step_id(context) != DEFAULT_STEP
    except Exception:
        restarted = False
    _capture_funnel(EVENT_ONBOARDING_STARTED, {"restarted": restarted}, context)

    set_step_id(DEFAULT_STEP, context)
    set_opted_out(False, context)
    overlay_state.clear()
    overlay_renderer.tag_redraw_all()
