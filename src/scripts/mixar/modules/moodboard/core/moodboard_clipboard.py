# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The moodboard clipboard: one copy, pasteable here or in another Mixar.

Copy (Ctrl/Cmd+C) takes ONE snapshot of the selection -- images, movies, text
boxes, inference nodes and the links between them (``clipboard_snapshot``) --
and does two things with it:

1. keeps it in this process (``_SESSION``), so a paste back into this file
   shares the image datablocks like Duplicate does, and
2. writes it to the shared on-disk copy buffer (``moodboard_copybuffer``: a
   partial ``.blend`` with the images plus a JSON manifest), which is how a
   SECOND running Mixar can paste the very same thing -- the mechanism
   Blender's own viewport copy/paste uses.

Paste (Ctrl/Cmd+V) decides which of the two to read (``clipboard_source``):
the manifest on disk names the process that wrote it, so a copy made by THIS
process pastes from the session and one made by another Mixar is appended from
the buffer -- whichever copy is newest wins, across every open instance. The
best-effort export of the first copied still to the OS clipboard is unchanged
(so a picture still pastes into other applications); movies stay lossless in
the buffer, since an OS image clipboard would reduce a clip to one frame.
"""

from __future__ import annotations

import time

from mixar.config.logging_config import get_logger
from . import clipboard_snapshot, moodboard_copybuffer, node_duplicate
from .media_utils import is_video_item, selected_exportable_media

logger = get_logger(__name__)

# This process's last copy. ``payload`` is the snapshot, ``buffer_id`` the
# manifest it was written to (None when the write failed), ``copied_at`` a
# wall-clock stamp comparable with the manifest's ``written_at``.
_SESSION: dict = {"payload": None, "buffer_id": None, "copied_at": 0.0, "system_image_size": None}


def _first_copied_still(scene):
    for item in selected_exportable_media(scene):
        if not is_video_item(item):
            return item.image
    return None


def _export_still_to_system_clipboard(image, scene):
    """Best-effort OS clipboard export. Returns the exported (w, h) or None."""
    if image is None:
        return None
    try:
        from .system_clipboard import copy_blender_image_to_system_clipboard

        copy_blender_image_to_system_clipboard(image, scene)
        return (int(image.size[0]), int(image.size[1]))
    except Exception as exc:
        logger.debug("System clipboard copy skipped: %s", exc)
        return None


def copy_selected(scene, *, export_to_system: bool = True) -> int:
    """Snapshot the selection into the session AND the on-disk buffer.

    Returns the number of items captured. A zero result leaves any previous
    clipboard contents untouched.
    """
    payload = clipboard_snapshot.build_snapshot(scene)
    count = clipboard_snapshot.item_count(payload)
    if count == 0:
        return 0

    system_size = None
    if export_to_system:
        system_size = _export_still_to_system_clipboard(_first_copied_still(scene), scene)

    _SESSION["payload"] = payload
    _SESSION["copied_at"] = time.time()
    _SESSION["system_image_size"] = system_size
    try:
        _SESSION["buffer_id"] = moodboard_copybuffer.write_buffer(
            payload,
            clipboard_snapshot.referenced_image_names(payload),
            system_image_size=system_size,
        )
    except Exception:
        # The in-process clipboard still works; only cross-instance paste is lost.
        logger.warning("Moodboard copy buffer write failed", exc_info=True)
        _SESSION["buffer_id"] = None
    return count


def _session_valid() -> bool:
    payload = _SESSION.get("payload")
    if not payload:
        return False
    # Text boxes and nodes need no datablock; media does. A snapshot whose
    # every image has since been deleted has nothing left to paste.
    names = clipboard_snapshot.referenced_image_names(payload)
    if not names:
        return True
    if payload.get("textboxes") or payload.get("nodes"):
        return True
    return any(node_duplicate.default_image_resolver(name) is not None for name in names)


def clipboard_source():
    """Where the next paste reads from: ``"session"``, ``"buffer"`` or None.

    The session wins when it produced the current manifest (or when the buffer
    write failed and nobody wrote a newer one since); a manifest another
    process wrote more recently wins over it.
    """
    manifest = moodboard_copybuffer.read_manifest()
    session_ok = _session_valid()
    if manifest is None:
        return "session" if session_ok else None
    if session_ok:
        if moodboard_copybuffer.is_own(manifest):
            return "session"
        if float(manifest.get("written_at") or 0.0) <= float(_SESSION.get("copied_at") or 0.0):
            return "session"
    return "buffer"


def has_clipboard() -> bool:
    """True if a paste would produce something."""
    return clipboard_source() is not None


def clipboard_exported_size():
    """(w, h) of the still the current clipboard source put on the OS
    clipboard, or None when it exported none (video/text/node-only copies, or
    an export that failed). The paste operator compares this against what the
    OS clipboard holds NOW: a different picture there means the user copied
    something newer in another application, and that wins."""
    source = clipboard_source()
    if source == "session":
        size = _SESSION.get("system_image_size")
    elif source == "buffer":
        manifest = moodboard_copybuffer.read_manifest() or {}
        size = manifest.get("system_image_size")
    else:
        size = None
    if not size:
        return None
    try:
        return (int(size[0]), int(size[1]))
    except (IndexError, TypeError, ValueError):
        return None


def paste_clipboard(scene, anchor: tuple[float, float] | None = None) -> int:
    """Recreate the clipboard contents on *scene*. Returns the count pasted.

    Relative layout is preserved: the group is centred on *anchor* (canvas
    coords, e.g. the cursor) or dropped in the nearest free slot near the
    viewport centre. Existing items are deselected and the pasted ones
    selected.
    """
    source = clipboard_source()
    if source == "session":
        return clipboard_snapshot.materialize_snapshot(
            scene, _SESSION["payload"], node_duplicate.default_image_resolver, anchor=anchor,
        )
    if source == "buffer":
        manifest = moodboard_copybuffer.read_manifest()
        if manifest is None:
            return 0
        appended = _buffer_images(manifest)
        return clipboard_snapshot.materialize_snapshot(
            scene, manifest["payload"], appended.get, anchor=anchor,
        )
    return 0


# Datablocks appended from a foreign buffer, keyed by its id: pasting the same
# copy twice shares them (as a second in-process paste would) instead of
# appending ``chair.png.001``, ``.002`` ... on every Ctrl+V.
_IMPORTED: dict = {"buffer_id": None, "images": {}}


def _still_alive(image) -> bool:
    try:
        return node_duplicate.default_image_resolver(image.name) is image
    except (AttributeError, ReferenceError):
        return False


def _buffer_images(manifest: dict) -> dict:
    buffer_id = manifest.get("buffer_id")
    cached = _IMPORTED["images"]
    if _IMPORTED["buffer_id"] == buffer_id and cached and all(_still_alive(img) for img in cached.values()):
        return cached
    images = moodboard_copybuffer.import_buffer_images(manifest)
    _IMPORTED["buffer_id"] = buffer_id
    _IMPORTED["images"] = images
    return images
