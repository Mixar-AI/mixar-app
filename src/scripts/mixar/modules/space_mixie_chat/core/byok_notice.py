# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Chat copy for a turn refused over the user's own key.

The backend keeps BYOK metadata only; the key rides every command from this
device (`byok/core/turn_credentials.py`). Two refusals reach the chat through
the command-error path:

- the server's 409 ``byok_key_required`` — BYOK is active for the account but
  the command carried no key (this device has none: an upgrade from a client
  that stored keys server-side, or a second machine);
- the client's own Codex refusals (``byok_codex_expired`` /
  ``byok_codex_refresh_failed``), raised before anything was sent.

Both are answered in AI Provider Settings, never by an automatic retry. A
third family is the sealed transport (`byok/core/transport_seal.py`): a
``byok_transport_key_stale`` that survived `turn_transport`'s one automatic
resend, the server's ``byok_transport_unavailable`` (503), this device's
``byok_transport_unreachable`` fetch failure, and a ``byok_key_unsealed``
(400, an old build sending plaintext). The key on this device is fine in all
of them, so they show the message with a retry hint and never touch the
settings card. The 409 is also the moment this device learns it may hold no usable key: the
settings card is re-derived from the key store (`check_presence_async`),
never flipped blindly — and when the cold-start credential fetch has not
landed yet (the turn went out keyless because the mirror still read
"inactive") the mirror is refreshed instead, which derives the card state
once the fetch lands.
"""

from mixar.modules.byok.constants import (
    BYOK_CODEX_EXPIRED_CODE,
    BYOK_CODEX_REFRESH_FAILED_CODE,
    BYOK_KEY_REQUIRED_CODE,
    BYOK_KEY_UNSEALED_CODE,
    BYOK_TRANSPORT_KEY_STALE_CODE,
    BYOK_TRANSPORT_UNAVAILABLE_CODE,
    BYOK_TRANSPORT_UNREACHABLE_CODE,
)
from mixar.modules.common.i18n import rpt_

_SETTINGS_HINT = "Open AI Provider Settings (profile menu) to add your key on this device."
_RETRY_HINT = "Your key on this device is unchanged — try again in a moment."
_UNSEALED_FALLBACK = "The key for this request was not sealed for Mixar. Update Mixar and try again."
# Sealed-transport refusals: the key on this device is fine, nothing to add
# in settings, so none of these touch the "Key needed on this device" card.
_TRANSPORT_CODES = (
    BYOK_TRANSPORT_KEY_STALE_CODE,      # the one automatic resend already happened
    BYOK_TRANSPORT_UNAVAILABLE_CODE,    # the server has no sealing key (503)
    BYOK_TRANSPORT_UNREACHABLE_CODE,    # this device could not fetch it
)


def byok_error_code(result, data) -> str:
    """The BYOK code on a command error, or ''.

    Over the socket a server 409 arrives as the JSON-RPC error's ``data``
    (``{status_code: 409, code: "byok_key_required", message}``); the
    receipt path repeats it at the top level; the client's own refusal puts
    the code under ``data`` only.
    """
    for source in (data, result):
        code = source.get('code') if isinstance(source, dict) else None
        if isinstance(code, str) and code.startswith('byok_'):
            return code
    return ''


def byok_error_message(result, data, status_code=None):
    """The chat line for a BYOK refusal, or None when this is not one.

    Keyed on the ``byok_*`` code alone: the server always sends
    ``code: "byok_key_required"`` with its 409, and a 409 without it (a
    future conflict on chat/input) must not flip the settings card to "Key
    needed on this device" for a platform-credit user.
    """
    code = byok_error_code(result, data)
    if not code:
        return None
    message = (result.get('message') or '').strip()
    if code == BYOK_KEY_REQUIRED_CODE:
        _mark_device_key_missing()
        return f"{message or rpt_('Your API key is needed on this device.')} {rpt_(_SETTINGS_HINT)}"
    if code == BYOK_CODEX_EXPIRED_CODE:
        return f"{rpt_(message)} {rpt_(_SETTINGS_HINT)}" if message else rpt_(_SETTINGS_HINT)
    if code == BYOK_CODEX_REFRESH_FAILED_CODE:
        return f"{rpt_(message)} {rpt_(_RETRY_HINT)}" if message else rpt_(_RETRY_HINT)
    if code in _TRANSPORT_CODES:
        return f"{rpt_(message)} {rpt_(_RETRY_HINT)}" if message else rpt_(_RETRY_HINT)
    if code == BYOK_KEY_UNSEALED_CODE:
        # Only an old build (or not Mixar) sends plaintext; the server's line
        # already says to update.
        return rpt_(message) if message else rpt_(_UNSEALED_FALLBACK)
    return None


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
    except Exception:  # noqa: BLE001 — a mirror miss must not eat the message
        pass
