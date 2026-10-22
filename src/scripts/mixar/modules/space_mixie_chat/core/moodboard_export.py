# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Moodboard stills written to a NAMED folder for the agent's / MCP's
``export_moodboard_images`` tool (there was no way to get a board image out
programmatically).

Names are the moodboard's ``image_name`` values (``list_moodboard_images``).
Each still is encoded from a temporary image holding its pixels, in the
requested format; the board's own image is never changed. Destinations are the ``export_package``
named folders, and results report file names and the folder kind only —
never an absolute local path.
"""

import os

import bpy

from .export_package import DESTINATIONS, _safe, destination

FORMATS = {"png": ("PNG", ".png"), "jpg": ("JPEG", ".jpg"), "webp": ("WEBP", ".webp")}
MAX_IMAGES = 50


def _board(scene) -> dict:
    """image_name -> moodboard item on this tab's board."""
    items = getattr(scene, "mixie_moodboard_images", None) or ()
    return {item.image.name: item for item in items if getattr(item, "image", None) is not None}


def _unique(folder: str, stem: str, ext: str, used: set) -> str:
    name, n = stem + ext, 1
    while name.lower() in used or os.path.exists(os.path.join(folder, name)):
        n += 1
        name = f"{stem}_{n}{ext}"
    used.add(name.lower())
    return name


def _write(image, path: str, file_format: str) -> None:
    """Encode ``image``'s pixels as ``file_format`` at ``path``. Not ``image.copy()``:
    a copy of a PACKED board image saves its packed bytes whatever the format, so a
    ".jpg" came out as PNG data. A fresh image holding the same pixels encodes."""
    import numpy as np

    width, height = image.size
    out = bpy.data.images.new("mixar_moodboard_export", width, height, alpha=True,
                              float_buffer=image.is_float)
    try:
        out.colorspace_settings.name = image.colorspace_settings.name
        pixels = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        out.pixels.foreach_set(pixels)
        out.filepath_raw = path
        out.file_format = file_format
        out.save()
    finally:
        bpy.data.images.remove(out)


def export_moodboard_images(names, fmt="png", where="downloads", folder=None, scene=None) -> dict:
    """Write the named board stills; ``{"success", "folder", "files": [...]}``."""
    from mixar.modules.moodboard.core.media_utils import is_still_item

    fmt = str(fmt or "png").lower()
    if fmt not in FORMATS:
        return {"success": False, "error": f"format must be one of {sorted(FORMATS)}"}
    where = str(where or "downloads").lower()
    if where not in DESTINATIONS:
        return {"success": False, "error": f"destination must be one of {list(DESTINATIONS)}"}
    names = [str(n) for n in (names or []) if str(n).strip()]
    if not names or len(names) > MAX_IMAGES:
        return {"success": False, "error": f"name 1 to {MAX_IMAGES} moodboard images"}
    board = _board(scene or bpy.context.scene)
    missing = [n for n in names if n not in board]
    if missing:
        return {"success": False, "error": "Not on this tab's moodboard: " + ", ".join(missing[:10])
                + ". List them with list_moodboard_images."}
    videos = [n for n in names if not is_still_item(board[n])]
    if videos:
        return {"success": False, "error": "Only still images can be exported here; videos: " + ", ".join(videos[:10])}
    empty = [n for n in names if board[n].image.size[0] == 0]
    if empty:
        return {"success": False, "error": "These images have no pixels to write: " + ", ".join(empty[:10])}

    file_format, ext = FORMATS[fmt]
    root = destination(where, folder)
    used, files = set(), []
    for name in names:
        image = board[name].image
        filename = _unique(root, _safe(os.path.splitext(name)[0], "moodboard_image"), ext, used)
        _write(image, os.path.join(root, filename), file_format)
        width, height = image.size
        files.append({"image_name": name, "file": filename, "width": int(width), "height": int(height),
                      "size_bytes": os.path.getsize(os.path.join(root, filename))})
    return {"success": True, "folder": where + (f"/{_safe(folder)}" if folder else ""), "format": fmt,
            "files": files}
