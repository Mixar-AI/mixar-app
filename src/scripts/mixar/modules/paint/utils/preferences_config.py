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


def save_preferences() -> None:
    """Persist current preferences to disk.

    Reads values from ``bpy.context.scene.mixar_paint_preferences`` and
    writes them to the JSON file returned by :func:`get_prefs_path`.  The
    function is a no-op when called during :func:`load_preferences` to
    prevent recursive writes.
    """
    if _loading:
        return

    scene = getattr(bpy.context, 'scene', None)
    if scene is None:
        return

    prefs = getattr(scene, 'mixar_paint_preferences', None)
    if prefs is None:
        return

    data = {}
    for prop in prefs.bl_rna.properties:
        key = prop.identifier
        if key == 'rna_type':
            continue
        try:
            data[key] = getattr(prefs, key)
        except Exception:
            pass

    try:
        path = get_prefs_path()
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=4)
        logger.debug("Mixar Paint preferences saved to %s", path)
    except Exception as exc:
        logger.warning("Failed to save Mixar Paint preferences: %s", exc)


def load_preferences() -> None:
    """Load persisted preferences from disk into the current scene.

    If no preferences file exists the function is a no-op; the property
    group's defaults remain in effect.
    """
    global _loading

    scene = getattr(bpy.context, 'scene', None)
    if scene is None:
        return

    prefs = getattr(scene, 'mixar_paint_preferences', None)
    if prefs is None:
        return

    path = get_prefs_path()
    if not os.path.exists(path):
        logger.debug("No Mixar Paint preferences file found at %s — using defaults", path)
        return

    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning("Failed to read Mixar Paint preferences from %s: %s", path, exc)
        return

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

    logger.debug("Mixar Paint preferences loaded from %s", path)
