# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure helpers for the Refer a Friend dialog (no ``bpy``, unit-tested).

Parsing here is a courtesy check so an obvious typo is caught before a round
trip. The backend validates every address again and owns what is sent.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from ..constants import EMAIL_SEPARATORS

# Deliberately loose: one "@", a dot in the domain, no spaces. Anything
# stricter belongs to the backend's validator, which has the final say.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SPLIT_RE = re.compile("[" + re.escape(EMAIL_SEPARATORS) + "]+")


def parse_emails(text: str) -> Tuple[List[str], List[str]]:
    """Split the field into ``(valid, invalid)``, lowercased and de-duplicated."""
    valid: List[str] = []
    invalid: List[str] = []
    for token in _SPLIT_RE.split(text or ""):
        address = token.strip().strip("<>").lower()
        if not address:
            continue
        bucket = valid if _EMAIL_RE.match(address) else invalid
        if address not in bucket:
            bucket.append(address)
    return valid, invalid


def unwrap(response: Any) -> Dict[str, Any]:
    """The ``data`` payload of a ``{status, data}`` envelope, or ``{}``."""
    envelope = getattr(response, "data", None) or {}
    if not isinstance(envelope, dict):
        return {}
    data = envelope.get("data", envelope)
    return data if isinstance(data, dict) else {}


def summarize(payload: Dict[str, Any]) -> Tuple[str, List[str], bool]:
    """``(headline, per-address lines, all_sent)`` for an invite-emails reply."""
    results = [r for r in payload.get("results") or [] if isinstance(r, dict)]
    sent = [r for r in results if r.get("status") == "sent"]
    others = [r for r in results if r.get("status") != "sent"]
    if sent and not others:
        noun = "friend" if len(sent) == 1 else "friends"
        return f"Invite sent to {len(sent)} {noun}", [], True
    lines = [f"{r.get('email', '')}: {r.get('message') or 'Not sent'}" for r in others]
    if sent:
        return f"Sent {len(sent)} of {len(results)} invites", lines, False
    return "No invites were sent", lines, False


def format_credits(amount: Any) -> str:
    try:
        return f"{int(amount):,}"
    except (TypeError, ValueError):
        return "0"


def error_message(error: Any, fallback: str) -> str:
    """User-facing text for a failed referral call.

    The referral endpoints answer 422/503 with messages written for users
    ("'x' is not a valid email address", "Daily invite limit reached"), so
    those are shown as sent. Everything else goes through the shared queue
    classifier so auth, rate-limit and offline failures read the same as
    they do on every other surface.
    """
    try:
        from mixar.modules.common.api.exceptions import ServerError, ValidationError
        from mixar.modules.common.job_queue.core.error_helpers import (
            classify_error,
            sanitize_message,
        )
    except Exception:  # noqa: BLE001 — stripped build: still say something
        return fallback
    if isinstance(error, (ValidationError, ServerError)) and getattr(error, "message", ""):
        if getattr(error, "status_code", None) in (422, 503):
            return sanitize_message(error.message, fallback)
    return classify_error(error) or sanitize_message(str(error), fallback)
