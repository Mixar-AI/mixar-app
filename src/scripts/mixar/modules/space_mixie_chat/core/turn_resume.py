# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Offer recovery for previously saved sessions that have no local live turn.

The WebSocket journal owns delivery. Its server cursor is never treated as a
rendered cursor: turn_events restores the cursor saved with the transcript.
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

# Server-reported turn dispositions (mixar-backend resume_buffer.TURN_*).
STATUS_RUNNING = "running"
STATUS_ABANDONED = "abandoned"
STATUS_ENDED = "ended"
# Only these two are worth telling the user about; ENDED ended in front of
# them and needs no notice.
_HIT_STATUSES = (STATUS_RUNNING, STATUS_ABANDONED)

_RUNNING_TITLE = "A previous task is still running"
_RUNNING_BODY = (
    "The connection dropped while the agent was working, and the task kept "
    "running on the server. Resume it to see what it produced — or dismiss "
    "this and start fresh."
)
_ABANDONED_TITLE = "A previous task was interrupted"
_ABANDONED_BODY = (
    "The connection dropped while the agent was working, and the task was "
    "stopped before anyone saw it finish. Resume it to see how far it got — "
    "or dismiss this and start fresh."
)


def check_orphaned_turns() -> None:
    """Ask the server which local sessions still have live turns.

    MAIN THREAD ONLY: it iterates ``bpy.data.scenes`` and reads scene RNA.
    ``connection_manager.on_connected`` (WebSocket thread) reaches it through
    ``run_on_main_thread``; the ``agent.status`` reply is handled off-thread
    and only its prompt is marshalled back. Sessions queried: every
    scene's ``mixie_session_id`` whose local state is idle-ish and which has
    no socket turn already running (the attach loop owns recovery then).
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
            from .turn_events import _turns, _blocked
            if sid in _blocked or any(turn.session_id == sid for turn in _turns.values()):
                continue
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
            # An open run's next turns arrive over the socket as wake-ups —
            # nothing is orphaned there.
            if SessionManager.run_open(scene):
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
                and _status_of(info) in _HIT_STATUSES
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
            "agent.status", {"session_ids": list(candidates)[:32]}, _on_status,
        )
    except Exception:
        logger.exception("check_orphaned_turns failed (non-fatal)")


def _status_of(info: dict) -> str:
    """The turn disposition a ``agent.status`` entry reports.

    Falls back to the pre-``status`` ``active`` bit so a new client keeps
    working against a backend that has not shipped the stamp yet; an entry
    with neither reads as ENDED, which is the silent direction — the failure
    being guarded here is a notice raised about a turn that is not there.
    """
    status = info.get("status")
    if isinstance(status, str) and status:
        return status
    return STATUS_RUNNING if info.get("active") else STATUS_ENDED


def _scene_has_live_stream(scene_name: str) -> bool:
    from .turn_transport import get_turn_handler

    handler = get_turn_handler(scene_name)
    return bool(handler and handler.is_running)


def offer_resume_prompt(scene, session_id: str, info: dict) -> None:
    """Add (or refresh) the "Resume previous task" bubble on a scene.

    Main-thread only (mutates ``scene.mixie_chat_messages``). Best-effort.
    """
    try:
        if scene is None or not hasattr(scene, "mixie_chat_messages"):
            return
        from .turn_events import _blocked
        if getattr(scene, 'mixie_session_id', '') != session_id or session_id in _blocked:
            return  # The user switched chats while the status request was pending.
        status = _status_of(info)
        if status not in _HIT_STATUSES:
            # Defence in depth: this function is what puts a claim about a
            # turn on screen, so it refuses to make one the status does not
            # support — a caller that stops filtering cannot resurrect the
            # notice-about-a-finished-turn bug on its own.
            return
        active = status == STATUS_RUNNING
        title = _RUNNING_TITLE if active else _ABANDONED_TITLE
        body = _RUNNING_BODY if active else _ABANDONED_BODY
        content = f"**{title}**\n\n{body}"
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
    """Remove the resume bubble (both "Resume task" and "Start fresh").

    ``bpy_prop_collection.remove()`` takes an INDEX, not the item — passing
    the PropertyGroup raises ``TypeError: expected one int argument`` and the
    notice stayed on screen forever (QA 2026-09-04). Collect indices and
    delete in reverse, the same way every other removal in this module does
    (slot_processor placeholder sweep, session_ops._reset_loader_bubbles,
    chat_ops stale-placeholder sweep).
    """
    try:
        if scene is None or not hasattr(scene, "mixie_chat_messages"):
            return
        stale = [
            i for i, msg in enumerate(scene.mixie_chat_messages)
            if getattr(msg, "bubble_id", "").startswith(RESUME_BUBBLE_PREFIX)
        ]
        for idx in reversed(stale):
            scene.mixie_chat_messages.remove(idx)
        _redraw()
    except Exception:
        logger.exception("dismiss_resume_prompt failed (non-fatal)")


def _fill_bubble(msg, content: str, session_id: str) -> None:
    """Populate the bubble manually — this is a client-originated bubble with
    no wire event behind it (same as the credits notice). Its buttons must not
    read as a paused turn; the actions slot no longer infers that from buttons
    (only input_type does), so this is now presentation, not a workaround."""
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
