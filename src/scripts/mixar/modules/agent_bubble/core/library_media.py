# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Images and videos inside the user's connected library folders.

Blender's asset list only enumerates datablocks marked as assets inside
``.blend`` files, so a folder of plain ``.png``/``.mp4`` files listed as an
EMPTY library in the island's Library tab. This module is the missing half:
it walks every connected folder (except the auto-archived "Mixar
Generations" library, which the AI source already shows), and mirrors the
media it finds into ``WindowManager.mixar_generations_files`` for the C++
pane to paint next to the library's assets.

Thumbnails go through ``bpy.utils.previews``: ``load()`` only registers a
DEFERRED preview, and the pane's ``icon_ensure_deferred`` starts the
threaded thumbnail read for the tiles actually on screen — nothing here
decodes an image.

Cost model: the walk is bounded (:data:`MAX_FILES`, :data:`MAX_DIRS`) and
change detection is a stat of each walked directory, so an unchanged folder
never rewrites the collection. :func:`refresh` is called from the Library
pump while the tab is showing, after connecting/removing a library, and when
the browsed library changes.
"""

from __future__ import annotations

import logging
import os
import time

import bpy

logger = logging.getLogger(__name__)

#: Must match ``asset_search/constants.py:GENERATION_LIBRARY_NAME`` and the
#: C++ ``GENERATIONS_LIBRARY_NAME``.
GENERATIONS_LIBRARY_NAME = "Mixar Generations"

#: Per-library bounds, so a library pointed at a home folder cannot stall
#: the UI. Anything past them is simply not listed.
MAX_FILES = 3000
MAX_DIRS = 400
MAX_DEPTH = 6

#: Minimum seconds between two change checks driven by the pump.
REFRESH_INTERVAL = 2.0

_FALLBACK_IMAGE = (
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".tga",
    ".exr", ".hdr",
)
_FALLBACK_MOVIE = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".gif")

_previews = None
#: library path -> (signature, entries); entries = [(abs_path, kind, mtime)].
_scan_cache: dict[str, tuple[tuple, list]] = {}
_last_refresh = 0.0


def _extensions():
    """``(image_exts, movie_exts)`` from Blender's compiled media support.

    A still extension that is also a movie one (``.gif``) counts as an image.
    """
    def _read(name, fallback):
        try:
            found = {str(e).lower() for e in getattr(bpy.path, name, ())}
        except TypeError:
            found = set()
        return {e for e in found if e.startswith(".")} or set(fallback)

    image = _read("extensions_image", _FALLBACK_IMAGE)
    movie = _read("extensions_movie", _FALLBACK_MOVIE)
    return image, movie - image


def classify(filename: str, image_exts=None, movie_exts=None) -> str:
    """``'IMAGE'``, ``'VIDEO'`` or ``''`` for a file name."""
    if image_exts is None or movie_exts is None:
        image_exts, movie_exts = _extensions()
    ext = os.path.splitext(filename)[1].lower()
    if ext in image_exts:
        return 'IMAGE'
    if ext in movie_exts:
        return 'VIDEO'
    return ''


def _walk(root: str):
    """``(dirpath, filenames, mtime)`` for every folder the scan covers.

    Hidden folders are skipped, and the walk stops at :data:`MAX_DEPTH` and
    :data:`MAX_DIRS` so the signature and the listing agree on scope.
    """
    root = os.path.abspath(root)
    base_depth = root.rstrip(os.sep).count(os.sep)
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        try:
            mtime = os.stat(dirpath).st_mtime
        except OSError:
            dirnames[:] = []
            continue
        seen += 1
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if dirpath.count(os.sep) - base_depth >= MAX_DEPTH or seen >= MAX_DIRS:
            dirnames[:] = []
        yield dirpath, filenames, mtime


def folder_signature(root: str) -> tuple:
    """Every covered folder with its mtime.

    Adding, removing or renaming a file changes its folder's mtime, so an
    equal signature means the listing is unchanged — a stat per folder
    instead of per file.
    """
    return tuple((dirpath, mtime) for dirpath, _files, mtime in _walk(root))


def scan_folder(root: str, image_exts=None, movie_exts=None):
    """Walk *root* and return ``(signature, entries)``.

    ``entries`` is ``[(abs_path, kind, mtime)]`` for every image and video,
    capped at :data:`MAX_FILES`. Hidden files are skipped.
    """
    if image_exts is None or movie_exts is None:
        image_exts, movie_exts = _extensions()
    signature = []
    entries = []
    for dirpath, filenames, dir_mtime in _walk(root):
        signature.append((dirpath, dir_mtime))
        if len(entries) >= MAX_FILES:
            continue
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            kind = classify(name, image_exts, movie_exts)
            if not kind:
                continue
            path = os.path.join(dirpath, name)
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            entries.append((path, kind, mtime))
            if len(entries) >= MAX_FILES:
                break
    return tuple(signature), entries


def _user_libraries(context):
    try:
        libs = context.preferences.filepaths.asset_libraries
    except Exception:  # noqa: BLE001 — no preferences in a background run
        return []
    out = []
    for lib in libs:
        if not lib.name or lib.name == GENERATIONS_LIBRARY_NAME:
            continue
        try:
            path = os.path.abspath(bpy.path.abspath(lib.path or ""))
        except Exception:  # noqa: BLE001 — a broken entry must not stop the rest
            continue
        if path and os.path.isdir(path):
            out.append((lib.name, path))
    return out


def _preview_collection():
    global _previews
    if _previews is None:
        import bpy.utils.previews

        _previews = bpy.utils.previews.new()
    return _previews


def _icon_id(path: str, kind: str) -> int:
    pcoll = _preview_collection()
    try:
        preview = pcoll.get(path)
        if preview is None:
            preview = pcoll.load(path, path, 'MOVIE' if kind == 'VIDEO' else 'IMAGE')
        return int(preview.icon_id)
    except Exception:  # noqa: BLE001 — the tile falls back to its glyph
        return 0


def refresh(context=None, *, force: bool = False) -> bool:
    """Re-list media in the connected folders; True when the list changed.

    Throttled to :data:`REFRESH_INTERVAL` unless *force* is set.
    """
    global _last_refresh
    context = context or bpy.context
    wm = getattr(context, "window_manager", None)
    files = getattr(wm, "mixar_generations_files", None) if wm else None
    if files is None:
        return False
    now = time.monotonic()
    if not force and now - _last_refresh < REFRESH_INTERVAL:
        return False
    _last_refresh = now

    image_exts, movie_exts = _extensions()
    wanted = []
    listed = set()  # A folder nested in another library is listed once.
    live_paths = set()
    for name, path in _user_libraries(context):
        live_paths.add(path)
        cached = _scan_cache.get(path)
        try:
            if cached is None or folder_signature(path) != cached[0]:
                cached = scan_folder(path, image_exts, movie_exts)
                _scan_cache[path] = cached
        except OSError:
            continue
        for file_path, kind, mtime in cached[1]:
            if file_path not in listed:
                listed.add(file_path)
                wanted.append((name, file_path, kind, int(mtime)))
    for stale in set(_scan_cache) - live_paths:
        del _scan_cache[stale]

    current = [(f.library, f.path, f.kind, f.mtime) for f in files]
    if current == wanted:
        return False
    files.clear()
    for lib_name, file_path, kind, mtime in wanted:
        item = files.add()
        item.library = lib_name
        item.path = file_path
        item.name = os.path.basename(file_path)
        item.kind = kind
        item.mtime = mtime
        item.icon_id = _icon_id(file_path, kind)
    _prune_previews({row[1] for row in wanted})
    return True


def _prune_previews(keep: set) -> None:
    if _previews is None:
        return
    for key in [k for k in _previews.keys() if k not in keep]:
        try:
            del _previews[key]
        except Exception:  # noqa: BLE001
            pass


def free() -> None:
    """Release every thumbnail (unregister)."""
    global _previews
    _scan_cache.clear()
    if _previews is not None:
        try:
            import bpy.utils.previews

            bpy.utils.previews.remove(_previews)
        except Exception:  # noqa: BLE001
            pass
        _previews = None
