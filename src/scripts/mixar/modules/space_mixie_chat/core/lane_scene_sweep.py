# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Session-end sweep of leaked agent lane workspace scenes.

Scene-build mode runs each sub-build in a throwaway lane scene tagged
``mixie_session_id = "agentlane:{parent}:{n}"``. The backend normally removes
these itself (merge_scene on success, remove_scene on failure), but if the
agent session dies first, those removal scripts arrive post-session and are
dropped as stale by main_thread_executor — stranding the lane scenes in the
user's file. This sweep runs when a session ends (turn settles to IDLE, New
Chat, stale-script drop). Token-owned workspaces with output or an incomplete
merge remain available for backend reconciliation: session inactivity is not
proof that a timed-out mutation failed. Only proven empty/helper-only owned
workspaces may be swept. Legacy unowned lanes retain the old cleanup policy;
objects visible from any other scene always survive.

Everything here is main-thread only (mutates scenes) and fail-soft.
"""

from mixar.config.logging_config import get_logger

from ..constants import AGENT_LANE_SESSION_PREFIX

logger = get_logger(__name__)


def _retention_reason(scene) -> str:
    """Why a trusted workspace cannot be swept, or empty when cleanup is safe.

    The backend owns publication/discard decisions. A clone is output too,
    and an empty scene can still hold an incomplete publication transaction.
    An unreadable inventory is never proof that the workspace is disposable.
    """
    import bpy

    try:
        token = scene.get("mixar_workspace_token")
        if not token:
            return ""  # Pre-token legacy lane; keep its existing cleanup policy.
        for coll in bpy.data.collections:
            if coll.get("mixar_workspace_token") == token:
                state = coll.get("mixar_workspace_state")
                plan = coll.get("mixar_workspace_merge_plan")
                if state != "committed" and (state or plan is not None):
                    return "merge_incomplete"
        for obj in scene.collection.all_objects:
            if (obj.get("mixar_workspace_source")
                    or obj.get("mixar_workspace_token") != token
                    or not obj.get("mixar_workspace_helper")):
                return "workspace_output"
    except Exception:
        return "inventory_unavailable"
    return ""


def _lane_session_id(scene) -> str:
    """Scene's mixie session id — property first, custom-prop fallback."""
    sid = getattr(scene, "mixie_session_id", "") or ""
    if not sid:
        try:
            sid = scene.get("mixie_session_id", "") or ""
        except Exception:
            sid = ""
    return sid


def _is_leaked_lane_scene(scene) -> bool:
    return _lane_session_id(scene).startswith(AGENT_LANE_SESSION_PREFIX)


def _point_windows_away_from(lane) -> None:
    """Make sure no window is left showing the scene we are about to remove."""
    import bpy

    fallback = None
    for s in bpy.data.scenes:
        if s is not lane and not _is_leaked_lane_scene(s):
            fallback = s
            break
    if fallback is None:
        fallback = next((s for s in bpy.data.scenes if s is not lane), None)
    if fallback is None:
        return
    for wm in bpy.data.window_managers:
        for window in wm.windows:
            try:
                if window.scene == lane:
                    window.scene = fallback
            except Exception:
                logger.debug("Could not switch window off lane scene", exc_info=True)


def _remove_lane_scene(lane) -> bool:
    """Remove one lane scene, mirroring the backend's remove_scene script.

    Objects are dropped only when NO other scene can still see them, decided
    by scene membership (``collection.all_objects`` recurses into linked child
    collections) — never by user counts.
    """
    import bpy

    if len(bpy.data.scenes) <= 1:
        return False

    reason = _retention_reason(lane)
    if reason:
        from mixar.modules.common.scenes_log import slog
        slog("sweep.retained", None, session_id=lane_parent_session(lane),
             lane=getattr(lane, "name", "?"), reason=reason)
        return False

    _point_windows_away_from(lane)

    outside = set()
    for s in bpy.data.scenes:
        if s is not lane:
            for o in s.collection.all_objects:
                outside.add(o.name)
    for o in list(lane.collection.all_objects):
        if o.name not in outside:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                logger.debug(
                    "Could not remove lane-only object %s",
                    getattr(o, "name", "?"),
                    exc_info=True,
                )
    bpy.data.scenes.remove(lane)
    return True


def lane_parent_session(scene) -> str:
    """The chat session a lane belongs to (``mixar_workspace_main_session``,
    stamped by the backend's workspace script), else ``""``."""
    try:
        return str(scene.get("mixar_workspace_main_session", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def sweep_leaked_lane_scenes(parent_session_id: str = "") -> int:
    """Remove every leaked ``agentlane:*`` scene. Main thread only, fail-soft.

    No-ops while the parent is active. Token-owned output remains recoverable
    after its session ends; inactivity alone never authorizes deleting it.
    """
    import bpy

    from .session import get_session_manager

    # A lane is leaked once ITS parent chat session is no longer active; other
    # tabs' running agents keep their lanes (parallel scenes). A lane with no
    # parent stamp keeps the old rule: swept only while no session is active.
    from mixar.modules.common.scenes_log import slog

    session = get_session_manager()
    any_active = session.has_active_session()
    lanes = []
    for s in bpy.data.scenes:
        if not _is_leaked_lane_scene(s):
            continue
        parent = lane_parent_session(s)
        if parent_session_id and parent != parent_session_id:
            continue
        if parent and session.has_active_session(parent):
            continue
        if not parent and any_active:
            continue
        slog("sweep.lane", None, session_id=parent, lane=s.name)
        lanes.append(s)
    removed = 0
    for lane in lanes:
        name = getattr(lane, "name", "?")
        try:
            if _remove_lane_scene(lane):
                removed += 1
        except Exception:
            logger.warning("Could not sweep lane scene %s", name, exc_info=True)
    if removed:
        logger.info("Swept %d leaked agent lane scene(s)", removed)
    return removed


def schedule_lane_scene_sweep(delay: float = 0.5, parent_session_id: str = "") -> None:
    """Run the sweep shortly, on the main thread via a one-shot app timer.

    The small delay lets the teardown path that scheduled us fully settle
    (state flips, queued responses) before scenes are mutated. Safe to call
    from any teardown site; the sweep itself re-checks the active-session
    guard when it actually runs.
    """
    import bpy

    def _run():
        try:
            sweep_leaked_lane_scenes(parent_session_id)
        except Exception:
            logger.warning("Lane scene sweep failed", exc_info=True)
        return None  # one-shot

    try:
        bpy.app.timers.register(_run, first_interval=delay)
    except Exception:
        logger.debug("Could not schedule lane scene sweep", exc_info=True)
