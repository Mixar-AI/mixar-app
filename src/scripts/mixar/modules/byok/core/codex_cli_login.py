# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Codex CLI's ChatGPT login, read in place on this computer.

The Codex (ChatGPT sub) provider uses the login the user's own Codex CLI keeps
in ``$CODEX_HOME/auth.json`` (default ``~/.codex/auth.json``). Mixar never
copies it anywhere: the cloud relay (``core/cloud_relay.py``) reads the
current access token and account id from the file for each call and adds
them to the request to ``chatgpt.com``. Nothing is sent to the Mixar backend
and nothing is written back — the Codex CLI stays the only owner of the
file, refreshing it whenever the user runs it.

No bpy imports: the relay runs on a worker thread.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Tuple

from mixar.modules.common.i18n import n_

# The CLI's own claim holding the ChatGPT account id (id token / access token).
_ACCOUNT_CLAIM = "https://api.openai.com/auth"
# Refuse a token this close to expiry: a long agent call must not outlive it.
_EXPIRY_MARGIN_S = 120

MSG_NOT_FOUND = n_("No Codex CLI login found on this computer — run `codex login` first.")
MSG_NO_CHATGPT = n_("The Codex CLI login has no ChatGPT sign-in — run `codex login`.")
MSG_EXPIRED = n_(
    "Your Codex CLI login has expired — run `codex login` (or any codex command) to renew it."
)
MSG_UNREADABLE = n_("Could not read the Codex CLI login on this computer.")


class CodexLoginError(Exception):
    """User-facing reason the Codex CLI login cannot be used (a msgid)."""


def auth_path() -> str:
    home = os.environ.get("CODEX_HOME") or os.path.join("~", ".codex")
    return os.path.join(os.path.expanduser(home), "auth.json")


def _jwt_claims(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(part))
        return claims if isinstance(claims, dict) else {}
    except Exception:  # noqa: BLE001 — opaque token: no claims
        return {}


def _account_id(tokens: dict) -> str:
    if isinstance(tokens.get("account_id"), str) and tokens["account_id"]:
        return tokens["account_id"]
    for name in ("id_token", "access_token"):
        claim = _jwt_claims(tokens.get(name) or "").get(_ACCOUNT_CLAIM)
        if isinstance(claim, dict) and claim.get("chatgpt_account_id"):
            return str(claim["chatgpt_account_id"])
    return ""


def parse(text: str, now: float | None = None) -> Tuple[str, str]:
    """``(access_token, account_id)`` from an ``auth.json`` text."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise CodexLoginError(MSG_UNREADABLE) from None
    tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        raise CodexLoginError(MSG_NO_CHATGPT)
    access = str(tokens["access_token"])
    exp = _jwt_claims(access).get("exp")
    if isinstance(exp, (int, float)):
        if (now if now is not None else time.time()) >= exp - _EXPIRY_MARGIN_S:
            raise CodexLoginError(MSG_EXPIRED)
    account = _account_id(tokens)
    if not account:
        raise CodexLoginError(MSG_NO_CHATGPT)
    return access, account


def read() -> Tuple[str, str]:
    """The current ``(access_token, account_id)``; raises CodexLoginError."""
    path = auth_path()
    if not os.path.exists(path):
        raise CodexLoginError(MSG_NOT_FOUND)
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        raise CodexLoginError(MSG_UNREADABLE) from None
    return parse(text)


def available() -> bool:
    try:
        read()
        return True
    except CodexLoginError:
        return False
