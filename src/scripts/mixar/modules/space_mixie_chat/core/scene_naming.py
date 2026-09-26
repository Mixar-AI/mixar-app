# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene tabs name themselves after their first task.

A tab is born as ``Scene``, ``Scene.001`` or ``Scene 7``; ten of those in the
drawer say nothing about what is in them. The first message a tab's chat
sends gives it a name — the opening words of the prompt, title-cased and
capped — before the turn starts, so every handler that keys on the scene name
is created with the final name. A tab the user has already renamed keeps its
name; only the FIRST prompt of a tab names it (the transcript decides, not
the session id: the id is minted before the send path runs).
"""

from __future__ import annotations

import re

from mixar.modules.common.scenes_log import slog

#: Blender's own names for new scenes: ``Scene``, ``Scene.001``, ``Scene 7``.
_DEFAULT_TAB = re.compile(r"^Scene(?:\.\d{3}|\s\d+)?$")
#: Filler that says nothing about the task when it opens the prompt.
_LEAD_FILLER = frozenset({
    "a", "an", "the", "please", "can", "could", "you", "i", "want", "would",
    "like", "to", "me", "my", "make", "create", "build", "generate", "add",
    "model", "let", "lets", "let's", "need", "now", "hi", "hello", "hey",
})
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'_\-]*")
TAB_NAME_MAXLEN = 24


def is_default_tab_name(name: str) -> bool:
    return bool(_DEFAULT_TAB.match((name or "").strip()))


def title_for_prompt(text: str, max_len: int = TAB_NAME_MAXLEN) -> str:
    """A short title from the prompt's first line: leading filler dropped,
    words title-cased, cut at a word boundary under ``max_len``. Empty when
    the prompt has no usable words (attachments only, punctuation)."""
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    words = _WORD.findall(line)
    while words and words[0].lower().strip("'") in _LEAD_FILLER:
        words.pop(0)
    if not words:
        words = _WORD.findall(line)
    out: list[str] = []
    for word in words:
        piece = word if word.isupper() and len(word) > 1 else word[:1].upper() + word[1:]
        candidate = " ".join(out + [piece])
        if len(candidate) > max_len:
            break
        out.append(piece)
    if not out and words:
        return words[0][:max_len]
    return " ".join(out)


def is_first_prompt(scene) -> bool:
    """True until the tab's transcript holds an agent reply or a second user
    message. The optimistic user bubble of the message being sent is already
    in the transcript when the send path runs, so ONE user message counts as
    the first prompt."""
    try:
        messages = list(getattr(scene, "mixie_chat_messages", None) or ())
    except Exception:  # noqa: BLE001
        return False
    users = sum(1 for m in messages if getattr(m, "sender", "") == "USER")
    agents = sum(1 for m in messages if getattr(m, "sender", "") == "AGENT")
    return users <= 1 and agents == 0


def auto_name_tab(scene, text: str) -> str:
    """Rename a still-default tab after its first prompt. Returns the new
    name, or "" when nothing changed. Blender keeps names unique, so a second
    tab asking for the same thing becomes ``<title>.001``."""
    if scene is None or not is_default_tab_name(getattr(scene, "name", "")):
        return ""
    if not is_first_prompt(scene):
        return ""
    title = title_for_prompt(text)
    if not title or title == scene.name:
        return ""
    old = scene.name
    try:
        scene.name = title
    except Exception:  # noqa: BLE001 — a read-only or linked scene keeps its name
        return ""
    slog("tab.autoname", scene, was=old, name=scene.name)
    return scene.name
