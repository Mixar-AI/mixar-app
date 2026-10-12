# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read only the sign-in tokens from the Codex CLI's login on this computer.

The Codex (ChatGPT sub) provider uses the login the Codex CLI keeps in
``$CODEX_HOME/auth.json`` (default ``~/.codex/auth.json``). The file also holds
the id token (name, email), any ``OPENAI_API_KEY`` and bookkeeping fields;
none of that is needed. ``minimal_bundle`` keeps exactly what the backend
uses — ``refresh_token``, ``access_token`` and ``account_id`` — and nothing
else ever leaves this machine.

No bpy imports.
"""

from __future__ import annotations

import base64
import json
import os

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

logger = get_logger(__name__)

# The ChatGPT account id claim the Codex CLI's tokens carry; used only when
# auth.json has no explicit account_id (older CLI versions).
_ACCOUNT_CLAIM = "https://api.openai.com/auth"

MSG_NOT_FOUND = n_("No Codex CLI login on this computer — run `codex login` first.")
MSG_UNREADABLE = n_("Could not read the Codex CLI login on this computer.")
MSG_NO_CHATGPT = n_("The Codex CLI login has no ChatGPT sign-in — run `codex login`.")


def auth_path() -> str:
    home = os.environ.get("CODEX_HOME") or os.path.join("~", ".codex")
    return os.path.join(os.path.expanduser(home), "auth.json")


def _account_from_jwt(token: str) -> str:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        claim = json.loads(base64.urlsafe_b64decode(part)).get(_ACCOUNT_CLAIM)
    except Exception:  # noqa: BLE001 — opaque token: no claim
        return ""
    if isinstance(claim, dict) and claim.get("chatgpt_account_id"):
        return str(claim["chatgpt_account_id"])
    return ""


def minimal_bundle(text: str) -> str:
    """The three token fields of an ``auth.json`` text, as compact JSON.

    The account id is derived from the id token here (on this computer) when
    the file has no explicit one, so the id token itself is never sent.
    Raises ``ValueError`` with a user-facing msgid when there is no ChatGPT
    login (e.g. an API-key-only file).
    """
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError(MSG_UNREADABLE) from None
    tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(tokens, dict) or not tokens.get("refresh_token"):
        raise ValueError(MSG_NO_CHATGPT)
    bundle = {"refresh_token": str(tokens["refresh_token"])}
    access = tokens.get("access_token")
    if isinstance(access, str) and access:
        bundle["access_token"] = access
    account = tokens.get("account_id")
    if not (isinstance(account, str) and account):
        account = (
            _account_from_jwt(str(tokens.get("id_token") or ""))
            or _account_from_jwt(str(access or ""))
        )
    if account:
        bundle["account_id"] = account
    return json.dumps(bundle, separators=(",", ":"))


def read_minimal_bundle() -> str:
    """``minimal_bundle`` of this computer's Codex CLI login."""
    path = auth_path()
    if not os.path.exists(path):
        raise ValueError(MSG_NOT_FOUND)
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        logger.warning("Codex CLI login read failed: %s", e.__class__.__name__)
        raise ValueError(MSG_UNREADABLE) from None
    return minimal_bundle(text)
