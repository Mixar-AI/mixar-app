# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""On-disk copy buffer: what lets a moodboard copy paste into ANOTHER Mixar.

Blender's own cross-process copy/paste (objects in the 3D viewport) works by
writing a partial ``copybuffer.blend`` into the shared temp directory and
appending from it on paste. The moodboard does the same with two files beside
each other in that directory:

* ``mixar_moodboard_copybuffer.blend`` -- a partial ``.blend`` written with
  ``bpy.data.libraries.write`` holding every Image datablock the copied items
  reference. Packed stills travel with their bytes; movies (which Blender
  cannot pack) travel as an ABSOLUTE file path, which is exactly right for two
  instances on one machine.
* ``mixar_moodboard_copybuffer.json`` -- the manifest: the clipboard SNAPSHOT
  (``clipboard_snapshot``: positions, text boxes, node configuration, links),
  the image names the ``.blend`` carries, and a per-process token so the
  process that wrote the buffer recognises its own copy and pastes it
  in-process (sharing datablocks) instead of re-importing it.

The manifest is written LAST and atomically, so a reader never sees a snapshot
whose ``.blend`` is still being written. A buffer left behind by an earlier
session stays valid, like Blender's -- staleness against the OS clipboard is
arbitrated by the paste operator, not here.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

MANIFEST_VERSION = 1
BUFFER_BASENAME = "mixar_moodboard_copybuffer"
BLEND_NAME = BUFFER_BASENAME + ".blend"
MANIFEST_NAME = BUFFER_BASENAME + ".json"

# Minted once per process: a manifest carrying it was written by THIS Mixar.
PROCESS_TOKEN = uuid.uuid4().hex


def buffer_directory() -> str:
    """The temp directory every Mixar on this machine shares.

    ``bpy.app.tempdir`` is the per-SESSION directory (``<base>/blender_xxxx``),
    so its parent is Blender's ``BKE_tempdir_base()`` -- the user's preference
    temp dir when set, else the system one -- which is where Blender's own
    ``copybuffer.blend`` lives and therefore where two instances meet.
    """
    session = str(getattr(bpy.app, "tempdir", "") or "")
    if session:
        base = os.path.dirname(os.path.normpath(session))
        if base and os.path.isdir(base):
            return base
    return tempfile.gettempdir()


def blend_path() -> str:
    return os.path.join(buffer_directory(), BLEND_NAME)


def manifest_path() -> str:
    return os.path.join(buffer_directory(), MANIFEST_NAME)


def _is_movie(image) -> bool:
    return str(getattr(image, "source", "") or "") == 'MOVIE'


def prepare_images_for_write(images) -> None:
    """Make sure every still's pixels are IN the datablock before it is written.

    A generated or edited image whose pixels only exist in memory would be
    written as an empty reference; packing embeds them. Movies are never
    packed (Blender cannot) -- their file path travels instead. Best-effort:
    a pack failure leaves that image as it was.
    """
    for image in images:
        if image is None or _is_movie(image):
            continue
        try:
            packed = getattr(image, "packed_file", None) is not None
            dirty = bool(getattr(image, "is_dirty", False))
            filepath = str(getattr(image, "filepath", "") or "")
            has_file = bool(filepath) and os.path.isfile(bpy.path.abspath(filepath))
            if dirty or not (packed or has_file):
                image.pack()
        except Exception:
            logger.debug("Could not pack %r for the copy buffer", getattr(image, "name", "?"), exc_info=True)


def _write_manifest(manifest: dict) -> None:
    path = manifest_path()
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    os.replace(tmp, path)


def write_buffer(payload: dict, image_names, *, system_image_size=None) -> str | None:
    """Write the ``.blend`` + manifest. Returns the new buffer id, or None.

    ``system_image_size`` is the (width, height) of the still that was also
    put on the OS clipboard, when one was -- the paste side uses it to tell
    "still our copy" from "the user copied something else since".
    """
    images = []
    for name in image_names or ():
        image = bpy.data.images.get(name)
        if image is not None:
            images.append(image)

    blend_name = ""
    if images:
        prepare_images_for_write(images)
        path = blend_path()
        try:
            # ABSOLUTE: a movie referenced as ``//clips/a.mp4`` must still
            # resolve from a different .blend in a different directory.
            bpy.data.libraries.write(
                path, set(images), path_remap='ABSOLUTE', fake_user=False, compress=False,
            )
            blend_name = BLEND_NAME
        except Exception:
            logger.warning("Moodboard copy buffer: writing %s failed", path, exc_info=True)
            return None

    buffer_id = uuid.uuid4().hex
    manifest = {
        "version": MANIFEST_VERSION,
        "buffer_id": buffer_id,
        "token": PROCESS_TOKEN,
        "pid": os.getpid(),
        "written_at": time.time(),
        "blend": blend_name,
        "image_names": [image.name for image in images],
        "system_image_size": list(system_image_size) if system_image_size else None,
        "payload": payload,
    }
    try:
        _write_manifest(manifest)
    except (OSError, TypeError, ValueError):
        logger.warning("Moodboard copy buffer: writing the manifest failed", exc_info=True)
        return None
    return buffer_id


def read_manifest() -> dict | None:
    """The current manifest, or None when there is none or it is unreadable."""
    path = manifest_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict) or manifest.get("version") != MANIFEST_VERSION:
        return None
    if not isinstance(manifest.get("payload"), dict) or not manifest.get("buffer_id"):
        return None
    return manifest


def is_own(manifest: dict | None) -> bool:
    return bool(manifest) and manifest.get("token") == PROCESS_TOKEN


def import_buffer_images(manifest: dict) -> dict:
    """Append the buffer's images into this file. ``{recorded name: Image}``.

    An appended datablock may come back renamed (``chair.png.001``) when this
    file already holds that name, so callers must resolve through this map and
    never by the recorded name. Names the ``.blend`` does not carry, and IDs
    Blender could not read, are simply absent from the map.
    """
    blend_name = str(manifest.get("blend") or "")
    names = [str(name) for name in manifest.get("image_names") or () if name]
    if not blend_name or not names:
        return {}
    path = os.path.join(buffer_directory(), blend_name)
    if not os.path.isfile(path):
        logger.warning("Moodboard copy buffer: %s is missing", path)
        return {}
    available: list[str] = []
    try:
        with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
            present = set(data_from.images)
            available = [name for name in names if name in present]
            data_to.images = list(available)
        loaded = list(data_to.images)
    except Exception:
        logger.warning("Moodboard copy buffer: appending from %s failed", path, exc_info=True)
        return {}
    mapping = {}
    for name, image in zip(available, loaded):
        if image is None:
            continue
        if _is_movie(image):
            # The source clip must still be there; a movie whose file is gone
            # would be a dead tile.
            try:
                if int(getattr(image, "frame_duration", 0) or 0) < 1:
                    bpy.data.images.remove(image)
                    continue
            except Exception:
                pass
        mapping[name] = image
    return mapping
