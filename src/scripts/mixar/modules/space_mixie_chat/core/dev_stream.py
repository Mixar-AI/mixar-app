# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scripted streaming demo for the agent chat.

Drives the *real* slot pipeline (SlotEventProcessor.apply_event) over a Blender
timer so the UI can be evaluated without a backend. Produces a clean,
industry-standard transcript — finalized "Thought for Ns" dropdown, a plan
block (todo rows + confidence), a collapsible "Used N tools" steps block, and a
Markdown answer that streams in token-by-token (headings, **bold**, `inline
code`, bullet list, fenced code block).

This is dev/demo scaffolding: real LLM output will flow through the same
apply_event path, so what looks good here looks good in production.
"""

import bpy

from mixar.config.logging_config import get_logger

from ..constants import SessionState
from .session import get_session_manager
from .slot_processor import get_slot_processor
from .ui_utils import redraw_chat_areas

logger = get_logger(__name__)

# Logical bubbles, in transcript (top-to-bottom) order.
_THINK = "dev-think"
_PLAN = "dev-plan"
_TOOLS = "dev-tools"
_ANSWER = "dev-answer"


def _chunks(text: str, size: int = 28) -> list[str]:
    """Split text into small append chunks for a smooth streaming feel,
    biased to break on spaces so words aren't sliced mid-token."""
    out: list[str] = []
    i = 0
    while i < len(text):
        end = min(i + size, len(text))
        nxt = text.find(" ", end)
        if nxt != -1 and nxt - end < 12:
            end = nxt + 1
        out.append(text[i:end])
        i = end
    return out


_ANSWER_MD = (
    "## Woods scene\n\n"
    "I set up a small clearing with a **log cabin** and an outdoor "
    "**stone fireplace**. The key assets I placed:\n\n"
    "- Mossy boundary stone 04\n"
    "- Dirt path through the clearing\n"
    "- Soft woodland sun for warm afternoon light\n\n"
    "You can nudge the fire with the `fireplace.intensity` property, "
    "or drive it from script:\n\n"
    "```python\n"
    "fire = bpy.data.objects['Fireplace']\n"
    "fire.modifiers['Fire'].strength = 1.5\n"
    "```\n\n"
    "Want me to scatter some falling leaves next?"
)


def _build_steps(scene_name: str, user_text: str) -> list:
    """Return a list of (delay_before_seconds, event_dict) steps.

    Each event is a slot event applied via apply_event. A ``None`` event is a
    control marker handled by the tick loop (e.g. finalize/idle).
    """
    steps: list = []

    def add(delay, event):
        steps.append((delay, event))

    # --- live thinking -------------------------------------------------
    add(0.0, {"bubble_id": _THINK, "loader": {"visible": True, "texts": ["Thinking…"]}})
    add(0.4, {"bubble_id": _THINK, "ephemeral": {
        "set": "Reading the request: a woods scene with a cabin and an outdoor fireplace."}})
    add(0.7, {"bubble_id": _THINK, "ephemeral": {
        "append": "\nI'll drop a cabin, scatter trees, add a stone fireplace and a dirt path."}})
    add(0.7, {"bubble_id": _THINK, "ephemeral": {
        "append": "\nThen warm the scene with soft afternoon light."}})
    # finalize thinking -> "Thought for Ns" dropdown, stop the spinner.
    add(0.8, {"bubble_id": _THINK, "ephemeral": {"clear": True},
              "loader": {"visible": False}})

    # --- plan block (content header + todo rows) -----------------------
    add(0.3, {"bubble_id": _PLAN, "content": {"set": "**Plan** · 95% confidence"}})
    add(0.2, {"bubble_id": _PLAN, "todo": [
        {"id": "p1", "text": "Block out the clearing and ground", "status": "DONE"},
        {"id": "p2", "text": "Place the log cabin", "status": "IN_PROGRESS"},
        {"id": "p3", "text": "Add the outdoor stone fireplace", "status": "PENDING"},
        {"id": "p4", "text": "Scatter trees and a dirt path", "status": "PENDING"},
    ]})

    # --- tool activity (steps block) -----------------------------------
    add(0.4, {"bubble_id": _TOOLS, "steps": {"summary": "Using 2 tools", "items": [
        {"id": "t1", "kind": "TOOL", "label": "Add asset", "target": "Mossy boundary stone 04",
         "status": "DONE"},
        {"id": "t2", "kind": "TOOL", "label": "Add asset", "target": "Soft woodland sun",
         "status": "RUNNING"},
    ]}})
    add(0.6, {"bubble_id": _TOOLS, "steps": {"summary": "Used 2 tools", "items": [
        {"id": "t1", "kind": "TOOL", "label": "Add asset", "target": "Mossy boundary stone 04",
         "status": "DONE"},
        {"id": "t2", "kind": "TOOL", "label": "Add asset", "target": "Soft woodland sun",
         "status": "DONE"},
    ]}})

    # --- streamed Markdown answer --------------------------------------
    first = True
    for chunk in _chunks(_ANSWER_MD):
        op = "set" if first else "append"
        add(0.06, {"bubble_id": _ANSWER, "content": {op: chunk}})
        first = False

    # --- done ----------------------------------------------------------
    add(0.2, None)  # idle marker
    return steps


# Module-global run state (single demo at a time).
_state = {"steps": None, "index": 0, "scene_name": None, "think_start": 0.0}


def _tick():
    steps = _state["steps"]
    if steps is None:
        return None
    idx = _state["index"]
    if idx >= len(steps):
        _finish()
        return None

    delay, event = steps[idx]
    _state["index"] = idx + 1

    scene = bpy.data.scenes.get(_state["scene_name"]) if _state["scene_name"] else None
    if scene is None:
        _finish()
        return None

    if event is not None:
        try:
            get_slot_processor().apply_event(event, scene)
        except Exception as exc:  # noqa: BLE001 — demo must never crash Blender
            logger.error("[DEV_STREAM] apply_event failed: %s", exc)
        redraw_chat_areas()

    # Return the delay until the NEXT step (or stop).
    if _state["index"] >= len(steps):
        _finish()
        return None
    return steps[_state["index"]][0]


def _finish():
    scene = bpy.data.scenes.get(_state["scene_name"]) if _state["scene_name"] else None
    if scene is not None:
        try:
            get_session_manager().set_state(scene, SessionState.IDLE)
        except Exception:  # noqa: BLE001
            pass
        redraw_chat_areas()
    _state["steps"] = None
    _state["index"] = 0


def stop_demo_stream() -> None:
    """Cancel any in-flight demo stream."""
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _state["steps"] = None
    _state["index"] = 0


def start_demo_stream(scene, user_text: str = "") -> None:
    """Begin a scripted streaming demo on the given scene.

    Adds an optional user bubble, then streams a full agent turn through the
    real slot pipeline. Safe to call repeatedly — restarts cleanly.
    """
    stop_demo_stream()

    if user_text:
        user_msg = scene.mixie_chat_messages.add()
        user_msg.sender = 'USER'
        user_msg.text = user_text

    try:
        get_session_manager().set_state(scene, SessionState.BUSY)
    except Exception:  # noqa: BLE001
        pass

    _state["steps"] = _build_steps(scene.name, user_text)
    _state["index"] = 0
    _state["scene_name"] = scene.name

    bpy.app.timers.register(_tick, first_interval=0.0)
    redraw_chat_areas()
