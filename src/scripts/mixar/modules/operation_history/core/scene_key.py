# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent per-scene operation-history id.

The operation log is a property of the *scene*, not of any single chat session — a scene
outlives sessions, and the most valuable manual edits happen before the user ever talks to
the agent. We therefore key all capture + reads by a stable id stored on the scene
(``scene.mixar_op_history_id``, saved in the .blend), assigned lazily on first use.
Pure except for the lazy attribute assignment; no bpy import needed.
"""

import uuid

from ..constants import NO_SESSION, SCENE_HISTORY_ID_PROP


def get_scene_history_id(scene) -> str:
    """Return the scene's persistent history id, assigning one if absent.

    Returns NO_SESSION for a missing scene or if the property can't be written
    (e.g. the property isn't registered yet) — capture/read still functions, degraded.
    """
    if scene is None:
        return NO_SESSION
    current = getattr(scene, SCENE_HISTORY_ID_PROP, "") or ""
    if current:
        return current
    new_id = uuid.uuid4().hex
    try:
        setattr(scene, SCENE_HISTORY_ID_PROP, new_id)
    except Exception:
        return NO_SESSION
    return new_id
