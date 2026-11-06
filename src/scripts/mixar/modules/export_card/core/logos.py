# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The export tiles' and engine chips' logos.

``assets/logos/<key>.png`` (see NOTICE.md for each mark's owner) plus the
Godot and Unreal marks the Connect engine sheet already ships, loaded once
into a ``bpy.utils.previews`` collection when the card first opens — never
inside a draw. ``icon_id(key)`` is 0 before that, for an unknown key, or
when loading failed; the tile then shows its label alone.
"""

from __future__ import annotations

import os

_MODULE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(_MODULE, "assets", "logos")
ENGINE_ASSETS = os.path.join(os.path.dirname(_MODULE), "space_mixie_chat", "assets", "engines")
KEYS = ("mixar", "blend", "gltf", "fbx", "usd", "obj", "stl", "png", "mp4", "web",
        "unity", "apple")
ENGINE_KEYS = ("godot", "unreal")
_collection = None


def _path(key: str) -> str:
    folder = ENGINE_ASSETS if key in ENGINE_KEYS else ASSETS
    return os.path.join(folder, f"{key}.png")


def load() -> None:
    """Load every logo once (main thread; fourteen small PNGs)."""
    global _collection
    if _collection is not None:
        return
    try:
        import bpy.utils.previews
        _collection = bpy.utils.previews.new()
        for key in KEYS + ENGINE_KEYS:
            path = _path(key)
            if os.path.isfile(path):
                preview = _collection.load(key, path, 'IMAGE')
                # The painters draw the full-size preview; the sheet tag asks
                # for it on every build (`UI_layout_mixar_sheet_tag_last`).
                # Reading the size here also loads it once at open, off the
                # draw path, so the first frame already has it.
                _ = preview.image_size
    except Exception:  # noqa: BLE001 - a missing logo leaves the label alone
        _collection = None


def icon_id(key: str) -> int:
    if not key:
        return 0
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
