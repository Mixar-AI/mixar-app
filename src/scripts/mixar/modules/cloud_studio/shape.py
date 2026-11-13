# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shapes ``api`` reports, as pure functions (no bpy): unit-tested outside the app."""

import json
import os

MAX_TEXT = 8000
MAX_MESSAGES = 60
ROLES = {"USER": "user", "AGENT": "agent"}
PHASES = ("idle", "working", "asking")


def clip(text, limit=MAX_TEXT):
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def phase(state_name, run_open):
    """What the agent is doing, in three words a page can act on.

    ``asking``: waiting for the person. ``working``: a turn is running, or its run's agents are
    still building after the turn went idle. ``idle``: a new request can start.
    """
    name = str(state_name or "").lower()
    if "await" in name:
        return "asking"
    if name in ("busy", "modifying") or run_open:
        return "working"
    return "idle"


def _loader(message):
    if not getattr(message, "loader_visible", False):
        return ""
    raw = getattr(message, "loader_texts", "") or "[]"
    try:
        texts = [str(t) for t in json.loads(raw)]
    except ValueError:
        texts = [str(raw)[:80]]
    return clip(texts[0], 120) if texts else "Working"


def message(item):
    """One chat bubble as plain data."""
    return {
        "id": getattr(item, "bubble_id", "") or "",
        "role": ROLES.get(getattr(item, "sender", ""), "agent"),
        "kind": str(getattr(item, "message_type", "") or "").lower(),
        "text": clip(getattr(item, "content", "") or getattr(item, "text", "")),
        "note": clip(getattr(item, "ephemeral", ""), 400),
        "working": _loader(item),
        "todos": [
            {"text": clip(t.text, 200), "status": str(t.status).lower()}
            for t in list(getattr(item, "todo_items", []))[:30]
        ],
        "steps": [
            {
                "label": clip(s.label, 120),
                "target": clip(s.target, 120),
                "status": str(s.status).lower(),
                "kind": clip(getattr(s, "kind", ""), 24).lower(),
            }
            for s in list(getattr(item, "step_items", []))[-20:]
        ],
        "actions": [
            {"label": clip(a.label, 80), "value": str(a.value)[:200]}
            for a in list(getattr(item, "action_items", []))[:8]
        ],
        "asks": bool(getattr(item, "input_type", "")),
    }


def messages(items, limit=MAX_MESSAGES):
    return [message(item) for item in list(items)[-max(1, int(limit)):]]


def scene_file(path, root):
    """``path`` as a scene file under ``root``, or None.

    The page names where a project is saved and opened. Only a ``.mixar`` file inside the given
    folder is ever accepted, whatever the path says (``..``, a symlink, another folder).
    """
    if not path or not root:
        return None
    resolved = os.path.realpath(os.path.expanduser(str(path)))
    base = os.path.realpath(os.path.expanduser(str(root)))
    if not resolved.endswith(".mixar") or not resolved.startswith(base + os.sep):
        return None
    return resolved


def attachable(path, folder):
    """``path`` when it is an existing file directly inside ``folder``, else None."""
    if not path or not folder:
        return None
    resolved = os.path.realpath(str(path))
    base = os.path.realpath(str(folder))
    if not resolved.startswith(base + os.sep) or not os.path.isfile(resolved):
        return None
    return resolved
