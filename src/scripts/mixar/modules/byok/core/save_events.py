# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How an AI Provider Save ended — one ``ui.action`` (feature ``byok``,
action ``save``) per Save.

The operator's own result only says whether a request left: ``FINISHED``
is not a usable key (validation is asynchronous) and ``CANCELLED`` hides why.
This event carries the outcome — ``refused`` before any request, then
``saved`` or ``failed`` once the request answers — with a fixed reason code
and the provider id. Never a key, a path, a URL or a model name.
"""

import functools
import re

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_PROVIDER = re.compile(r"^[a-z0-9_]{1,32}$")


def report(outcome: str, provider: str, reason: str = "") -> None:
    """Queue the event; never raises into the Save path."""
    try:
        from mixar.modules.common.analytics.capture import capture
        from mixar.modules.common.analytics.constants import EVENT_UI_ACTION

        provider = provider if isinstance(provider, str) and _PROVIDER.match(provider) else "other"
        capture(EVENT_UI_ACTION, {
            "feature": "byok", "action": "save", "outcome": outcome,
            "provider": provider, "reason": reason or None,
        })
    except Exception as exc:  # noqa: BLE001 - telemetry must not break a Save
        logger.debug("BYOK save event not queued: %s", exc)


#: The Save operator's own refusal messages (msgids) -> reason.
_FORM_REFUSALS = {
    "Pick a provider.": "provider_missing",
    "Pick a model.": "model_missing",
    "Enter your API key.": "key_missing",
    "Enter a model slug and your key.": "fields_missing",
    "Choose a Codex model.": "model_missing",
}


def refusal_reason(wm) -> str:
    """Why a Save just returned CANCELLED, from the error it showed."""
    if getattr(wm, "byok_dialog_state", "") != "ERROR":
        return "busy"  # the in-flight guard: a save or removal is still running
    message = getattr(wm, "byok_last_error", "")
    from . import local_provider
    reason = _FORM_REFUSALS.get(message) or local_provider.refusal_reason(message)
    if reason:
        return reason
    provider = getattr(wm, "byok_form_provider", "")
    if provider == "codex":
        return "codex_sign_in"
    if provider == "local":
        return "local_custom_invalid" if getattr(wm, "byok_form_local_mode", "") == "CUSTOM" else "local_stopped"
    return "refused"


def reporting_refusals(execute):
    """Decorates the Save operator's ``execute``: a refused Save reports why."""
    @functools.wraps(execute)
    def _execute(self, context):
        result = execute(self, context)
        if "CANCELLED" in result:
            wm = context.window_manager
            report("refused", getattr(wm, "byok_form_provider", ""), refusal_reason(wm))
        return result
    return _execute


def reporting(on_done, provider: str):
    """``on_done`` for one save request that first reports how it ended."""
    def _done(success, data, err):
        from . import local_provider
        report("saved" if success else "failed", provider, "" if success else
               local_provider.refusal_reason(err) or ("device_store" if data else "request_failed"))
        on_done(success, data, err)
    return _done
