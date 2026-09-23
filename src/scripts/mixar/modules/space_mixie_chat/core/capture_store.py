# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Persist the images an agent tool call produced, for the chat's image tiles.

The captures (viewport renders, seam / UV inspections, final renders) are made
by THIS client: every one comes back through a `blender.execute_script` reply
as base64 in the result dict. The backend keeps its own copy for the model;
the chat needs a file on disk it can draw. This module extracts them from the
result dict and writes them under the session's durable media dir,

    ~/.mixar/chat_media/<session>/captures/<request>_<n>.<jpg|png>

which the chat-history archive already treats as durable (it never re-copies
files under the media root) and deletes with the session.

No bpy imports — pure, unit-testable. Bounded on purpose: a session keeps at
most CAPTURE_KEEP_PER_SESSION files; the oldest are unlinked as new ones land.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re

CAPTURE_DIR_NAME = "captures"
CAPTURE_KEEP_PER_SESSION = 64
# One tool call never legitimately produces more than a handful of views.
CAPTURE_MAX_PER_RESULT = 8
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")

_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _media_dir(session_id: str) -> str:
    """Same path rule as chat_history.media_dir (not imported: that module
    pulls in the package logger; this one must stay importable in tests)."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "no-session")[:80]
    return os.path.join(os.path.expanduser("~"), ".mixar", "chat_media", safe)


def captures_dir(session_id: str) -> str:
    return os.path.join(_media_dir(session_id), CAPTURE_DIR_NAME)


def _ext_for(mime: str, default: str = ".jpg") -> str:
    return _MIME_EXT.get((mime or "").lower().strip(), default)


def _decode(b64: str) -> bytes | None:
    if not b64 or not isinstance(b64, str):
        return None
    try:
        return base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError):
        return None


def _split_data_url(url: str) -> tuple[str, str] | None:
    """`data:image/png;base64,....` -> (mime, payload); None for anything else."""
    if not isinstance(url, str) or not url.startswith("data:"):
        return None
    head, sep, payload = url.partition(",")
    if not sep or ";base64" not in head:
        return None
    mime = head[5:].split(";", 1)[0]
    return mime, payload


RESULT_PREFIX = "__RESULT__"
_IMAGE_KEYS = ("image_base64", "images", "image_url")


def printed_result(output: str) -> dict:
    """The dict a script printed as ``__RESULT__<json>``, else {}.

    The backend's capture scripts (render_viewport, inspect_mesh_seams, the
    final render) PRINT their result; only the ``__RESULT__`` VARIABLE form is
    flattened into the reply by ``ExecutionResult.to_dict``. Without this the
    client never saw its own captures (uat1 session 5cb3f137: zero local
    tiles, only downloads).
    """
    for line in (output or "").splitlines():
        if line.startswith(RESULT_PREFIX):
            try:
                parsed = json.loads(line[len(RESULT_PREFIX):])
            except ValueError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
    return {}


def extract_images(result: dict) -> list[dict]:
    """Pull every image out of a tool result dict.

    Recognised shapes (see the backend's viewport scripts):
      - render_viewport:        {image_base64, image_mime, width, height}
      - inspect_mesh_seams:     {images: [{view, image_base64, image_mime?, width?, height?}]}
      - render_viewport_final:  {image_url: "data:image/png;base64,..."}
    at the top level, or inside the printed ``__RESULT__`` line of ``output``.

    Returns a list of {"data": bytes, "mime": str, "width": int, "height": int,
    "caption": str}. Never raises; malformed entries are skipped.
    """
    out: list[dict] = []
    if not isinstance(result, dict):
        return out
    if not any(result.get(k) for k in _IMAGE_KEYS):
        printed = printed_result(result.get("output") or "")
        if any(printed.get(k) for k in _IMAGE_KEYS):
            result = {**result, **printed}

    def push(data, mime, width, height, caption):
        if not data or len(out) >= CAPTURE_MAX_PER_RESULT:
            return
        out.append({
            "data": data,
            "mime": mime or "image/jpeg",
            "width": int(width or 0),
            "height": int(height or 0),
            "caption": (caption or "")[:120],
        })

    push(_decode(result.get("image_base64")), result.get("image_mime"),
         result.get("width"), result.get("height"), result.get("caption") or "")

    for entry in result.get("images") or []:
        if not isinstance(entry, dict):
            continue
        push(_decode(entry.get("image_base64")), entry.get("image_mime"),
             entry.get("width") or result.get("width"),
             entry.get("height") or result.get("height"),
             entry.get("view") or entry.get("caption") or "")

    parsed = _split_data_url(result.get("image_url") or "")
    if parsed:
        push(_decode(parsed[1]), parsed[0], result.get("width"),
             result.get("height"), "final render")
    return out


def _safe_name(value: str) -> str:
    return _SAFE.sub("_", value or "")[:48] or "capture"


def save_captures(session_id: str, request_id: str, result: dict) -> list[dict]:
    """Write the result's images to disk and return tile records.

    Each record is {"local_path", "width", "height", "caption"} — the fields
    MixieChatImageItem carries. Returns [] when the result holds no image or
    nothing could be written (disk full, unwritable home). Never raises.
    """
    images = extract_images(result)
    if not images:
        return []
    target = captures_dir(session_id)
    try:
        os.makedirs(target, exist_ok=True)
    except OSError:
        return []

    records = []
    stem = _safe_name(request_id)
    for n, img in enumerate(images):
        path = os.path.join(target, f"{stem}_{n}{_ext_for(img['mime'])}")
        try:
            with open(path, "wb") as f:
                f.write(img["data"])
        except OSError:
            continue
        records.append({
            "local_path": path,
            "width": img["width"],
            "height": img["height"],
            "caption": img["caption"],
        })
    if records:
        prune_captures(session_id)
    return records


def prune_captures(session_id: str, keep: int = CAPTURE_KEEP_PER_SESSION) -> int:
    """Unlink the oldest captures past `keep` for one session. Returns count removed."""
    target = captures_dir(session_id)
    try:
        with os.scandir(target) as it:
            files = [e for e in it if e.is_file()]
    except OSError:
        return 0
    if len(files) <= keep:
        return 0
    try:
        files.sort(key=lambda e: e.stat().st_mtime)
    except OSError:
        files.sort(key=lambda e: e.name)
    removed = 0
    for entry in files[: len(files) - keep]:
        try:
            os.unlink(entry.path)
            removed += 1
        except OSError:
            pass
    return removed


# ── Backend-held images ─────────────────────────────────────────────────────

IMAGE_ENDPOINT = "api/v1/agent/images"
_MAGIC = ((b"\xff\xd8\xff", ".jpg"), (b"\x89PNG", ".png"), (b"RIFF", ".webp"))


def _ext_from_bytes(data: bytes) -> str:
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    return ".jpg"


def backend_image_path(session_id: str, image_id: str) -> str | None:
    """The cached file for a backend image id, or None when not fetched yet."""
    target = captures_dir(session_id)
    for _magic, ext in _MAGIC:
        path = os.path.join(target, f"{image_id}{ext}")
        if os.path.isfile(path):
            return path
    return None


def _http_fetch(session_id: str, image_id: str) -> bytes | None:
    """GET the bytes through the shared authenticated HTTP client."""
    from mixar.modules.common.api.client import get_http_client
    response = get_http_client().get(f"{IMAGE_ENDPOINT}/{session_id}/{image_id}", timeout=20)
    raw = getattr(response, "data", None)
    if not isinstance(raw, (bytes, bytearray)):
        raw = getattr(getattr(response, "raw", None), "content", None)
    return bytes(raw) if isinstance(raw, (bytes, bytearray)) and raw else None


def fetch_backend_image(session_id: str, image_id: str, fetch=None) -> str | None:
    """Ensure the backend image `image_id` is on disk; return its path.

    Content-addressed: an id already cached is never fetched again. `fetch`
    (session_id, image_id) -> bytes|None is injectable for tests; the default
    goes through the app's authenticated HTTP client. Never raises.
    """
    if not session_id or not re.fullmatch(r"[0-9a-f]{8,64}", image_id or ""):
        return None
    cached = backend_image_path(session_id, image_id)
    if cached:
        return cached
    try:
        data = (fetch or _http_fetch)(session_id, image_id)
    except Exception:
        return None
    if not data:
        return None
    target = captures_dir(session_id)
    try:
        os.makedirs(target, exist_ok=True)
        path = os.path.join(target, f"{image_id}{_ext_from_bytes(data)}")
        with open(path, "wb") as f:
            f.write(data)
    except OSError:
        return None
    prune_captures(session_id)
    return path
