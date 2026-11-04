# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The engines' logos for the Connect engine sheet's ENGINES rows.

``assets/engines/<key>.png`` (Godot's CC BY 4.0 icon, Unreal's "U" mark; see
NOTICE.md) loaded once into a ``bpy.utils.previews`` collection — the path
Blender's own add-ons use, which keeps the alpha — when the sheet first
opens, never inside a draw. ``icon_id(key)`` is 0 (no logo) before that, for
an engine without a file, or when loading fails; the row then shows its name
alone.
"""

from __future__ import annotations

import os

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "engines")
KEYS = ("godot", "unreal")
_collection = None


def load() -> None:
    """Load every logo once (main thread; two small PNGs)."""
    global _collection
    if _collection is not None:
        return
    try:
        import bpy.utils.previews
        _collection = bpy.utils.previews.new()
        for key in KEYS:
            path = os.path.join(ASSETS, f"{key}.png")
            if os.path.isfile(path):
                _collection.load(key, path, 'IMAGE')
    except Exception:  # noqa: BLE001 - a missing logo leaves the name alone
        _collection = None


def icon_id(key: str) -> int:
    """The logo's icon id for ``key`` ("godot" / "unreal"), else 0."""
    try:
        preview = _collection.get(key) if _collection is not None else None
        return int(preview.icon_id) if preview is not None else 0
    except Exception:  # noqa: BLE001
        return 0


def unload() -> None:
    global _collection
    if _collection is not None:
        try:
            import bpy.utils.previews
            bpy.utils.previews.remove(_collection)
        except Exception:  # noqa: BLE001
            pass
    _collection = None
