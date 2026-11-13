# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Worker-thread Linux login preflight; never write credentials to a file."""
import secrets

from mixar.modules.common.i18n import rpt_
from mixar.modules.common.utils import credential_store


def check_login_storage():
    """Verify a fresh write/read/delete, without touching an existing session.

    Reading an absent item alone cannot distinguish a usable store from a
    null backend. Use a unique, non-credential probe and always clean it up.
    Do not cache failures: unlocking the keyring must allow an immediate retry.
    """
    name = "LoginProbe." + secrets.token_hex(16)
    value = secrets.token_hex(16)
    try:
        written = credential_store.set_secret(name, value)
        readable = written and credential_store.get_secret(name) == value
    finally:
        deleted = credential_store.delete_secret(name)
    return bool(readable and deleted)


def storage_error_result():
    return {
        "success": False,
        "failure_kind": "credential_storage",
        "message": rpt_(
            "Mixar cannot save your sign-in securely. Enable and unlock a "
            "Secret Service keyring (such as GNOME Keyring or KWallet) in your "
            "desktop D-Bus session, check that its configuration is writable, "
            "then try Sign in again."
        ),
    }
