# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""What the chat shows for a turn refused over the user's own key.

The backend keeps BYOK metadata only; the key rides every command from this
device (`byok/core/turn_credentials.py`). Three refusals reach the chat
through the command-error path:

- the server's 409 ``byok_key_required`` — BYOK is active for the account
  but the command carried no key (an upgrade from a client that stored keys
  server-side, a second machine); its detail names the account's
  ``provider`` and ``model``;
- the client's own Codex refusals (``byok_codex_expired`` /
  ``byok_codex_refresh_failed``), raised before anything was sent.

Each becomes a desktop-owned card (`byok_card`): ONE provider-specific line
and two actions — enter the credential (AI Provider Settings, prefilled,
then the message is resent) or switch to Mixar credits (remove the key,
then resend). The server's ``message`` is never shown for the key-missing
case; it is the fallback copy for builds that predate the card.
`refusal_card` is pure so the copy is pinned by tests.

A third family is the sealed transport (`byok/core/transport_seal.py`): a
``byok_transport_key_stale`` that survived `turn_transport`'s one automatic
resend, the server's ``byok_transport_unavailable`` (503), this device's
``byok_transport_unreachable`` fetch failure, and a ``byok_key_unsealed``
(400, an old build sending plaintext). The key on this device is fine in all
of them, so they become a Try-again (resend) card and never touch the
settings card.

