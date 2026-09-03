# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reconnect turn recovery — offer "Resume previous task" after a drop (#1258).

The backend keeps a turn running after the client's SSE dies (disconnect
drain) and buffers the missed events, but until now a reconnecting client
had no idea: the next message silently superseded the in-flight turn.

Flow:
1. On WS reconnect (``connection_manager.on_connected``), collect the chat
   session ids of scenes that look idle locally and ask the server
   ``turn.status`` for them (ownership-scoped Redis liveness).
2. A hit (active or replayable) surfaces a chat bubble with a
   ``resume_task:<session_id>`` PRIMARY action — the same manual-bubble
   pattern as the credits notice, so it never flips the session into
   AWAITING_INPUT.
3. Confirming runs ``bpy.ops.mixie_chat.resume_previous_task`` which adopts
   the session into a per-scene SSE handler and replays + follows via the
   existing attach endpoint. Dismiss removes the bubble.

All bpy work happens on the main thread (``run_on_main_thread``); the WS
thread only sends the status request and marshals the result back.
"""

import uuid

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Stable bubble-id prefix so repeated reconnects refresh one notice bubble
# instead of stacking duplicates.
RESUME_BUBBLE_PREFIX = "turn-resume-"
RESUME_ACTION_PREFIX = "resume_task:"
DISMISS_ACTION = "dismiss_resume_task"

_TITLE = "A previous task is still running"
_BODY = (
    "The connection dropped while the agent was working, and the task kept "
    "running on the server. Resume it to see what it produced — or dismiss "
    "this and start fresh."
)


def check_orphaned_turns() -> None:
    """Ask the server which local sessions still have live turns.

    Called on every WS reconnect (main thread). Sessions queried: every
    scene's ``mixie_session_id`` whose local state is idle-ish and which has
    no SSE handler already running (the attach loop owns recovery then).
    """
    try:
        from mixar.modules.space_mixie_chat.constants import SessionState

        from .jsonrpc_client import get_jsonrpc_client

        client = get_jsonrpc_client()
        if client is None:
            return

        candidates = {}
        for scene in bpy.data.scenes:
            sid = getattr(scene, "mixie_session_id", "") or ""
            if not sid or sid in candidates:
                continue
            # Scenes actively streaming are self-healing via their own attach
            # loop; active local states (BUSY/MODIFYING/AWAITING_INPUT) mean
            # the turn is already accounted for in the UI.
            if _scene_has_live_stream(scene.name):
                continue
            from mixar.modules.space_mixie_chat.core.session import (
                SessionManager,
            )

            if SessionManager.get_state(scene) not in (
                SessionState.IDLE, SessionState.OFFLINE,
            ):
                continue
            candidates[sid] = scene.name

        if not candidates:
            return

        def _on_status(result):
            try:
                turns = (result or {}).get("turns") or {}
            except Exception:
                return
            hits = {
                sid: (info or {})
                for sid, info in turns.items()
                if isinstance(info, dict)
                and (info.get("active") or info.get("replayable"))
            }
            if not hits:
                return
            from .main_thread_executor import run_on_main_thread

            def _prompt():
                for sid, info in hits.items():
                    scene_name = candidates.get(sid) or next(
                        (s.name for s in bpy.data.scenes
                         if getattr(s, "mixie_session_id", "") == sid),
                        None,
                    )
                    if scene_name:
                        offer_resume_prompt(
                            bpy.data.scenes.get(scene_name), sid, info,
                        )

            run_on_main_thread(_prompt)

        client.send_request(
            "turn.status", {"session_ids": list(candidates)}, _on_status,
        )
    except Exception:
        logger.exception("check_orphaned_turns failed (non-fatal)")


def _scene_has_live_stream(scene_name: str) -> bool:
    from .sse_handler import get_sse_handler

    handler = get_sse_handler(scene_name)
    return bool(handler and handler.is_running)


def offer_resume_prompt(scene, session_id: str, info: dict) -> None:
    """Add (or refresh) the "Resume previous task" bubble on a scene.

    Main-thread only (mutates ``scene.mixie_chat_messages``). Best-effort.
    """
    try:
        if scene is None or not hasattr(scene, "mixie_chat_messages"):
            return
        content = f"**{_TITLE}**\n\n{_BODY}"
        active = bool(info.get("active"))
        if active:
            content += "\n\nThe task is *still running* — resuming will replay what you missed and follow it live."

        # Refresh an existing notice in place instead of stacking duplicates.
        for msg in scene.mixie_chat_messages:
            if getattr(msg, "bubble_id", "").startswith(RESUME_BUBBLE_PREFIX):
                _fill_bubble(msg, content, session_id)
                _redraw()
                return

        msg = scene.mixie_chat_messages.add()
        msg.bubble_id = f"{RESUME_BUBBLE_PREFIX}{uuid.uuid4().hex[:8]}"
        msg.sender = "AGENT"
        msg.message_type = "AGENT"
        _fill_bubble(msg, content, session_id)

        try:
            from .animation_manager import start_slide_redraw_burst

            start_slide_redraw_burst()
        except Exception:
            pass
        _redraw()
    except Exception:
        logger.exception("offer_resume_prompt failed (non-fatal)")


def dismiss_resume_prompt(scene) -> None:
    """Remove the resume bubble (user chose to start fresh)."""
    try:
        if scene is None or not hasattr(scene, "mixie_chat_messages"):
            return
        for msg in list(scene.mixie_chat_messages):
            if getattr(msg, "bubble_id", "").startswith(RESUME_BUBBLE_PREFIX):
                scene.mixie_chat_messages.remove(msg)
        _redraw()
    except Exception:
        logger.exception("dismiss_resume_prompt failed (non-fatal)")


def _fill_bubble(msg, content: str, session_id: str) -> None:
    """Populate the bubble manually (NOT via the slot pipeline — this must
    not flip the session into AWAITING_INPUT, same as the credits notice)."""
    msg.content = content
    msg.text = content

    try:
        from .markdown_parser import parse_markdown_to_segments
        from .message_helpers import set_markdown_segments

        segments = parse_markdown_to_segments(content, streaming=False)
        set_markdown_segments(msg, segments)
    except Exception as e:
        logger.debug(f"turn-resume markdown parse skipped: {e}")

    msg.action_items.clear()
    resume = msg.action_items.add()
    resume.label = "Resume task"
    resume.value = f"{RESUME_ACTION_PREFIX}{session_id}"
    resume.style = "PRIMARY"
    dismiss = msg.action_items.add()
    dismiss.label = "Start fresh"
    dismiss.value = DISMISS_ACTION
    dismiss.style = "DEFAULT"


def _redraw() -> None:
    try:
        from .ui_utils import redraw_chat_areas

        redraw_chat_areas()
    except Exception:
        pass
