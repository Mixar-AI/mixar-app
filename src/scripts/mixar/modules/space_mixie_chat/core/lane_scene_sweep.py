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
Chat, stale-script drop) and removes any leftover lane scenes, mirroring the
backend's remove_scene semantics: objects visible ONLY in the lane scene are
deleted, anything any other scene can still see survives untouched.

Everything here is main-thread only (mutates scenes) and fail-soft.
"""

from mixar.config.logging_config import get_logger

from ..constants import AGENT_LANE_SESSION_PREFIX

logger = get_logger(__name__)


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


def sweep_leaked_lane_scenes() -> int:
    """Remove every leaked ``agentlane:*`` scene. Main thread only, fail-soft.

    No-ops while an agent session is still active — lanes are only "leaked"
    once nothing can legitimately clean them up anymore.
    """
    import bpy

    from .session import get_session_manager

    if get_session_manager().has_active_session():
        return 0

    lanes = [s for s in bpy.data.scenes if _is_leaked_lane_scene(s)]
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


def schedule_lane_scene_sweep(delay: float = 0.5) -> None:
    """Run the sweep shortly, on the main thread via a one-shot app timer.

    The small delay lets the teardown path that scheduled us fully settle
    (state flips, queued responses) before scenes are mutated. Safe to call
    from any teardown site; the sweep itself re-checks the active-session
    guard when it actually runs.
    """
    import bpy

    def _run():
        try:
            sweep_leaked_lane_scenes()
        except Exception:
            logger.warning("Lane scene sweep failed", exc_info=True)
        return None  # one-shot

    try:
        bpy.app.timers.register(_run, first_interval=delay)
    except Exception:
        logger.debug("Could not schedule lane scene sweep", exc_info=True)
