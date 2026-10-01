# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What an undo or redo must never do to the scene tabs.

Blender's memfile undo restores the whole document, including which scene
each window shows: the step was written while an agent script had the
window PINNED to its tab or to a worker lane scene, so a plain Ctrl-Z in the
user's tab moved them to the agent's tab, or into the lane itself, and a step
older than a tab's creation deleted the tab under its live run (2026-09-29
lab; the production crash of the same day sat on this path).

Two invariants, enforced around every undo and redo by ``undo_guard``:

1. **The view does not move.** Each window returns to the scene it showed
   before the undo when that scene still exists; a window left on a lane
   scene is moved to the user's tab, never left inside a workspace.
2. **No run outlives its tab silently.** A session whose scene vanished in the
   undo while its turn or run was open is cancelled on the backend and its
   executor turn ended, so it stops building (and billing) into nothing.

Everything here takes plain arguments so it is testable without Blender;
``undo_guard`` passes the live ``bpy`` objects.
"""

from __future__ import annotations

from typing import Callable, Iterable

from mixar.config.logging_config import get_logger

from ..constants import SessionState, is_lane_scene

logger = get_logger(__name__)

_ACTIVE = (SessionState.BUSY, SessionState.MODIFYING, SessionState.AWAITING_INPUT)


def _slog(event: str, **kv) -> None:
    try:
        from mixar.modules.common.scenes_log import slog
        slog(event, None, **kv)
    except Exception:  # noqa: BLE001 — a log line never breaks undo
        pass


# -- Snapshots (undo_pre / redo_pre) ------------------------------------------


def snapshot_view(windows: Iterable) -> dict[int, str]:
    """Which real scene each window shows, by window index. Lanes are not
    recorded: a window on a lane has nowhere sensible to return to."""
    saved: dict[int, str] = {}
    for index, window in enumerate(windows):
        scene = getattr(window, "scene", None)
        if scene is None or is_lane_scene(scene):
            continue
        saved[index] = scene.name
    return saved


def snapshot_runs(scenes: Iterable, session) -> dict[str, str]:
    """Sessions with a live turn or an open run, mapped to their scene name."""
    live: dict[str, str] = {}
    for scene in scenes:
        if is_lane_scene(scene):
            continue
        sid = getattr(scene, "mixie_session_id", "") or ""
        if not sid:
            continue
        try:
            active = session.get_state(scene) in _ACTIVE or session.run_open(scene)
        except Exception:  # noqa: BLE001 — a scene mid-teardown
            continue
        if active:
            live[sid] = scene.name
    return live


# -- Repairs (undo_post / redo_post) ------------------------------------------


def restore_view(windows: Iterable, saved: dict[int, str], scenes_by_name: Callable[[str], object],
                 real_scenes: Iterable) -> list[tuple[int, str, str]]:
    """Put every window back on the scene it showed before the undo.

    A window whose saved scene is gone keeps its current scene unless that is
    a lane, in which case it goes to the first real scene. Returns the moves
    made as ``(window index, from, to)``.
    """
    moves: list[tuple[int, str, str]] = []
    fallback = next((s for s in real_scenes if not is_lane_scene(s)), None)
    for index, window in enumerate(windows):
        current = getattr(window, "scene", None)
        current_name = getattr(current, "name", "")
        target = None
        wanted = saved.get(index)
        if wanted:
            candidate = scenes_by_name(wanted)
            if candidate is not None and not is_lane_scene(candidate):
                target = candidate
        if target is None and (current is None or is_lane_scene(current)):
            target = fallback
        if target is None or target is current:
            continue
        try:
            window.scene = target
        except Exception:  # noqa: BLE001 — a window mid-teardown
            logger.debug("Could not restore window %d to %s", index, target.name, exc_info=True)
            continue
        moves.append((index, current_name, target.name))
        _slog("undo.view_restored", window=index, was=current_name, to=target.name,
              off_lane=bool(current is not None and is_lane_scene(current)))
    return moves


def cancel_orphaned_runs(saved_runs: dict[str, str], live_session_ids: Iterable[str],
                         cancel: Callable[[str], None], end_turn: Callable[[str], None]) -> list[str]:
    """Cancel every session that was running before the undo and has no scene
    after it. Returns the session ids cancelled."""
    alive = set(live_session_ids)
    orphaned: list[str] = []
    for sid, scene_name in saved_runs.items():
        if sid in alive:
            continue
        try:
            end_turn(sid)
        except Exception:  # noqa: BLE001
            logger.debug("Could not end the executor turn of %s", sid[:8], exc_info=True)
        try:
            cancel(sid)
        except Exception:  # noqa: BLE001
            logger.warning("Could not cancel the orphaned run of %s", sid[:8], exc_info=True)
        orphaned.append(sid)
        _slog("undo.orphaned_run", session_id=sid, scene=scene_name)
        logger.warning("Undo removed scene %r under its live run; session %s cancelled",
                       scene_name, sid[:8])
    return orphaned


# -- Wiring helpers for undo_guard --------------------------------------------


def live_session_ids(scenes: Iterable) -> list[str]:
    return [getattr(s, "mixie_session_id", "") or "" for s in scenes if not is_lane_scene(s)]


def repair_after_undo(saved_view: dict[int, str], saved_runs: dict[str, str]) -> None:
    """Apply both invariants against the live document. Main thread only."""
    import bpy

    windows = list(bpy.context.window_manager.windows)
    scenes = list(bpy.data.scenes)
    restore_view(windows, saved_view, bpy.data.scenes.get, scenes)
    if not saved_runs:
        return
    from .executor import get_executor
    from ..ui.operators.session_ops import send_cancel_request_async

    cancel_orphaned_runs(saved_runs, live_session_ids(scenes),
                         send_cancel_request_async, get_executor().end_agent_turn)
