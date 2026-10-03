# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Whether the backend's scene tools reach this MCP session, and why not.

An AI app asks for tools once while it starts, and only some apps reload the
list when told it changed. So the launcher waits briefly for a Mixar that is
starting (a few seconds, well inside the apps' startup timeouts), never for one
that needs the user (signed out, several apps open), and reports the reason to
the agent instead of letting it guess.
"""

import asyncio
import time

#: Longest wait for a starting Mixar before the first tool list is answered; with
#: the catalog fetch it stays inside Codex's 30 s startup timeout (initialize +
#: tools/list).
STARTUP_WAIT_SECONDS = 12
#: Background re-check interval (doubling to the cap) while the session lacks the scene tools.
RECHECK_FIRST_SECONDS = 1
RECHECK_MAX_SECONDS = 30
CATALOG_TIMEOUT_SECONDS = 7

NEXT_STEPS = {
    "available": "",
    "loading": ("They are being added to this session; if they do not appear, ask the user to reconnect "
                "the Mixar MCP server (Claude Code: /mcp, then reconnect mixar; Codex: start a new session)."),
    "signed_out": "Ask the user to sign in to Mixar; the scene tools are added once they do.",
    "starting": "Mixar is starting; wait a moment and check again.",
    "absent": "Mixar is not open; ask the user to open Mixar and sign in.",
    "connecting": "Mixar is signed in but still connecting to its server; wait a moment.",
    "choose": "Several Mixar apps are open; call mixar_ui_context with one of their instance ids.",
    "closed": "The Mixar app this connection used was closed; call mixar_ui_context to choose a running one.",
}


async def fetch_tools(connector, wait_seconds=0.0):
    """(tools or None, readiness). Waits only while Mixar is starting."""
    deadline = time.monotonic() + wait_seconds
    while True:
        check = getattr(connector, "readiness", lambda: ("ready", ""))
        state, _ = await asyncio.to_thread(check)
        if state == "ready":
            try:
                tools = await asyncio.wait_for(asyncio.to_thread(connector.catalog), CATALOG_TIMEOUT_SECONDS)
                return tools, state
            except (OSError, ValueError, KeyError, RuntimeError, TimeoutError):
                state = "connecting"
        if state not in ("starting", "connecting") or time.monotonic() >= deadline:
            return None, state
        await asyncio.sleep(1)


def scene_tools(listed, readiness, health):
    """The status mixar_ui_context reports: is scene work possible in this session?"""
    if listed:
        if readiness == "ready" and not health.get("connected"):
            status = "connecting"
        else:
            status = "available" if readiness == "ready" else readiness
    else:
        status = "loading" if readiness == "ready" else readiness
    return {"scene_tools": status, "next_step": NEXT_STEPS.get(status, "")}
