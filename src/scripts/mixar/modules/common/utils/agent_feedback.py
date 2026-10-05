# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent feedback channel.

Agent-invoked generation operators can stash a human-readable failure reason
here just before returning ``{'CANCELLED'}``. The backend generation tool reads
it (window_manager custom prop ``mixar_agent_gen_reason``) right after
dispatching the operator, so the agent can report *why* a generation didn't
start (e.g. "no mesh selected") instead of a generic cancel.

The same window_manager channel carries ``mixar_agent_ref`` in the other
direction: the identity of the agent generation this enqueue belongs to, so
the terminal outcome can be pushed back to the backend (see ``take_agent_ref``
and ``common/job_queue/core/agent_results.py``).

Uses window_manager ID custom properties — no PropertyGroup registration needed.
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


_REF_KEY = "mixar_agent_ref"
_ORIGIN_KEY = "mixar_job_origin"


def clear_agent_ref(context=None) -> None:
    """Discard an unclaimed ref (and its MCP origin) when its synchronous agent
    script ends, so a later manual generation never inherits either."""
    try:
        if context is None:
            import bpy

            context = bpy.context
        wm = context.window_manager
        for key in (_REF_KEY, _ORIGIN_KEY):
            if key in wm.keys():
                del wm[key]
    except Exception:
        pass


def take_agent_ref(context) -> dict:
    """Read, CLEAR and return the agent's generation ref for this enqueue.

    The backend's enqueue script sets ``mixar_agent_ref`` to a JSON blob
    (``generation_id`` / ``session_id`` / ``run_id`` / ``task_id`` /
    ``worker_id`` / ``job_type``) immediately before calling the generation
    operator, so the client can report that generation's terminal outcome
    back over the agent WebSocket instead of the agent polling for it.

    The read CLEARS the property: a ref belongs to one invocation (the
    retopology batch claims it once for all accepted siblings). A later
    user-initiated generation must never inherit a stale one. Anything
    unreadable/unparseable/not-an-object yields ``{}`` (reporting is
    best-effort — it can never block an enqueue).
    """
    raw = ""
    try:
        wm = context.window_manager
        raw = wm.get(_REF_KEY, "") or ""
        if _REF_KEY in wm.keys():
            del wm[_REF_KEY]
    except Exception:
        return {}

    if not raw:
        return {}
    try:
        import json

        ref = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}
    if not isinstance(ref, dict) or not ref.get("generation_id"):
        return {}
    return {str(k): v for k, v in ref.items()}


def take_job_origin(context) -> str:
    """Read and CLEAR the backend's MCP marker for this enqueue: ``"mcp"`` or "".

    The backend's enqueue script sets ``mixar_job_origin`` beside the agent ref
    when an external AI app (MCP) asked for the generation, so the job submit
    can say so (``X-Mixar-Job-Origin``). Cleared like the ref so a later manual
    generation never inherits it.
    """
    try:
        wm = context.window_manager
        value = str(wm.get(_ORIGIN_KEY, "") or "")
        if _ORIGIN_KEY in wm.keys():
            del wm[_ORIGIN_KEY]
    except Exception:
        return ""
    return "mcp" if value == "mcp" else ""
