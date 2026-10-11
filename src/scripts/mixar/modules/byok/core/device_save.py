# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Save a BYOK config whose key stays on this computer.

Every save path in the AI Provider Settings dialog ends here:

1. the key goes into the OS keychain (``key_vault``) first — the previous key
   for that provider is remembered;
2. ``PUT /agent/byok`` carries ``key_location="device"``, a masked label and
   this app's agent connection id, never the key;
3. the backend validates through that connection, so the relay
   (``cloud_relay``) answers its probe with the key just stored;
4. if the save fails, the previous key is put back (or the new one removed);
   if it succeeds, keys for other providers are removed — so the keychain
   always matches the one config the backend holds.

Codex stores nothing: the Codex CLI login is read in place for each call.
No bpy imports beyond the main-thread callback the caller supplies.
"""

from __future__ import annotations

from typing import Callable, Optional

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from . import byok_client, codex_cli_login, key_vault

logger = get_logger(__name__)

MSG_SIGN_IN = n_("Sign in to Mixar first — keys are kept per account on this computer.")
MSG_CONNECT = n_(
    "Mixar is not connected to the agent yet — wait a moment and try again."
)
MSG_KEYCHAIN = n_(
    "Couldn't save the key in your system keychain. Unlock it and try again."
)


def _app_connection_id() -> Optional[str]:
    try:
        from mixar.modules.space_mixie_chat.core.connection_manager import (
            get_connection_manager,
        )
        manager = get_connection_manager()
        if not manager.is_connected:
            return None
        return manager.instance_id or None
    except Exception:  # noqa: BLE001 — stripped builds / not initialised
        return None


def save(
    provider: str,
    model: str,
    key: str,
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
    *,
    base_url: Optional[str] = None,
    supports_vision: Optional[bool] = None,
) -> Optional[str]:
    """Start the save; returns a user-facing error msgid, or None if started.

    ``key`` is the API key (or the local server's optional bearer token);
    ignored for Codex. ``on_done`` runs on the main thread like
    ``byok_client.save_credentials``'s callback.
    """
    key = (key or "").strip()
    instance_id = _app_connection_id()
    if instance_id is None:
        return MSG_CONNECT

    preview: Optional[str] = None
    restore: Optional[Callable[[], None]] = None
    if provider == "codex":
        try:
            codex_cli_login.read()
        except codex_cli_login.CodexLoginError as e:
            return str(e)
    elif key or provider != "local":
        if not key_vault.has_account():
            return MSG_SIGN_IN
        previous = key_vault.get_key(provider)
        if not key_vault.store_key(provider, key):
            return MSG_KEYCHAIN
        preview = key_vault.mask(key)

        def restore() -> None:
            if previous:
                key_vault.store_key(provider, previous)
            else:
                key_vault.delete_key(provider)
    else:
        # Local server without a bearer token: nothing to keep. Drop an old
        # token only once the backend has accepted the new config.
        restore = None

    def _done(success: bool, data, err) -> None:
        if not success:
            if restore is not None:
                restore()
        else:
            # Keep only the active config's key (none for Codex, or for a
            # local server without a bearer token).
            keep = provider if key and provider != "codex" else None
            key_vault.delete_all_except(keep)
        on_done(success, data, err)

    byok_client.save_credentials(
        provider=provider,
        model=model,
        api_key=None,
        base_url=base_url,
        supports_vision=supports_vision,
        key_location="device",
        key_preview=preview,
        instance_id=instance_id,
        on_done=_done,
    )
    return None
