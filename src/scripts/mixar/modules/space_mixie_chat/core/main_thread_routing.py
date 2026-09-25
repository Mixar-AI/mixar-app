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

from mixar.modules.common.scenes_log import slog

from ..constants import is_lane_scene, is_non_scene_routing_session

logger = get_logger(__name__)

# The user's genuine foreground scene — the one window.scene should return to
# after a per-scene-routed (or lane) script flips away from it. Tracked by name
# because Scene datablocks are not safe to hold across undo/file-load. Updated
# only when an active-scene-follow script runs (agent:/empty session), i.e. the
# scene the user is actually looking at.
_user_foreground_scene_name: str = ""
# The scene the window showed right before the LAST pin. Restore goes back to
# exactly this scene (a user viewing tab B while tab A's agent runs stays on
# B); the tracked foreground scene above is only the fallback when it is gone.
_restore_scene_name: str = ""
# The session whose pin the next restore undoes (its dossier gets the restore).
_restore_session_id: str = ""
# Read by the backend's render template: a window screenshot while the pin has
# flipped window.scene without a redraw would show the previous scene's pixels.
ROUTE_SWITCHED_KEY = "mixie_route_switched"


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


def _window():
    """The window whose ``scene`` pins a routed script: the context window, or
    the first window when a timer tick carries none. ``(window, kind)``."""
    win = getattr(bpy.context, "window", None)
    if win is not None:
        return win, "context"
    wm = getattr(bpy.context, "window_manager", None)
    windows = list(getattr(wm, "windows", None) or []) if wm is not None else []
    if windows:
        return windows[0], "borrowed"
    return None, "none"


def _set_route_switched(flag: bool) -> None:
    try:
        bpy.app.driver_namespace[ROUTE_SWITCHED_KEY] = bool(flag)
    except Exception:  # noqa: BLE001 — a missing namespace only loses the hint
        pass


def scenes_for_session(session_id: str) -> list:
    return [s for s in bpy.data.scenes if getattr(s, "mixie_session_id", "") == session_id]


def route_request(
    session_id: str, tool_name: str, request_id: str
) -> tuple[Optional[object], bool, Optional[str]]:
    """Resolve and switch to the target scene for a script.

    Returns ``(target_scene, did_switch, error)``. ``error`` is set (and no
    switch happens) when a per-scene session matches no scene, matches more
    than one, or cannot be pinned because no window exists.
    """
    global _user_foreground_scene_name, _restore_scene_name, _restore_session_id
    target_scene = None
    window, window_kind = _window()
    if not is_non_scene_routing_session(session_id):
        matches = scenes_for_session(session_id)
        if not matches:
            logger.warning(
                "No scene for session '%s' (tool %s, id %s) — rejecting script",
                session_id, tool_name, request_id,
            )
            slog("route.reject", None, session_id=session_id, reason="no_scene", tool=tool_name)
            return None, False, f"no scene for session {session_id}"
        if len(matches) > 1:
            names = ", ".join(s.name for s in matches)
            logger.warning(
                "Session '%s' matches %d scenes (%s) (tool %s, id %s) — rejecting script",
                session_id, len(matches), names, tool_name, request_id,
            )
            slog("route.reject", None, session_id=session_id, reason="ambiguous", scenes=names, tool=tool_name)
            return None, False, f"session {session_id} matches {len(matches)} scenes ({names}); refusing to guess"
        target_scene = matches[0]
    elif window is not None:
        active = window.scene
        if active is not None and not is_lane_scene(active):
            _user_foreground_scene_name = active.name

    did_switch = False
    if target_scene is not None:
        current = window.scene if window is not None else getattr(bpy.context, "scene", None)
        if current != target_scene:
            if window is None:
                slog("route.reject", target_scene, reason="no_window", tool=tool_name)
                return None, False, f"no window to pin scene {target_scene.name!r} for session {session_id}"
            did_switch = True
            _restore_scene_name = (
                current.name if current is not None and not is_lane_scene(current) else ""
            )
            _restore_session_id = session_id
            window.scene = target_scene
            logger.debug(f"Switched to scene '{target_scene.name}' for script execution")
            slog("route.pin", target_scene, target=target_scene.name,
                 was=getattr(current, "name", ""), window=window_kind, tool=tool_name)
    _set_route_switched(did_switch)
    return target_scene, did_switch, None


def restore_after(did_switch: bool) -> None:
    """Restore the scene the user was looking at before the pin.

    Falls back to the TRACKED user scene — never "whatever was active when
    this script started", which may itself be a throwaway lane scene.
    """
    _set_route_switched(False)
    if not did_switch:
        return
    window, _ = _window()
    if window is None:
        return
    restore_scene = bpy.data.scenes.get(_restore_scene_name) if _restore_scene_name else None
    if restore_scene is None or is_lane_scene(restore_scene):
        restore_scene = resolve_user_foreground_scene()
    if restore_scene is not None and window.scene != restore_scene:
        try:
            window.scene = restore_scene
            slog("route.restore", None, session_id=_restore_session_id, to=restore_scene.name)
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
