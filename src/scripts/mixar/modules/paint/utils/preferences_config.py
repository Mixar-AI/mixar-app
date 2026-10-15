# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""JSON-based persistence for Mixar Paint preferences.

Preferences are stored in Blender's user config directory so they persist
across sessions and blend file changes, independent of the .blend file.
"""

import json
import os

import bpy
from bpy.utils import user_resource

from ....config.logging_config import get_logger

logger = get_logger(__name__)

# Flag to suppress saves during initial load to avoid feedback loops
_loading = False


def get_prefs_path() -> str:
    """Return the path to the Mixar Paint preferences JSON file."""
    config_dir = user_resource('CONFIG', path='mixar_paint', create=True)
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, 'preferences.json')


def _read_prefs_file() -> dict:
    """The saved preferences as a dict; {} when missing or unreadable."""
    path = get_prefs_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning("Failed to read Mixar Paint preferences from %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _write_prefs_file(data: dict) -> None:
    """Atomically replace preferences.json (temp file + os.replace)."""
    path = get_prefs_path()
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=4)
    os.replace(tmp_path, path)


def _scene_prefs(scene):
    return getattr(scene, 'mixar_paint_preferences', None) if scene is not None else None


def save_preferences(prefs=None, key=None) -> None:
    """Merge preference values into the JSON file.

    ``key`` names the ONE property that changed (every property's update
    callback passes its own name): only that key is written and every other
    saved key is kept, so an edit made in a scene that still holds defaults
    (a new scene tab) never resets the rest. Without ``key`` every property
    of ``prefs`` is merged. ``prefs`` defaults to the current scene's group.
    A no-op while :func:`load_preferences` applies values.
    """
    if _loading:
        return

    if prefs is None:
        prefs = _scene_prefs(getattr(bpy.context, 'scene', None))
    if prefs is None:
        return

    if key is not None:
        keys = [key]
    else:
        keys = [p.identifier for p in prefs.bl_rna.properties if p.identifier != 'rna_type']

    data = _read_prefs_file()
    for name in keys:
        try:
            data[name] = getattr(prefs, name)
        except Exception:
            pass

    try:
        _write_prefs_file(data)
        logger.debug("Mixar Paint preferences saved (%s)", key or "all")
    except Exception as exc:
        logger.warning("Failed to save Mixar Paint preferences: %s", exc)


def _apply(prefs, data: dict) -> None:
    global _loading
    _loading = True
    try:
        for key, value in data.items():
            if hasattr(prefs, key):
                try:
                    setattr(prefs, key, value)
                except Exception as exc:
                    logger.debug("Could not restore preference '%s': %s", key, exc)
    finally:
        _loading = False


# session_uid of every scene whose group received the saved preferences.
# Reset on file load; hydrate_new_scenes() fills scenes created afterwards
# (scene tabs, bpy.data.scenes.new) so they never start from defaults.
_hydrated_scenes = set()


def load_preferences(scene=None) -> None:
    """Load persisted preferences into ``scene`` (default: the current scene).

    If no preferences file exists the property group's defaults remain.
    """
    if scene is None:
        scene = getattr(bpy.context, 'scene', None)
    prefs = _scene_prefs(scene)
    if prefs is None:
        return
    _mark_hydrated(scene)
    data = _read_prefs_file()
    if data:
        _apply(prefs, data)


def _mark_hydrated(scene) -> None:
    uid = getattr(scene, 'session_uid', None)
    if isinstance(uid, int):
        _hydrated_scenes.add(uid)


def reset_hydration() -> None:
    """Forget hydrated scenes (a file load replaced every Scene)."""
    _hydrated_scenes.clear()


def hydrate_new_scenes() -> int:
    """Load the saved preferences into scenes not hydrated yet; returns the count.

    Cheap enough for a UI timer: one session_uid lookup per scene, and the
    JSON is read only when a new scene exists.
    """
    try:
        scenes = list(bpy.data.scenes)
    except Exception:
        return 0
    pending = [s for s in scenes
               if isinstance(getattr(s, 'session_uid', None), int)
               and s.session_uid not in _hydrated_scenes]
    if not pending:
        return 0
    data = _read_prefs_file()
    for scene in pending:
        _mark_hydrated(scene)
        prefs = _scene_prefs(scene)
        if prefs is not None and data:
            _apply(prefs, data)
    return len(pending)


def migrate_addon_projects_dir() -> bool:
    """One shot: move a per-Scene ``addon_projects_dir`` into the user config.

    The projects root used to be a field of this group (and so of
    preferences.json and of every Scene). Takes the saved JSON value first,
    then any Scene that still stores one; blanks and the default are not
    worth carrying. The first successful pass always writes the key (``""``
    = the default when nothing was found), so no later file load can pull a
    root out of someone else's .blend. Returns True when a value was migrated.
    """
    from ....config.config import (
        ADDON_PROJECTS_DIR_KEY,
        DEFAULT_ADDON_PROJECTS_DIR,
        has_addon_projects_dir,
        set_addon_projects_dir,
    )

    if has_addon_projects_dir():
        return False
    candidates = [_read_prefs_file().get(ADDON_PROJECTS_DIR_KEY)]
    try:
        for scene in bpy.data.scenes:
            prefs = _scene_prefs(scene)
            getter = getattr(prefs, 'get', None)
            if callable(getter):
                candidates.append(getter(ADDON_PROJECTS_DIR_KEY))
    except Exception:
        pass
    found = next(
        (v for v in candidates
         if isinstance(v, str) and v.strip() not in ("", DEFAULT_ADDON_PROJECTS_DIR)),
        "",
    )
    if not set_addon_projects_dir(found):
        # add_config keeps the value in memory even when the write fails,
        # so the key reads as present for the rest of this session: the
        # migration is retried at the next startup.
        return False
    if found:
        logger.info("Migrated the add-on projects folder into the user config")
    return bool(found)
