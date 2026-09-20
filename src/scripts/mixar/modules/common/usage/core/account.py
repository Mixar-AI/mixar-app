# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Greeting name for the profile card.

The card opens with "Welcome, <name> !", so it needs something short and
personal. ``/auth/me`` returns an optional ``name``; when it is absent
(most SSO signups never set one) the email's local part is the only
signal available, and reads correctly for the common cases
(``rahul@mixar.app`` → "Rahul").

Kept pure and separate from ``state`` so the derivation is unit-testable
and so a malformed name can never break the card draw.
"""

from __future__ import annotations

import re

#: Separators used between name parts in a local part (rahul.sharma, dev_ops).
_LOCAL_PART_SEPARATORS = re.compile(r"[._\-+]+")

#: Trailing digits are almost always disambiguation noise (rahul92), not a
#: name. Stripped only when letters remain, so "user123" degrades to "User"
#: but a fully numeric local part is left alone rather than becoming empty.
_TRAILING_DIGITS = re.compile(r"\d+$")

#: Cap so a pathological name can't blow past the card's heading width;
#: the C++ side clips too, this just keeps the RNA string sane.
_MAX_NAME_LEN = 32


def derive_display_name(full_name: str = "", email: str = "") -> str:
    """Short greeting name from the account's name, else its email.

    Returns "" when neither yields anything usable — the card then greets
    without a name rather than printing "Welcome,  !".
    """
    first = _first_word(full_name)
    if first:
        return first[:_MAX_NAME_LEN]

    local = (email or "").split("@", 1)[0]
    if not local:
        return ""

    head = _LOCAL_PART_SEPARATORS.split(local)[0]
    if not head:
        return ""

    stripped = _TRAILING_DIGITS.sub("", head)
    if stripped:
        head = stripped

    return head[:1].upper() + head[1:_MAX_NAME_LEN]


def _first_word(value: str) -> str:
    """First whitespace-separated word of a name, title-cased if it is
    plainly lowercase (backends store both "Rahul" and "rahul")."""
    parts = (value or "").strip().split()
    if not parts:
        return ""
    word = parts[0]
    if word.islower():
        return word[:1].upper() + word[1:]
    return word


def apply_from_user_info(user_info) -> None:
    """Write the greeting name to ``wm.mixar_account_name``.

    Called from the login apply paths, which already run on the main
    thread. Best-effort: a missing property (partial build) or absent
    window manager must never break login.
    """
    import bpy

    data = {}
    if isinstance(user_info, dict):
        data = user_info.get("data") or {}

    name = derive_display_name(
        full_name=str(data.get("name") or ""),
        email=str(data.get("email") or ""),
    )

    try:
        bpy.context.window_manager.mixar_account_name = name
    except Exception:  # noqa: BLE001 — property not registered yet
        pass


def clear() -> None:
    """Drop the greeting name on logout."""
    import bpy

    try:
        bpy.context.window_manager.mixar_account_name = ""
    except Exception:  # noqa: BLE001
        pass
