# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Warm the Export sheet's engine logo at idle.

`bpy.utils.previews` fills an image on its first draw, so a logo loaded in
the sheet's own `invoke` showed an empty Unreal tile on the first opening.
Loading it a few seconds after startup (two 128 px PNGs, main thread, once)
has it ready before anyone clicks Export.
"""

import bpy

_WARM_AFTER_SECONDS = 4.0


def _warm():
    try:
        from mixar.modules.space_mixie_chat.core import engine_logos
        engine_logos.load()
        preview = engine_logos._collection.get("unreal") if engine_logos._collection else None
        if preview is not None:
            # Touch the pixels: the preview decodes its image on first access.
            _ = preview.image_size[0]
    except Exception:  # noqa: BLE001 - the tile falls back to its glyph
        pass
    return None


def register():
    if not bpy.app.timers.is_registered(_warm):
        bpy.app.timers.register(_warm, first_interval=_WARM_AFTER_SECONDS)


def unregister():
    if bpy.app.timers.is_registered(_warm):
        bpy.app.timers.unregister(_warm)


classes = ()
