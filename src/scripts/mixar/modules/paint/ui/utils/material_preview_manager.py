# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material preview/thumbnail management for inline material library.

Downloads thumbnails from thumbnail_url in background threads so Blender's
UI thread is never blocked. Once a download completes, a one-shot timer loads
the image into the preview collection and triggers a redraw.
"""

import os
import threading

import bpy
import bpy.utils.previews

# Global preview collection for material thumbnails
_preview_collection = None

# material_ids whose downloads are in-flight — prevents duplicate threads
_pending: set = set()
_pending_lock = threading.Lock()


def get_preview_collection():
    """Get or create the preview collection for material thumbnails."""
    global _preview_collection
    if _preview_collection is None:
        _preview_collection = bpy.utils.previews.new()
    return _preview_collection


def _get_cache_dir() -> str:
    """Return the local thumbnail cache directory."""
    try:
        cache_dir = bpy.utils.user_resource('DATAFILES', path='mixar/thumbnail_cache')
    except Exception:
        cache_dir = os.path.join(os.path.expanduser("~"), ".mixar", "thumbnail_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _download_worker(material_id: str, thumbnail_url: str, local_path: str) -> None:
    """Background thread: download thumbnail then schedule main-thread load."""
    try:
        import requests
        r = requests.get(thumbnail_url, timeout=15)
        if r.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(r.content)
            # Hand off to main thread via timer (pcoll is not thread-safe)
            bpy.app.timers.register(
                lambda: _on_download_complete(material_id, local_path),
                first_interval=0.0,
            )
    except Exception:
        pass
    finally:
        with _pending_lock:
            _pending.discard(material_id)


def _on_download_complete(material_id: str, local_path: str):
    """Called on main thread after a thumbnail download completes."""
    if not os.path.exists(local_path):
        return None

    pcoll = get_preview_collection()
    if material_id not in pcoll:
        try:
            pcoll.load(material_id, local_path, 'IMAGE')
        except Exception:
            return None

    # Trigger redraw so the newly loaded preview appears
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass

    return None  # one-shot timer


def load_material_preview(material) -> int:
    """Return icon_id for a material thumbnail, kicking off a download if needed.

    Non-blocking: returns 0 while the download is in progress, then returns
    the real icon_id after the background thread finishes and a redraw fires.

    Args:
        material: ProceduralMaterial instance (needs .material_id, .thumbnail_path,
                  .thumbnail_url attributes).

    Returns:
        int: Icon ID for the loaded preview, or 0 if not yet available.
    """
    pcoll = get_preview_collection()

    # Already in collection — fast path
    if material.material_id in pcoll:
        return pcoll[material.material_id].icon_id

    # Try local file (thumbnail_path set by user or previous download)
    if material.thumbnail_path and os.path.exists(material.thumbnail_path):
        try:
            pcoll.load(material.material_id, material.thumbnail_path, 'IMAGE')
            return pcoll[material.material_id].icon_id
        except Exception:
            return 0

    # Try disk cache (downloaded in a previous session)
    cache_dir = _get_cache_dir()
    local_path = os.path.join(cache_dir, f"{material.material_id}.png")
    if os.path.exists(local_path):
        try:
            pcoll.load(material.material_id, local_path, 'IMAGE')
            material.thumbnail_path = local_path
            return pcoll[material.material_id].icon_id
        except Exception:
            return 0

    # No local copy — start background download if URL is available
    if material.thumbnail_url:
        with _pending_lock:
            already_downloading = material.material_id in _pending
            if not already_downloading:
                _pending.add(material.material_id)

        if not already_downloading:
            t = threading.Thread(
                target=_download_worker,
                args=(material.material_id, material.thumbnail_url, local_path),
                daemon=True,
            )
            t.start()

    return 0  # placeholder until download completes


def clear_previews():
    """Clear all loaded previews and free resources."""
    global _preview_collection
    if _preview_collection is not None:
        bpy.utils.previews.remove(_preview_collection)
        _preview_collection = None


def register():
    """Register preview collection (created on demand)."""
    pass


def unregister():
    """Unregister and clear preview collection."""
    clear_previews()
    with _pending_lock:
        _pending.clear()
