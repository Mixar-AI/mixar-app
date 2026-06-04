# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Custom green / grey / yellow pill icons for the Agent Bubble.

Generates three small antialiased circle PNGs at startup (in the
user's tempdir), then loads them via `bpy.utils.previews.load()` —
the standard well-tested icon-loading path Blender's own addons use.

Earlier revisions tried `bpy.data.images.new()` + writing
`image.preview.icon_pixels_float` directly, but that path renders
icon-only operator buttons (text="") as solid coloured squares
because Blender's auto-derived icon thumbnail loses the alpha
channel on that specific render path. `bpy.utils.previews.load()`
goes through the same icon-render code as built-in icons (e.g.
RECORD_ON / RADIOBUT_ON) which preserves alpha correctly.

The PNG files are written once per Mixar boot. We use the user's
tempdir (cleaned up by the OS) so we don't leave artifacts behind
in the project tree.
"""

from __future__ import annotations

import os
import tempfile

import bpy
import bpy.utils.previews

from mixar.config.logging_config import get_logger

_logger = get_logger(__name__)

# Visual tuning to roughly match the Figma chips. Values are linear-light
# (Blender's pixels[] is float-linear).
_PILL_SIZE = 64
_PILL_GREEN = (0.30, 0.85, 0.45)
_PILL_GREY = (0.45, 0.45, 0.50)
_PILL_YELLOW = (1.00, 0.74, 0.18)
# macOS-style "close" red — slightly darker than pure red so it sits
# alongside the yellow + green traffic lights without screaming.
_PILL_BLUE = (0.25, 0.55, 1.00)
_PILL_RED = (1.00, 0.36, 0.34)

# Palette: name → linear-light RGB triple.
_PILL_PALETTE = {
    "green": _PILL_GREEN,
    "grey": _PILL_GREY,
    "blue": _PILL_BLUE,
    "yellow": _PILL_YELLOW,
    "red": _PILL_RED,
}


# bpy.utils.previews collection — populated by register(), torn down
# by unregister(). Also cached so subsequent get_pill_icon_id_named
# calls don't have to look it up.
_pcoll = None

# Cached temp directory for our generated PNGs (one per session).
_cache_dir = None


def _make_circle_pixels(color_rgb, size: int = _PILL_SIZE):
    """Flat RGBA float list for a filled antialiased circle on
    transparent background, top-down row order (Blender's image
    pixel convention is row-major bottom-up — Image.save handles
    the orientation, so we don't need to flip ourselves here)."""
    cx = (size - 1) * 0.5
    cy = (size - 1) * 0.5
    radius = (size * 0.5) - 2.0
    pixels = []
    r, g, b = color_rgb
    for y in range(size):
        for x in range(size):
            dx = x - cx
            dy = y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= radius - 0.5:
                alpha = 1.0
            elif dist <= radius + 0.5:
                alpha = max(0.0, radius + 0.5 - dist)
            else:
                alpha = 0.0
            pixels.extend([r, g, b, alpha])
    return pixels


def _write_circle_png(filepath: str, color_rgb, size: int = _PILL_SIZE) -> bool:
    """Write a filled-circle RGBA PNG via Blender's Image.save().

    Returns True on success. Uses a temporary Image data-block that
    we remove once the PNG is on disk so the data-block list stays
    clean.
    """
    img_name = "_mixar_pill_gen_tmp"
    # Remove a stale temp image from a previous failed call, if any.
    stale = bpy.data.images.get(img_name)
    if stale is not None:
        try:
            bpy.data.images.remove(stale)
        except Exception:  # noqa: BLE001 — defensive
            pass

    img = bpy.data.images.new(img_name, size, size, alpha=True, float_buffer=False)
    try:
        img.pixels = _make_circle_pixels(color_rgb, size)
        img.update()
        img.filepath_raw = filepath
        img.file_format = 'PNG'
        img.save()
    except Exception as e:  # noqa: BLE001
        _logger.warning("agent_bubble: pill PNG save failed (%s): %s", filepath, e)
        try:
            bpy.data.images.remove(img)
        except Exception:  # noqa: BLE001
            pass
        return False

    try:
        bpy.data.images.remove(img)
    except Exception:  # noqa: BLE001
        pass
    return True


def get_pill_icon_id(running: bool) -> int:
    """Return the icon_id for the green (running) or grey (idle) pill."""
    return get_pill_icon_id_named("green" if running else "grey")


def get_pill_icon_id_named(color_name: str) -> int:
    """Return the icon_id for any palette pill colour."""
    global _pcoll
    if _pcoll is None or color_name not in _pcoll:
        return 0
    return _pcoll[color_name].icon_id


def register():
    """Generate all palette PNGs once + load them as a previews collection."""
    global _pcoll, _cache_dir

    if _pcoll is not None:
        return  # already registered

    try:
        _cache_dir = os.path.join(tempfile.gettempdir(), "mixar_agent_bubble_pills")
        os.makedirs(_cache_dir, exist_ok=True)
    except Exception as e:  # noqa: BLE001 — never break startup
        _logger.warning("agent_bubble: tempdir creation failed: %s", e)
        return

    pcoll = bpy.utils.previews.new()
    for color_name, color_rgb in _PILL_PALETTE.items():
        png_path = os.path.join(_cache_dir, color_name + ".png")
        if not _write_circle_png(png_path, color_rgb):
            continue
        try:
            pcoll.load(color_name, png_path, "IMAGE")
        except KeyError:
            # Already loaded — skip (shouldn't happen on first register but
            # defensive against re-register without unregister).
            pass
        except Exception as e:  # noqa: BLE001
            _logger.warning(
                "agent_bubble: pill preview load failed (%s): %s",
                color_name, e,
            )
    _pcoll = pcoll


def unregister():
    """Remove the previews collection on Mixar teardown."""
    global _pcoll
    if _pcoll is not None:
        try:
            bpy.utils.previews.remove(_pcoll)
        except Exception as e:  # noqa: BLE001 — defensive on shutdown
            _logger.warning("agent_bubble: previews.remove failed: %s", e)
        _pcoll = None


def refresh():
    """Rebuild preview icons after file load.

    Blender can invalidate preview/icon backing data across .mixar loads while
    the Python module globals survive. Force a clean preview collection so the
    status pill uses the same custom coloured dots as a fresh launch.
    """
    unregister()
    register()
