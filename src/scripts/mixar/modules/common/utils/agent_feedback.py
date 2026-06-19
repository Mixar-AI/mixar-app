# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent feedback channel.

Agent-invoked generation operators can stash a human-readable failure reason
here just before returning ``{'CANCELLED'}``. The backend generation tool reads
it (window_manager custom prop ``mixar_agent_gen_reason``) right after
dispatching the operator, so the agent can report *why* a generation didn't
start (e.g. "no mesh selected") instead of a generic cancel.

Uses a window_manager ID custom property — no PropertyGroup registration needed.
"""

_REASON_KEY = "mixar_agent_gen_reason"


def set_agent_gen_reason(context, message: str) -> None:
    """Record why an agent-dispatched generation operator failed."""
    try:
        context.window_manager[_REASON_KEY] = str(message)
    except Exception:
        pass


def clear_agent_gen_reason(context) -> None:
    """Clear any prior reason (call at the start of an agent-path execute)."""
    try:
        context.window_manager[_REASON_KEY] = ""
    except Exception:
        pass
