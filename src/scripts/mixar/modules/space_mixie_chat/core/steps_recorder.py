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


def _current_loader_phase(bubble) -> str:
    """The current loader phase as a clean label ("Placing object", "Validating
    scene", …), or "" for the generic 'Executing bpy script…'. Used to give each
    tool row a descriptive name (the backend sends no per-tool reasoning)."""
    import json
    raw = getattr(bubble, "loader_texts", "") or ""
    try:
        texts = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return ""
    if not isinstance(texts, list) or not texts:
        return ""
    idx = getattr(bubble, "loader_current_index", 0) or 0
    if idx < 0 or idx >= len(texts):
        idx = 0
    text = (texts[idx] or "").strip().rstrip("…").rstrip(".").strip()
    if not text or text.lower().startswith("executing bpy script"):
        return ""
    return text


def record_step_start(scene, request_id: str, tool_name: str) -> None:
    """Append a RUNNING step row for a tool call that is about to execute."""
    try:
        bubble = _find_active_agent_bubble(scene)
        if bubble is None:
            logger.debug("[STEPS] No agent bubble for %s, skipping row", tool_name)
            return
        begin_step_on_bubble(bubble, request_id, tool_name)
        # The backend sends no per-tool reasoning, so label the row with the
        # current loader PHASE ("Placing object", "Validating scene", …) — the
        # best descriptive signal — instead of a generic "Tool call".
        status = _current_loader_phase(bubble)
        if status:
            try:
                bubble.step_items[-1].label = status
            except Exception:  # noqa: BLE001
                pass
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
