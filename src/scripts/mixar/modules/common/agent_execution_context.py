# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Process-local context for work enqueued by a running agent script."""

from typing import Optional


_current: Optional[dict[str, str]] = None


def set_agent_execution_context(session_id: str, turn_id: str) -> None:
    """Mark the synchronous agent script currently running on the main thread."""
    global _current
    _current = {
        "source": "agent",
        "session_id": session_id or "",
        "turn_id": turn_id or "",
    }


def clear_agent_execution_context() -> None:
    """Clear the current agent script marker."""
    global _current
    _current = None


def get_agent_execution_context() -> Optional[dict[str, str]]:
    """Return a copy of the current context, including this Mixar instance."""
    if _current is None:
        return None

    context = dict(_current)
    try:
        import bpy

        wm = getattr(bpy.context, "window_manager", None)
        context["instance_id"] = getattr(wm, "mixie_instance_id", "") if wm else ""
    except Exception:
        context["instance_id"] = ""
    return context


def stamp_agent_context(payload: dict) -> Optional[dict[str, str]]:
    """Stamp *payload* when called during agent execution; never block enqueue."""
    try:
        context = get_agent_execution_context()
        if context is not None:
            payload["agent_context"] = context
        return context
    except Exception:
        return None
