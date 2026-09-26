# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-tab state behind the Parallel Agents panel.

Parallel scenes: every chat session (scene tab) streams its own task list.
The WindowManager mirror the C++ panel draws is a projection of ONE of them —
the tab the window shows — so a background tab's workers never overwrite the
visible panel, and switching tabs swaps the panel. This module keeps each
session's last task list and its dismissal memory, watches which tab is in
front, and asks ``cards`` to re-project when that changes. ``cards`` owns
every write to the mirror.
"""

from __future__ import annotations

from typing import Optional

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_WATCH_INTERVAL_S = 0.5


class TabMemory:
    """What one tab's panel has let go of.

    ``dismissed``: task ids whose card left the mirror during the tab's
    current fan-out — a user dismissal or the auto-exit of a finished card.
    ``dismiss_card`` removes the row, but the backend keeps streaming the same
    task list, so a later membership rebuild would re-add the card that just
    left. Scoped to the fan-out: ``clear_cards`` resets it, so an id is never
    silently hidden in a later turn (synthetic ``idx:N`` ids recur). A
    dismissal only holds for a task that is FINISHED: reopened work streams
    back PENDING/IN_PROGRESS and the card comes back.

    ``exit_epoch``: bumped every time a task id is revived. A pending exit
    timer captures the epoch it was scheduled under and does nothing when it
    no longer matches, so the timer armed for the previous completion cannot
    remove the new card.

    Per tab, so switching tabs neither forgets a dismissal nor resurrects the
    card on the way back.
    """

    __slots__ = ("dismissed", "exit_epoch")

    def __init__(self) -> None:
        self.dismissed: set[str] = set()
        self.exit_epoch: dict[str, int] = {}

    def reset(self) -> None:
        self.dismissed.clear()
        self.exit_epoch.clear()


#: session id -> the LAST task list of that chat session (card records).
_sessions: dict[str, list[dict]] = {}
_memory: dict[str, TabMemory] = {}
#: The session whose records the mirror currently shows.
_projected_sid: str = ""


def memory(sid: str) -> TabMemory:
    mem = _memory.get(sid)
    if mem is None:
        mem = _memory[sid] = TabMemory()
    return mem


def records(sid: str) -> Optional[list[dict]]:
    return _sessions.get(sid)


def store(sid: str, recs: list[dict]) -> None:
    _sessions[sid] = [dict(rec) for rec in recs]
    _ensure_watch()


def forget(sid: str, *, reset_dismissals: bool) -> None:
    _sessions.pop(sid, None)
    if reset_dismissals:
        _memory.pop(sid, None)


def projected_sid() -> str:
    return _projected_sid


def mark_projected(sid: str) -> None:
    global _projected_sid
    _projected_sid = sid


def foreground_scene():
    """The scene the user is looking at (the window's), else the context scene."""
    window = getattr(bpy.context, "window", None)
    scene = getattr(window, "scene", None) if window is not None else None
    return scene if scene is not None else getattr(bpy.context, "scene", None)


def sid_of(scene) -> str:
    return (getattr(scene, "mixie_session_id", "") or "") if scene is not None else ""


def foreground_sid() -> str:
    return sid_of(foreground_scene())


def project_foreground() -> None:
    """Show the visible tab's cards. A no-op while the tab has not changed.

    The stored records are card records already (normalized once when they
    arrived); they are applied to the mirror directly, never re-normalized.
    """
    global _projected_sid
    sid = foreground_sid()
    if sid == _projected_sid:
        return
    _projected_sid = sid
    from .cards import apply_records, clear_mirror  # noqa: PLC0415 — cards imports this module

    recs = _sessions.get(sid)
    if recs:
        apply_records([dict(rec) for rec in recs], sid, foreground_scene())
    else:
        clear_mirror(reset_dismissals=False)


def _watch_foreground():
    """Timer: keep the mirror on the visible tab; stops once nothing is stored."""
    try:
        project_foreground()
    except Exception:  # noqa: BLE001 — the panel never breaks the app
        logger.debug("card projection failed", exc_info=True)
    return _WATCH_INTERVAL_S if _sessions else None


def _ensure_watch() -> None:
    try:
        if not bpy.app.timers.is_registered(_watch_foreground):
            bpy.app.timers.register(_watch_foreground, first_interval=_WATCH_INTERVAL_S)
    except Exception:  # noqa: BLE001
        pass
