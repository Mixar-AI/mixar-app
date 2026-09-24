# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Live step recording for the agent steps block.

Bridges real `blender.execute_script` tool executions (main_thread_executor)
onto the active agent bubble's `step_items`, so the steps block fills with
real tool activity as the agent works. All row/summary logic lives in the
pure, unit-tested steps_format helpers — this module only locates the bubble
and triggers the redraw/layout-rebuild.

Runs on the main thread only (called from the executor timer callback).
"""

from mixar.config.logging_config import get_logger

from ..constants import TEMP_PLACEHOLDER_PREFIX
from .capture_store import fetch_backend_image, save_captures
from .steps_format import (
    apply_activity_to_bubble,
    attach_step_images,
    begin_step_on_bubble,
    finish_step_on_bubble,
    images_to_fetch,
    is_internal_step,
)
from .ui_utils import bump_layout_epoch, redraw_chat_areas

logger = get_logger(__name__)


def _find_active_agent_bubble(scene):
    """Return the most recent non-placeholder AGENT bubble, or None."""
    messages = getattr(scene, "mixie_chat_messages", None)
    if not messages:
        return None
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if msg.sender == 'AGENT' and not msg.bubble_id.startswith(TEMP_PLACEHOLDER_PREFIX):
            return msg
    return None


def _find_bubble_with_step(scene, request_id: str):
    """Return the bubble holding a step row with `request_id`, or None."""
    messages = getattr(scene, "mixie_chat_messages", None)
    if not messages:
        return None
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        for row in msg.step_items:
            if row.item_id == request_id:
                return msg
    return None


def _find_bubble_with_call(scene, call_id: str):
    """Return the bubble holding a step row for backend `call_id`, or None.

    The two views of one tool call — the backend's `activity` payload and the
    script RPC the tool dispatched — arrive on different paths in no fixed
    order. Whichever lands second joins the row the first one opened, on THAT
    bubble, instead of the newest bubble (which may be a text bubble that
    opened in between and would then draw the step beneath its text).
    """
    messages = getattr(scene, "mixie_chat_messages", None)
    if not messages or not call_id:
        return None
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        for row in msg.step_items:
            if getattr(row, "call_id", "") == call_id:
                return msg
    return None


def _find_bubble_by_id(scene, bubble_id: str):
    messages = getattr(scene, "mixie_chat_messages", None)
    if not messages or not bubble_id:
        return None
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if msg.bubble_id == bubble_id:
            return msg
    return None


def record_step_start(scene, request_id: str, tool_name: str, script: str = "",
                      call_id: str = "") -> None:
    """Append (or adopt) the RUNNING step row for a tool call about to execute."""
    try:
        # Internal executions ("_"-prefixed names: verification snapshots,
        # polling loops, lane plumbing) and notification pushes are backend
        # bookkeeping — the user only sees steps that do something for them.
        if is_internal_step(tool_name, request_id):
            return
        bubble = _find_bubble_with_call(scene, call_id) or _find_active_agent_bubble(scene)
        if bubble is None:
            logger.debug("[STEPS] No agent bubble for %s, skipping row", tool_name)
            return
        from .cat_activity import clear_activity
        clear_activity(scene)
        begin_step_on_bubble(bubble, request_id, tool_name, script, call_id=call_id)
        # A new tool step starting means the agent has moved on from its current
        # reasoning — collapse the live thinking panel to "Thought for Ns" so it
        # appears progressively rather than only at the very end of the turn.
        from .slot_processor import collapse_live_thinking
        collapse_live_thinking(bubble, scene)
        bump_layout_epoch(scene)
        redraw_chat_areas()
    except Exception:
        logger.debug("[STEPS] step-start recording failed", exc_info=True)


def record_step_end(scene, request_id: str, result: dict, session_id: str = "") -> None:
    """Complete the step row for `request_id` from the execution result.

    A capture result (viewport render, seam / UV inspection, final render)
    also lands as image tiles under the row: the bytes are written to the
    session's media dir and referenced from the bubble's image_items.
    """
    try:
        bubble = _find_bubble_with_step(scene, request_id)
        if bubble is None:
            return
        result = result or {}
        if finish_step_on_bubble(bubble, request_id, result):
            from .cat_activity import note_step_completed
            note_step_completed(scene, bubble, request_id)
        _attach_captures(scene, bubble, request_id, result, session_id)
        bump_layout_epoch(scene)
        redraw_chat_areas()
    except Exception:
        logger.debug("[STEPS] step-end recording failed", exc_info=True)


def record_step_captures(scene, request_id: str, result: dict, session_id: str = "") -> None:
    """Attach capture tiles to an ALREADY finished step row.

    The final render (`render_viewport(quality="final")`) replies late: the
    executor closes the row with the deferral marker and the pixels arrive
    minutes later from preview_deferral's poller. This hangs them under the
    same row by request id.
    """
    try:
        bubble = _find_bubble_with_step(scene, request_id)
        if bubble is None:
            return
        _attach_captures(scene, bubble, request_id, result or {}, session_id)
        bump_layout_epoch(scene)
        redraw_chat_areas()
    except Exception:
        logger.debug("[STEPS] late capture recording failed", exc_info=True)


def _attach_captures(scene, bubble, request_id: str, result: dict, session_id: str) -> None:
    """Write the result's images to disk and hang them under the step row."""
    if not result.get("success"):
        return
    if not session_id:
        session_id = getattr(scene, "mixie_session_id", "") or ""
    try:
        records = save_captures(session_id, request_id, result)
        if records:
            added = attach_step_images(bubble, request_id, records)
            open_latest_gallery(scene, bubble)
            logger.debug("[STEPS] %d capture tile(s) for %s", added, request_id)
    except Exception:
        logger.debug("[STEPS] capture tile recording failed", exc_info=True)