The 409 is also the moment this device learns it may hold no usable key:
the settings card is re-derived from the key store
(`_mark_device_key_missing`, unchanged), never flipped blindly. Before the
cold-start credential fetch has landed the turn went out keyless over a key
that may well be here, so nothing is shown: the mirror is refreshed and the
message resent once the fetch lands; a second refusal shows the card.
"""

from dataclasses import dataclass

from mixar.modules.byok.constants import (
    BYOK_CODEX_EXPIRED_CODE,
    BYOK_CODEX_REFRESH_FAILED_CODE,
    BYOK_KEY_REQUIRED_CODE,
    BYOK_KEY_UNSEALED_CODE,
    BYOK_PROVIDER_DISPLAY_NAMES,
    BYOK_TRANSPORT_KEY_STALE_CODE,
    BYOK_TRANSPORT_UNAVAILABLE_CODE,
    BYOK_TRANSPORT_UNREACHABLE_CODE,
    CODEX_PROVIDER_ID,
    LOCAL_PROVIDER_ID,
)
from mixar.modules.byok.core import codex_auth, key_prompt
from mixar.modules.common.i18n import n_, rpt_

# Primary-button actions (`byok_card` maps them to clicks).
ACTION_ENTER = "enter"
ACTION_RESEND = "resend"

_WHY_LINE = n_("Mixar never keeps your key on its servers. It stays only on the computer where you enter it.")
_CREDITS_LABEL = n_("Use Mixar credits instead")

# Sealed-transport refusals (`byok/core/transport_seal.py`): the key on this
# device is fine, so they become a Try-again (resend) card and never touch the
# "Key needed on this device" settings card.
_UNSEALED_FALLBACK = n_("The key for this request was not sealed for Mixar. Update Mixar and try again.")
_TRANSPORT_RETRY_LINE = n_("Couldn't secure your key for this request — try again in a moment.")
_TRANSPORT_CODES = (
    BYOK_TRANSPORT_KEY_STALE_CODE,      # the one automatic resend already happened
    BYOK_TRANSPORT_UNAVAILABLE_CODE,    # the server has no sealing key (503)
    BYOK_TRANSPORT_UNREACHABLE_CODE,    # this device could not fetch it
)


@dataclass(frozen=True)
class RefusalCard:
    code: str
    line: str                 # translated, one line
    primary_label: str        # translated button text
    primary_action: str       # ACTION_ENTER | ACTION_RESEND
    provider: str = ""        # dialog prefill (ACTION_ENTER)
    model: str = ""
    focus: str = key_prompt.FOCUS_KEY

    @property
    def credits_label(self) -> str:
        return rpt_(_CREDITS_LABEL)

    @property
    def why_line(self) -> str:
        return rpt_(_WHY_LINE)


def byok_error_code(result, data) -> str:
    """The BYOK code on a command error, or ''.

    Over the socket a server 409 arrives as the JSON-RPC error's ``data``
    (``{status_code: 409, code: "byok_key_required", provider, model,
    message}``); the receipt path repeats it at the top level; the client's
    own refusal puts the code under ``data`` only.
    """
    code = _field(result, data, 'code')
    return code if code.startswith('byok_') else ''


def _field(result, data, name) -> str:
    for source in (data, result):
        value = source.get(name) if isinstance(source, dict) else None
        if isinstance(value, str) and value:
            return value
    return ''


def provider_display_name(provider: str) -> str:
    provider = (provider or '').strip()
    return BYOK_PROVIDER_DISPLAY_NAMES.get(provider.lower()) or provider.capitalize()


def refusal_card(result, data):
    """The card for a BYOK refusal, or None when this is not one.

    Keyed on the ``byok_*`` code alone: a 409 without it (a future conflict
    on chat/input) is not BYOK and must not touch the settings card.
    """
    code = byok_error_code(result, data)
    if not code:
        return None
    message = _field(result, data, 'message')
    if code == BYOK_KEY_REQUIRED_CODE:
        provider = _field(result, data, 'provider').lower()
        model = _field(result, data, 'model')
        if not provider:
            provider, model = _mirror_provider_model()
        if provider == CODEX_PROVIDER_ID:
            return RefusalCard(code, rpt_("Link your ChatGPT sign-in to continue"),
                               rpt_("Link sign-in"), ACTION_ENTER, provider, model,
                               key_prompt.FOCUS_CODEX_PATH)
        if provider == LOCAL_PROVIDER_ID:
            return RefusalCard(code, rpt_("Enter your local model's token to continue"),
                               rpt_("Enter token"), ACTION_ENTER, provider, model,
                               key_prompt.FOCUS_LOCAL_KEY)
        line = rpt_("Enter your {provider} API key to continue").format(
            provider=provider_display_name(provider))
        return RefusalCard(code, line, rpt_("Enter key"), ACTION_ENTER, provider, model)
    if code == BYOK_CODEX_EXPIRED_CODE:
        line = rpt_("Sign in to Codex again to continue")
        reason = _CODEX_REASONS.get(message)
        if reason:
            line = f"{line} — {rpt_(reason)}"
        return RefusalCard(code, line, rpt_("Sign in to Codex"), ACTION_ENTER,
                           CODEX_PROVIDER_ID, "", key_prompt.FOCUS_CODEX_PATH)
    if code == BYOK_CODEX_REFRESH_FAILED_CODE:
        if message == codex_auth.MSG_FILE_NOT_WRITABLE:
            return RefusalCard(code, rpt_("Your Codex sign-in file is not writable — fix its "
                                          "permissions or sign in to Codex again to continue"),
                               rpt_("Sign in to Codex"), ACTION_ENTER,
                               CODEX_PROVIDER_ID, "", key_prompt.FOCUS_CODEX_PATH)
        return RefusalCard(code, rpt_("Couldn't renew your Codex sign-in — check your connection"),
                           rpt_("Try again"), ACTION_RESEND)
    if code in _TRANSPORT_CODES:
        # The key on this device is fine; a manual retry refetches the sealing
        # key and resends. Never touches the settings card.
        line = rpt_(message) if message else rpt_(_TRANSPORT_RETRY_LINE)
        return RefusalCard(code, line, rpt_("Try again"), ACTION_RESEND)
    if code == BYOK_KEY_UNSEALED_CODE:
        # Only an old build (or not Mixar) sends plaintext; the server's line
        # already says to update.
        line = rpt_(message) if message else rpt_(_UNSEALED_FALLBACK)
        return RefusalCard(code, line, rpt_("Try again"), ACTION_RESEND)
    return None


# Short reasons appended to the Codex sign-in line, keyed on the raw
# (untranslated) message the client's refusal carries.
_CODEX_REASONS = {
    codex_auth.MSG_FILE_MISSING: n_("no Codex sign-in was found"),
    codex_auth.MSG_FILE_UNREADABLE: n_("the sign-in file could not be read"),
}


def _mirror_provider_model():
    try:
        from mixar.modules.byok.core import credential_state
        state = credential_state.snapshot()
        return (state.get("byok_current_provider") or "").lower(), state.get("byok_current_model") or ""
    except Exception:  # noqa: BLE001 — the card still draws without a provider
        return "", ""


def present_refusal(result, data, scene) -> bool:
    """Handle a BYOK refusal on ``scene``: show the card, or — cold start —
    refresh the mirror and resend once it lands. False when the error is
    not a BYOK refusal (the caller shows it as usual)."""
    card = refusal_card(result, data)
    if card is None:
        return False
    from . import byok_card
    session_id = getattr(scene, 'mixie_session_id', '') or ''
    if card.code == BYOK_KEY_REQUIRED_CODE:
        if _cold_start_resend(session_id, card):
            return True
        _mark_device_key_missing()
    byok_card.show(scene, card)
    return True


def _cold_start_resend(session_id, card) -> bool:
    """Before the first credential fetch has landed, the turn went out
    keyless because the mirror still read "inactive". Refresh it and resend
    the message when it lands — once. Returns True when that was armed."""
    from mixar.modules.byok.core import credential_state

    from . import byok_card, byok_resend
    if credential_state.snapshot().get("byok_state_loaded"):
        return False
    record = byok_resend.pending(session_id)
    if record is None or record.auto_resent:
        return False

    def _landed(loaded: bool):
        if loaded and byok_resend.resend(session_id, automatic=True):
            return
        scene = byok_resend._scene_for(session_id)
        if scene is not None:
            _mark_device_key_missing()
            byok_card.show(scene, card)

    credential_state.on_next_fetch(_landed)
    credential_state.refresh()
    return True


def _mark_device_key_missing() -> None:
    try:
        from mixar.modules.byok.core import credential_state, key_store

        state = credential_state.snapshot()
        if not state.get("byok_state_loaded"):
            credential_state.refresh()
            return
        key_store.check_presence_async(
            state.get("byok_current_provider") or "", credential_state.set_device_key_missing,
        )
    except Exception:  # noqa: BLE001 — a mirror miss must not eat the card
        pass
