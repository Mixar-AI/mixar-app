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
from .steps_format import begin_step_on_bubble, finish_step_on_bubble
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
        bubble = _find_active_agent_bubble(scene)
        if bubble is None:
            logger.debug("[STEPS] No agent bubble for %s, skipping row", tool_name)
            return
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


def record_step_end(scene, request_id: str, result: dict) -> None:
    """Complete the step row for `request_id` from the execution result."""
    try:
        bubble = _find_bubble_with_step(scene, request_id)
        if bubble is None:
            return
        finish_step_on_bubble(bubble, request_id, result or {})
        bump_layout_epoch(scene)
        redraw_chat_areas()
    except Exception:
        logger.debug("[STEPS] step-end recording failed", exc_info=True)
