# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent per-scene operation-history id.

The operation log is a property of the *scene*, not of any single chat session — a scene
outlives sessions, and the most valuable manual edits happen before the user ever talks to
the agent. We therefore key all capture + reads by a stable id stored on the scene
(``scene.mixar_op_history_id``, saved in the .blend), assigned lazily on first use.

Undo restores the scene datablock, so an undo past the step that assigned the id blanks
the property. Without a memory of the id the undo handler would mint a new one and every
undo would open a new history folder (13,658 of them were found on one machine). The ids
handed out in this process are therefore remembered by the scene's ``session_uid`` and
written back when the property comes up empty. ``session_uid`` survives undo and rename
and is never reused within a session, so a new scene that takes a deleted tab's name
never inherits that tab's history. `forget_all` runs on file load.
Pure except for the lazy attribute assignment; no bpy import needed.
"""

import uuid

from ..constants import NO_SESSION, SCENE_HISTORY_ID_PROP

_remembered: dict = {}   # scene session_uid -> id handed out or seen in this process


def get_scene_history_id(scene) -> str:
    """Return the scene's persistent history id, assigning one if absent.

    Returns NO_SESSION for a missing scene or if the property can't be written
    (e.g. the property isn't registered yet) — capture/read still functions, degraded.
    """
    if scene is None:
        return NO_SESSION
    uid = getattr(scene, "session_uid", None)
    current = getattr(scene, SCENE_HISTORY_ID_PROP, "") or ""
    if current:
        if uid is not None:
            _remembered[uid] = current
        return current
    new_id = (_remembered.get(uid) if uid is not None else None) or uuid.uuid4().hex
    try:
        setattr(scene, SCENE_HISTORY_ID_PROP, new_id)
    except Exception:
        return NO_SESSION
    if uid is not None:
        _remembered[uid] = new_id
    return new_id


def remembered_id(scene) -> str:
    """The id remembered for ``scene`` in this process, or ``""``."""
    return _remembered.get(getattr(scene, "session_uid", None), "")


def forget_all() -> None:
    """Drop the remembered ids (a loaded file's scenes are new datablocks)."""
    _remembered.clear()
