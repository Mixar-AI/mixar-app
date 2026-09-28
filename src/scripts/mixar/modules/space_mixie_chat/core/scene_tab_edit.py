# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Identity-safe scene renaming and batch close, shared by panel operators."""

import json

from ..constants import MANUAL_SCENE_NAME_PROP, is_lane_scene


def resolve_tabs(serialized):
    """Resolve a captured set of ID session_uids; never substitute by name."""
    from ..ui.operators.scene_tab_ops import ordered_tabs
    try:
        values = json.loads(serialized)
        if not isinstance(values, list) or not values or any(
                not isinstance(v, str) or not v.isdecimal() for v in values):
            raise ValueError
    except (ValueError, TypeError):
        return [], 'Invalid scene selection'
    requested = set(values)
    tabs = [s for s in ordered_tabs() if str(s.session_uid) in requested]
    if len(tabs) != len(requested):
        return [], 'The selected scenes changed; select them again'
    return tabs, ''


def rename_scene_tab(scene, name):
    from ..ui.operators.scene_tab_ops import _running, ordered_tabs, renumber_tabs
    if scene is None or is_lane_scene(scene):
        return False, 'That scene is no longer available'
    name = name.strip()
    if not name:
        return False, 'Enter a scene name'
    if name == scene.name:
        # Nothing to change. Never mark the scene as manually named here: the
        # inline field commits on click-away too, so this path is reached by
        # an accidental double-click and must leave automatic naming intact.
        return True, ''
    if _running(scene):
        return False, 'Wait for this scene’s agent to finish before renaming'
    try:
        # Freeze the visual order before changing its name-based fallback sort.
        tabs = ordered_tabs()
        scene.name = name  # Blender handles uniqueness and UTF-8 limits.
        scene[MANUAL_SCENE_NAME_PROP] = True
        renumber_tabs(tabs)
    except (RuntimeError, TypeError, AttributeError):
        return False, 'This scene cannot be renamed'
    return True, ''


def tab_has_chat(scene) -> bool:
    """True when the tab's transcript holds any message (its chat is worth keeping)."""
    try:
        return len(getattr(scene, 'mixie_chat_messages', None) or ()) > 0
    except Exception:  # noqa: BLE001
        return False


_FURNITURE_TYPES = frozenset({'CAMERA', 'LIGHT'})


def tab_is_empty(scene) -> bool:
    """Nothing to lose: no chat, no run, idle, and nothing in the scene but the
    camera and light a new tab is furnished with. Such a tab is deleted without
    a question (an Undo toast brings an equal one back)."""
    if scene is None or is_lane_scene(scene) or tab_has_chat(scene):
        return False
    try:
        from ..ui.operators.scene_tab_ops import _running
        if _running(scene):
            return False
    except Exception:  # noqa: BLE001
        return False
    try:
        return all(o.type in _FURNITURE_TYPES for o in scene.objects)
    except Exception:  # noqa: BLE001
        return False


def batch_preflight(serialized):
    from ..ui.operators.scene_tab_ops import _running, _connection_live
    tabs, reason = resolve_tabs(serialized)
    if reason:
        return [], reason
    if any(s.library is not None for s in tabs):
        return [], 'Linked scenes cannot be deleted here'
    if any(_running(s) for s in tabs) and not _connection_live():
        return [], 'Reconnect to stop the selected agents before deleting'
    return tabs, ''


def close_scene_tabs(serialized):
    """Validate the whole captured set before deleting; reuse per-tab cleanup."""
    from ..ui.operators.scene_tab_ops import (
        close_scene_tab, new_scene_tab, ordered_tabs, real_scenes, renumber_tabs)
    tabs, reason = batch_preflight(serialized)
    if reason:
        return 0, reason
    if len(tabs) == len(real_scenes()):
        try:
            new_scene_tab()  # Keep the invariant: a window always has a scene.
        except Exception:
            return 0, 'Could not create the replacement empty scene'
    # Windows showing a doomed tab move straight to a survivor, never to the
    # next tab in the batch (each hop would snapshot and switch every window).
    survivor = next((s for s in ordered_tabs() if s not in tabs), None)
    closed = 0
    for scene in tabs:
        ok, reason = close_scene_tab(scene, neighbour=survivor)
        if not ok:
            return closed, reason
        closed += 1
    renumber_tabs()
    return closed, ''
