# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers of the AI Provider Settings operators (byok_ops, 500-line rule):
the account-busy gate the dialog shares with the island, the dialog's
prefill sources, and the toast a request owes when its dialog is gone."""

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ...core import byok_client, credential_state, model_suggestions, preference_state

logger = get_logger(__name__)

TURN_IN_FLIGHT_MESSAGE = n_("Wait for the current reply to finish, then change the model.")


def turn_in_flight(context) -> bool:
    """An agent turn is streaming / waiting on input in this scene, or a run
    is still open (workers building after the orchestrator answered "in
    progress"). The backend binds a turn's key and model when the turn
    starts, so a switch, pause or resume now would apply only to the NEXT
    message while the island claimed otherwise — the chip would name a model
    the running turn is not on, or the thumb would sit on Mixie while a key
    run keeps streaming on the key. Every scene tab counts: a turn streaming
    in another tab runs on the same account key. False when the chat module
    is unavailable."""
    try:
        from mixar.modules.space_mixie_chat.constants import SessionState
        from mixar.modules.space_mixie_chat.core.session import get_session_manager

        session = get_session_manager()
        scene = getattr(context, "scene", None)
        if scene is not None:
            if session.get_state(scene) in (SessionState.BUSY, SessionState.MODIFYING,
                                            SessionState.AWAITING_INPUT):
                return True
            if session.run_open(scene):
                return True
        # Any other tab with a live turn or an open run (the registry the
        # script executor gates on).
        return bool(session.has_active_session())
    except Exception as exc:  # noqa: BLE001 — a gate must never break a click
        logger.debug("BYOK turn gate skipped: %s", exc)
        return False


def account_busy() -> bool:
    """Another change of the key or the pick is in flight: an island toggle /
    model switch, a save / removal sent from a dialog closed mid-request, or a
    hosted pick (whose echo / revert would put the old byok_active back over
    this save's). One at a time, so no late answer undoes another."""
    return bool(credential_state.pending() or byok_client.mutation_in_flight()
                or preference_state.mutation_pending())


def saved_provider_model(wm):
    """(provider, model) of the key in use, else of the key paused on this
    computer (`credential_state.resume_target`), else ("", "")."""
    if wm.byok_is_active:
        return wm.byok_current_provider or "", wm.byok_current_model or ""
    return credential_state.resume_target()


def toast_if_closed(dialog_open, title, err):
    """A request whose dialog was closed (Esc) still owes the user its
    failure; an open dialog shows it inline."""
    if dialog_open:
        return
    try:
        from mixar.modules.common.notifications import get_notification_store

        get_notification_store().push(
            "error", title, body=err or n_("Please try again."), ttl_ms=8000,
            id="byok_request_failed",
        )
    except Exception:  # noqa: BLE001 — the log line already records it
        pass


def prefill_from_prompt(wm, prompt):
    """Apply a key-missing card's prefill (`core/key_prompt`), if any. A
    provider or model the catalog does not list yet is skipped — the row
    keeps whatever the mirror prefilled above."""
    if not prompt:
        return
    provider, model = prompt.get("provider") or "", prompt.get("model") or ""
    try:
        if provider:
            wm.byok_form_provider = provider
        if model and model_suggestions.is_openrouter(provider):
            wm.byok_form_openrouter_model = model
        elif model and not model_suggestions.is_local(provider):
            wm.byok_form_model = model
    except TypeError:
        logger.debug("Key prompt prefill skipped — provider or model not in the catalog yet")


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
