# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The two glyphs of the Zen toolbar's Scenes button: ``>≡`` (open the
drawer) and ``≡<`` (close it).

Blender ships no such icon, so the PNGs are rasterised once per session into
the temp dir and loaded through ``bpy.utils.previews`` — the same path the
agent bubble's pill dots take (``agent_bubble.core.pill_icons``). Generation
runs from a ``bpy.app.timers`` callback, never inside the toolbar draw: until
it lands ``icon_id`` returns 0 and the button falls back to a stock icon.
"""

from __future__ import annotations

import os
import tempfile

import bpy
import bpy.utils.previews

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_SIZE = 32
_NAMES = {True: "scenes_open", False: "scenes_close"}
_pcoll = None
_scheduled = False


#: The glyph fills this fraction of the icon square, centred: the rest is
#: breathing room between the strokes and the button's rounded rectangle.
_GLYPH_SCALE = 0.72


def _segments(open_glyph: bool):
    """Line segments in a 0..1 square, y up: three bars and a chevron."""
    bars_x = (0.42, 0.94) if open_glyph else (0.06, 0.58)
    bars = [((bars_x[0], y), (bars_x[1], y)) for y in (0.25, 0.5, 0.75)]
    if open_glyph:
        chevron = [((0.08, 0.26), (0.28, 0.5)), ((0.28, 0.5), (0.08, 0.74))]
    else:
        chevron = [((0.92, 0.26), (0.72, 0.5)), ((0.72, 0.5), (0.92, 0.74))]

    def shrink(pt):
        return (0.5 + (pt[0] - 0.5) * _GLYPH_SCALE, 0.5 + (pt[1] - 0.5) * _GLYPH_SCALE)

    return [(shrink(a), shrink(b)) for a, b in bars + chevron]


def _distance(px, py, seg):
    (x0, y0), (x1, y1) = seg
    dx, dy = x1 - x0, y1 - y0
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0.0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length2))
    cx, cy = x0 + t * dx, y0 + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _pixels(open_glyph: bool, size: int = _SIZE):
    """Flat RGBA floats, white strokes on transparent, bottom-up rows."""
    segments = _segments(open_glyph)
    half = 0.055 * _GLYPH_SCALE  # stroke half-width in the unit square
    out = []
    for row in range(size):
        py = (row + 0.5) / size
        for col in range(size):
            px = (col + 0.5) / size
            d = min(_distance(px, py, seg) for seg in segments)
            alpha = max(0.0, min(1.0, (half - d) * size + 0.5))
            out.extend([1.0, 1.0, 1.0, alpha])
    return out


def _write_png(path: str, open_glyph: bool) -> bool:
    name = "_mixar_scenes_toggle_tmp"
    stale = bpy.data.images.get(name)
    if stale is not None:
        bpy.data.images.remove(stale)
    img = bpy.data.images.new(name, _SIZE, _SIZE, alpha=True, float_buffer=False)
    try:
        img.pixels = _pixels(open_glyph)
        img.update()
        img.filepath_raw = path
        img.file_format = 'PNG'
        img.save()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("scenes toggle icon %s failed: %s", path, exc)
        return False
    finally:
        try:
            bpy.data.images.remove(img)
        except Exception:  # noqa: BLE001
            pass


def _generate():
    global _pcoll
    # The folder name carries the glyph revision: a cached PNG from an older
    # build must not outlive a redesign.
    folder = os.path.join(tempfile.gettempdir(), "mixar_scenes_toggle_icons_v2")
    os.makedirs(folder, exist_ok=True)
    pcoll = bpy.utils.previews.new()
    for open_glyph, name in _NAMES.items():
        path = os.path.join(folder, name + ".png")
        if (not os.path.isfile(path) or os.path.getsize(path) <= 0) and not _write_png(path, open_glyph):
            continue
        preview = pcoll.load(name, path, 'IMAGE')
        preview.icon_size[0]  # force the lazy decode now, not on the draw thread
    _pcoll = pcoll
    return None


def icon_id(drawer_open: bool) -> int:
    """icon_id of the glyph to show for the current drawer state, or 0.

    ``drawer_open`` True shows ``≡<`` (the button will close the drawer)."""
    global _scheduled
    if _pcoll is None:
        if not _scheduled:
            _scheduled = True
            try:
                bpy.app.timers.register(_generate, first_interval=0.0)
            except Exception:  # noqa: BLE001
                _scheduled = False
        return 0
    preview = _pcoll.get(_NAMES[not drawer_open])
    return preview.icon_id if preview is not None else 0


def unregister() -> None:
    global _pcoll, _scheduled
    if _pcoll is not None:
        try:
            bpy.utils.previews.remove(_pcoll)
        except Exception:  # noqa: BLE001
            pass
    _pcoll = None
    _scheduled = False
