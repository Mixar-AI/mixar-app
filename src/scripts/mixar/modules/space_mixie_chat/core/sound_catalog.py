# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backend-driven catalog of task-completion sounds.

The list of sounds lives on the backend (``GET /api/v1/notifications/sounds``),
so new options can ship without a client release. Each entry is
``{"id", "label", "url"}`` where ``url`` is an S3 link to the clip.

Two caches keep playback instant and offline-tolerant:

- the catalog JSON (list + ETag) is persisted to disk so the picker renders
  immediately on the next launch, before any network round-trip;
- each clip is downloaded once into a per-user cache directory and played
  from disk thereafter.

Network/disk work runs on daemon threads and never touches ``bpy``; callers
marshal playback back to the main thread themselves.
"""

import hashlib
import json
import os
import tempfile
import threading
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_CATALOG_FILENAME = "notification_sounds.json"
_CLIP_SUBDIR = "sound_cache"
# Completion clips are tiny; refuse anything absurd rather than fill the disk.
_MAX_CLIP_BYTES = 10 * 1024 * 1024
_DOWNLOAD_TIMEOUT_S = 20

_lock = threading.Lock()
_sounds: List[Dict[str, str]] = []
_etag: Optional[str] = None

_resolved_data_dir: Optional[str] = None


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _data_dir() -> str:
    """Resolve the per-user cache root, once, on the main thread.

    Workers reuse the cached value so they never reach into ``bpy.utils``.
    """
    global _resolved_data_dir
    if _resolved_data_dir is None:
        path = None
        try:
            import bpy

            path = bpy.utils.user_resource("DATAFILES", path="mixar")
        except Exception:  # noqa: BLE001 — headless/early import
            path = None
        _resolved_data_dir = path or os.path.join(
            os.path.expanduser("~"), ".mixar"
        )
    return _resolved_data_dir


def _catalog_path() -> str:
    return os.path.join(_data_dir(), _CATALOG_FILENAME)


def _clip_dir() -> str:
    return os.path.join(_data_dir(), _CLIP_SUBDIR)


def _clip_ext(url: str) -> str:
    """Best-effort audio extension from the URL path (defaults to .mp3)."""
    name = urllib.parse.urlparse(url).path
    ext = os.path.splitext(name)[1].lower()
    return ext if ext in {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"} else ".mp3"


def _clip_path(sound: Dict[str, str]) -> str:
    """Deterministic on-disk path for a sound's cached clip.

    Keyed on the URL so a re-uploaded clip (new URL) lands in a new file
    instead of serving stale audio.
    """
    url = sound.get("url", "")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return os.path.join(_clip_dir(), f"{sound.get('id', digest)}_{digest}{_clip_ext(url)}")


# ---------------------------------------------------------------------------
# Disk persistence
# ---------------------------------------------------------------------------


def _sanitize(raw) -> List[Dict[str, str]]:
    """Keep only well-formed ``{id, label, url}`` entries."""
    out: List[Dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id", "")).strip()
        url = str(item.get("url", "")).strip()
        label = str(item.get("label", "") or sid).strip()
        if sid and url:
            out.append({"id": sid, "label": label, "url": url})
    return out


def _load_from_disk() -> None:
    path = _catalog_path()
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        sounds = _sanitize(stored.get("sounds") if isinstance(stored, dict) else None)
        etag = stored.get("etag") if isinstance(stored, dict) else None
    except Exception as exc:  # noqa: BLE001 — corrupt cache is not fatal
        logger.warning("Sound catalog disk cache read failed: %s", exc)
        return
    global _sounds, _etag
    with _lock:
        _sounds = sounds
        _etag = etag or None


def _save_to_disk(etag: Optional[str], sounds: List[Dict[str, str]]) -> None:
    path = _catalog_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=".notification_sounds_", suffix=".json", dir=os.path.dirname(path)
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"etag": etag, "sounds": sounds}, handle)
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001 — cache write is best effort
        logger.warning("Sound catalog disk cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# Public accessors (main thread)
# ---------------------------------------------------------------------------


def initialize() -> None:
    """Resolve paths and load the disk cache. Call once on the main thread."""
    _data_dir()
    _load_from_disk()


def get_sounds() -> List[Dict[str, str]]:
    """Return the cached catalog (possibly empty). Never raises."""
    with _lock:
        return list(_sounds)


def find_sound(sound_id: str) -> Optional[Dict[str, str]]:
    """Return the catalog entry for *sound_id*, or None."""
    with _lock:
        for sound in _sounds:
            if sound["id"] == sound_id:
                return dict(sound)
    return None


def cached_clip_path(sound_id: str) -> Optional[str]:
    """Local path of an already-downloaded clip, or None if not cached."""
    sound = find_sound(sound_id)
    if not sound:
        return None
    path = _clip_path(sound)
    return path if os.path.isfile(path) else None


# ---------------------------------------------------------------------------
# Download (background thread; no bpy)
# ---------------------------------------------------------------------------


def download_clip(sound: Dict[str, str]) -> Optional[str]:
    """Download a clip to the cache and return its path (None on failure).

    Safe to call from a daemon thread. Idempotent: an already-cached clip is
    returned without re-downloading.
    """
    url = sound.get("url")
    if not url:
        return None
    dest = _clip_path(sound)
    if os.path.isfile(dest):
        return dest
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT_S) as response:
            data = response.read(_MAX_CLIP_BYTES + 1)
        if not data or len(data) > _MAX_CLIP_BYTES:
            logger.warning("Sound clip rejected (empty or too large): %s", sound.get("id"))
            return None
        fd, tmp = tempfile.mkstemp(
            prefix=".clip_", suffix=os.path.splitext(dest)[1], dir=os.path.dirname(dest)
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, dest)
        return dest
    except Exception as exc:  # noqa: BLE001 — sound is never critical
        logger.debug("Sound clip download failed for %s: %s", sound.get("id"), exc)
        return None


def _prefetch_all(sounds: List[Dict[str, str]]) -> None:
    for sound in sounds:
        download_clip(sound)


# ---------------------------------------------------------------------------
# Refresh (background thread)
# ---------------------------------------------------------------------------


def _refresh() -> None:
    """Fetch the catalog, persist it, and prefetch clips. No bpy access."""
    global _sounds, _etag
    try:
        from mixar.modules.auth.core.auth import get_access_token

        if not get_access_token():
            return

        from mixar.modules.common.api.services import get_notifications_service

        with _lock:
            etag = _etag
        response = get_notifications_service().get_sounds(etag=etag)
    except Exception as exc:  # noqa: BLE001 — offline / pre-auth is fine
        logger.debug("Sound catalog fetch skipped: %s", exc)
        return

    if getattr(response, "status_code", None) == 304:
        _prefetch_all(get_sounds())
        return
    if not getattr(response, "success", False):
        return

    # House response envelope is ``{"status", "message", "data": {"sounds": [...]}}``.
    body = getattr(response, "data", None)
    payload = body.get("data") if isinstance(body, dict) else None
    raw = payload.get("sounds") if isinstance(payload, dict) else None
    sounds = _sanitize(raw)
    new_etag = None
    headers = getattr(response, "headers", None)
    if isinstance(headers, dict):
        new_etag = headers.get("ETag") or headers.get("etag")

    with _lock:
        _sounds = sounds
        _etag = new_etag or _etag
        snapshot = list(_sounds)
        etag_to_save = _etag
    _save_to_disk(etag_to_save, snapshot)
    _prefetch_all(snapshot)


def refresh_async() -> None:
    """Refresh the catalog on a daemon thread. Best effort; never raises."""
    threading.Thread(
        target=_refresh, name="mixar-sound-catalog", daemon=True
    ).start()


def clear() -> None:
    """Drop the in-memory catalog (e.g. on logout)."""
    global _sounds, _etag
    with _lock:
        _sounds = []
        _etag = None
