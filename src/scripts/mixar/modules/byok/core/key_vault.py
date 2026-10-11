# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK API keys kept on this computer, in the OS keychain.

Keys never go to the Mixar backend: the backend relays each provider call
through this app (``core/cloud_relay.py``), which reads the key from here and
adds it to the request for that provider's fixed host only.

Storage matches the login tokens (``auth/core/auth.py``): macOS Keychain and
Linux Secret Service through ``keyring``, Windows Credential Manager through
the same Win32 calls. Entries are scoped per signed-in account and provider —
``BYOK-<account hash>-<provider>`` under ``MixarSafeStorage`` — so a second
account on the same computer never uses the first one's key. The account
hash is a SHA-256 prefix of the email, so the email itself never becomes a
keychain label.

No bpy imports: the relay reads keys on a worker thread.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_SERVICE = "MixarSafeStorage"
# Providers whose key the app may hold. "local" is the optional bearer token of
# a custom local server; Codex has no stored key (the Codex CLI's own login
# is read in place — core/codex_cli_login.py).
STORED_KEY_PROVIDERS = frozenset(
    {"anthropic", "openai", "gemini", "fugu", "kimi", "openrouter", "local"}
)


def _account_scope() -> Optional[str]:
    try:
        from mixar.modules.space_mixie_chat.core.account_identity import account_email
        email = (account_email() or "").strip().lower()
    except Exception:  # noqa: BLE001 — stripped builds: no account, no keys
        email = ""
    if not email:
        return None
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]


def _entry_name(provider: str) -> Optional[str]:
    scope = _account_scope()
    if scope is None or provider not in STORED_KEY_PROVIDERS:
        return None
    return f"BYOK-{scope}-{provider}"


# --- Platform backends (test seams) -----------------------------------------

def _backend():
    from mixar.modules.auth.core import auth as _auth

    if getattr(_auth, "_is_windows", False):
        return (
            lambda name: _auth._win_get_password(f"{name}@{_SERVICE}"),
            lambda name, value: _auth._win_set_password(f"{name}@{_SERVICE}", name, value),
            lambda name: _auth._win_delete_password(f"{name}@{_SERVICE}"),
        )
    import keyring

    def _set(name, value):
        keyring.set_password(_SERVICE, name, value)
        return True

    def _delete(name):
        try:
            keyring.delete_password(_SERVICE, name)
        except keyring.errors.PasswordDeleteError:
            pass  # nothing stored is success
        return True

    return (lambda name: keyring.get_password(_SERVICE, name), _set, _delete)


# --- Public API ---------------------------------------------------------------

def get_key(provider: str) -> str:
    """The stored key for ``provider`` and the signed-in account, or ""."""
    name = _entry_name(provider)
    if name is None:
        return ""
    try:
        return _backend()[0](name) or ""
    except Exception as e:  # noqa: BLE001 — keychain locked/unavailable
        logger.warning("BYOK keychain read failed: %s", e.__class__.__name__)
        return ""


def store_key(provider: str, key: str) -> bool:
    """Store ``key`` for ``provider``; False if there is no account or the
    keychain refused it (the caller must not save the BYOK config then)."""
    name = _entry_name(provider)
    if name is None or not key:
        return False
    try:
        return bool(_backend()[1](name, key))
    except Exception as e:  # noqa: BLE001
        logger.error("BYOK keychain write failed: %s", e.__class__.__name__)
        return False


def delete_key(provider: str) -> bool:
    name = _entry_name(provider)
    if name is None:
        return False
    try:
        return bool(_backend()[2](name))
    except Exception as e:  # noqa: BLE001
        logger.warning("BYOK keychain delete failed: %s", e.__class__.__name__)
        return False


def delete_all_except(keep: Optional[str] = None) -> None:
    """Remove this account's stored keys for every provider but ``keep``.

    The backend holds one active BYOK config, so after a save (or a remove,
    ``keep=None``) the keychain holds at most that config's key."""
    for provider in STORED_KEY_PROVIDERS:
        if provider != keep:
            delete_key(provider)


def has_account() -> bool:
    return _account_scope() is not None


def mask(key: str) -> str:
    """A label for the key that cannot reveal it: a short prefix (the vendor
    marker, e.g. ``sk-ant``) and the last four characters."""
    key = (key or "").strip()
    if len(key) < 16:
        return "••••"
    prefix = key[:6] if key.startswith("sk-") else key[:3]
    return f"{prefix}…{key[-4:]}"
