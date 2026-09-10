# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene routing and history archiving for agent scripts on the GUI main thread.

Split out of ``main_thread_executor`` (harness v3 PR 1) so the pump itself
stays small; the behaviour is unchanged:

- A per-scene routing session (the user's main scene UUID or an
  ``agentlane:<parent>:<n>`` lane scene) MUST resolve to a scene: switch to
  it, execute, restore. The constant ``agent:<connection>`` / empty session
  follows the user's active window scene.
- The switch + execute + restore all happen within one timer tick, so the
  user sees no visual change.
- A real per-scene session with no matching scene is REJECTED (hard-fail),
  never run against whatever scene happens to be active.
"""

from __future__ import annotations

from typing import Optional

import bpy

from mixar.config.logging_config import get_logger

from ..constants import is_lane_scene, is_non_scene_routing_session

logger = get_logger(__name__)

# The user's genuine foreground scene — the one window.scene should return to
# after a per-scene-routed (or lane) script flips away from it. Tracked by name
# because Scene datablocks are not safe to hold across undo/file-load. Updated
# only when an active-scene-follow script runs (agent:/empty session), i.e. the
# scene the user is actually looking at.
_user_foreground_scene_name: str = ""


def resolve_user_foreground_scene():
    """The user's real (non-lane) foreground scene to restore window.scene to.

    Prefers the tracked scene captured while an active-scene-follow script ran.
    If it was deleted, falls back to any real (non-lane) scene — NEVER a lane
    scene. Returns None only if no real scene exists (should not happen).
    """
    tracked = (
        bpy.data.scenes.get(_user_foreground_scene_name)
        if _user_foreground_scene_name else None
    )
    if tracked is not None and not is_lane_scene(tracked):
        return tracked
    for s in bpy.data.scenes:
        if not is_lane_scene(s):
            return s
    return None


def route_request(
    session_id: str, tool_name: str, request_id: str
) -> tuple[Optional[object], bool, Optional[str]]:
    """Resolve and switch to the target scene for a script.

    Returns ``(target_scene, did_switch, error)``. ``error`` is set (and no
    switch happens) when a per-scene session matches no scene.
    """
    global _user_foreground_scene_name
    target_scene = None
    if not is_non_scene_routing_session(session_id):
        for s in bpy.data.scenes:
            if getattr(s, "mixie_session_id", "") == session_id:
                target_scene = s
                break
        if target_scene is None:
            logger.warning(
                "No scene for session '%s' (tool %s, id %s) — rejecting script",
                session_id, tool_name, request_id,
            )
            return None, False, f"no scene for session {session_id}"
    elif bpy.context.window is not None:
        active = bpy.context.window.scene
        if active is not None and not is_lane_scene(active):
            _user_foreground_scene_name = active.name

    did_switch = False
    if target_scene and bpy.context.window and bpy.context.window.scene != target_scene:
        did_switch = True
        bpy.context.window.scene = target_scene
        logger.debug(f"Switched to scene '{target_scene.name}' for script execution")
    return target_scene, did_switch, None


def restore_after(did_switch: bool) -> None:
    """Restore the user's real foreground scene after a routed execution.

    Restores to the TRACKED user scene — not "whatever was active when this
    script started", which may itself be a throwaway lane scene.
    """
    if not did_switch or not bpy.context.window:
        return
    restore_scene = resolve_user_foreground_scene()
    if restore_scene is not None and bpy.context.window.scene != restore_scene:
        try:
            bpy.context.window.scene = restore_scene
        except Exception:
            pass  # Scene may have been deleted by the script


def archive_history(
    tool_name: str, script: str, result_dict: dict, target_scene, request_id: str
) -> None:
    """Operation history: archive every agent script/tool execution (fail-soft)."""
    try:
        from mixar.modules.operation_history.constants import HISTORY_SCRIPT_MARKER, HISTORY_TOOLS
        from mixar.modules.operation_history.core import store as _op_store
        from mixar.modules.operation_history.core.record import build_agent_record
        from mixar.modules.operation_history.core.scene_key import get_scene_history_id
        if tool_name in HISTORY_TOOLS or HISTORY_SCRIPT_MARKER in script:
            return
        hist_scene = target_scene if target_scene is not None else (
            bpy.context.window.scene if bpy.context.window else None)
        hist_sid = get_scene_history_id(hist_scene)
        wm = getattr(bpy.context, "window_manager", None)
        iid = getattr(wm, "mixie_instance_id", "") if wm else ""
        _op_store.append_operation(
            build_agent_record(tool_name=tool_name, result_dict=result_dict,
                               session_id=hist_sid, instance_id=iid, request_id=request_id),
            script_text=script,
        )
    except Exception as exc:  # never break execution/response on history failure
        logger.debug("operation_history: failed to record agent op: %s", exc)
