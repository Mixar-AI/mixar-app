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
from .capture_store import save_captures
from .steps_format import (
    attach_step_images,
    begin_step_on_bubble,
    finish_step_on_bubble,
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


def record_step_start(scene, request_id: str, tool_name: str, script: str = "") -> None:
    """Append a RUNNING step row for a tool call that is about to execute."""
    try:
        # Internal executions ("_"-prefixed names: verification snapshots,
        # polling loops, lane plumbing) and notification pushes are backend
        # bookkeeping — the user only sees steps that do something for them.
        if is_internal_step(tool_name, request_id):
            return
        bubble = _find_active_agent_bubble(scene)
        if bubble is None:
            logger.debug("[STEPS] No agent bubble for %s, skipping row", tool_name)
            return
        from .cat_activity import clear_activity
        clear_activity(scene)
        begin_step_on_bubble(bubble, request_id, tool_name, script)
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
            logger.debug("[STEPS] %d capture tile(s) for %s", added, request_id)
    except Exception:
        logger.debug("[STEPS] capture tile recording failed", exc_info=True)
