# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Byte-aware bounds for the chat composer draft.

``StringProperty(maxlen=N)`` keeps at most ``N`` UTF-8 bytes (measured on
the 5.2 fork: a 70000-char assignment and a paste-then-type in the editor
both stop at exactly N); anything longer is cut by RNA on assignment without
a word to the user. Every path
that writes ``scene.mixie_chat_input`` programmatically (paste, voice,
scribble, sketch typing) clamps through here so the warning it reports
matches what the property will actually keep.
"""

from ..constants import CHAT_INPUT_MAXLEN


def capacity_bytes(maxlen: int = CHAT_INPUT_MAXLEN) -> int:
    """UTF-8 bytes the property keeps."""
    return max(int(maxlen), 0)


def fits(text: str, maxlen: int = CHAT_INPUT_MAXLEN) -> bool:
    return len(text.encode("utf-8")) <= capacity_bytes(maxlen)


def is_full(text: str, maxlen: int = CHAT_INPUT_MAXLEN) -> bool:
    """True once the draft occupies the whole buffer: typing adds nothing."""
    return len(text.encode("utf-8")) >= capacity_bytes(maxlen)


def clamp(text: str, maxlen: int = CHAT_INPUT_MAXLEN) -> tuple[str, int]:
    """Return ``(kept, dropped_chars)``; never splits a multi-byte character."""
    limit = capacity_bytes(maxlen)
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text, 0
    kept = raw[:limit].decode("utf-8", errors="ignore")
    return kept, len(text) - len(kept)