def open_latest_gallery(scene, bubble) -> None:
    """Only the bubble that most recently received a tile shows its gallery
    open; every other bubble's "Viewed N images" collapses to its header."""
    try:
        for msg in getattr(scene, "mixie_chat_messages", None) or ():
            if msg.sender != 'AGENT':
                continue
            msg.images_collapsed = msg.bubble_id != bubble.bubble_id
    except Exception:
        logger.debug("[STEPS] gallery collapse sweep failed", exc_info=True)


def record_activity(scene, activity: dict) -> None:
    """Apply a backend ``activity`` payload (one per tool call) to the chat.

    Rows merge on ``call_id`` with the ones the script path opened; images
    the bubble has no tile for are fetched off the main thread from
    ``GET /agent/images/{session}/{id}`` and attached when they land.
    """
    try:
        bubble = _find_bubble_with_call(scene, str(activity.get("call_id") or ""))
        if bubble is None:
            bubble = _find_bubble_by_id(scene, str(activity.get("bubble_id") or ""))
        if bubble is None:
            bubble = _find_active_agent_bubble(scene)
        if bubble is None:
            return
        row = apply_activity_to_bubble(bubble, activity)
        if row is None:
            return
        from .cat_activity import clear_activity, note_step_completed
        if row.status == "RUNNING":
            clear_activity(scene)
        elif row.status == "DONE":
            note_step_completed(scene, bubble, row.item_id)
        wanted = images_to_fetch(bubble, row, activity)
        if wanted:
            session_id = getattr(scene, "mixie_session_id", "") or ""
            _fetch_activity_images(scene, bubble.bubble_id, row.item_id, session_id, wanted)
        bump_layout_epoch(scene)
        redraw_chat_areas()
    except Exception:
        logger.debug("[STEPS] activity recording failed", exc_info=True)


def _fetch_activity_images(scene, bubble_id: str, step_id: str, session_id: str,
                           refs: list) -> None:
    """Download the refs on a worker thread, then attach the tiles on main."""
    import threading

    from .main_thread_executor import run_on_main_thread

    def work():
        records = []
        for ref in refs:
            path = fetch_backend_image(session_id, ref["id"])
            if path:
                records.append({"local_path": path, "width": 0, "height": 0,
                                "caption": ref.get("label") or ""})
        if not records:
            return

        def attach():
            try:
                target = _find_bubble_by_id(scene, bubble_id)
                if target is None:
                    return
                attach_step_images(target, step_id, records)
                open_latest_gallery(scene, target)
                bump_layout_epoch(scene)
                redraw_chat_areas()
            except Exception:
                logger.debug("[STEPS] attaching fetched tiles failed", exc_info=True)

        run_on_main_thread(attach)

    threading.Thread(target=work, daemon=True, name="MixarActivityImages").start()
