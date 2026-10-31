# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parent side: the snapshot a worker job runs on.

``save_as_mainfile(copy=True)`` is the one way to hand another process the
document from Python that is both complete and safe in this process:

- It is Blender's own writer, the same one memfile undo uses, so it reads the
  data and changes nothing: ``bpy.data.filepath`` and the dirty flag stay,
  edit-mode meshes are flushed first (``bpy.data.libraries.write`` writes the
  stale mesh, and writing a Scene through it crashed 5.2 — export_package.py).
- ``thumbnail=False`` skips the AUTO preview, an EEVEE camera render that cost
  seconds on production scenes (turn_checkpoints.py), and
  ``keep_windows_for_snapshot`` keeps the chat island open across the save.
- ``relative_remap=True`` rewrites ``//`` paths for the snapshot's folder, so
  textures, caches and libraries resolve in the worker.

A .blend does not hold the pixels of an image that was painted or generated and
not saved. Every such (dirty) image is written beside the snapshot as raw
float32 RGBA, listed in ``images.json``, and the worker puts the pixels back
after it loads the file (``worker_jobs.restore_images``).

Snapshots live under ``supervisor.root_dir()``; :func:`acquire` /
:func:`release` count the jobs that still need one (a crashed job is sent
again on the same file) and delete it after the last.
"""

import json
import os
import time

import bpy

from . import supervisor

SNAPSHOT_PREFIX = "mixar_worker_snapshot_"
_counter = 0
_users = {}       # snapshot folder -> jobs still using it
_cached = {}      # purpose -> (fingerprint, record): the reusable preview snapshot


def _keep_bubble_windows():
    try:
        from mixar.modules.agent_bubble.core.bubble_lifecycle import keep_windows_for_snapshot
        return keep_windows_for_snapshot()
    except Exception:
        import contextlib
        return contextlib.nullcontext()


def dirty_images():
    """Images whose pixels only live in memory (painted, generated, edited)."""
    found = []
    for image in bpy.data.images:
        try:
            if image.type != "IMAGE" or image.source == "TILED" or not image.is_dirty:
                continue
            if not image.has_data or image.size[0] <= 0 or image.size[1] <= 0:
                continue
        except (ReferenceError, AttributeError, RuntimeError):
            continue
        found.append(image)
    return found


def _write_images(images, folder) -> list:
    import numpy as np

    manifest = []
    for index, image in enumerate(images):
        width, height = int(image.size[0]), int(image.size[1])
        channels = int(image.channels)
        buffer = np.empty(width * height * channels, dtype=np.float32)
        image.pixels.foreach_get(buffer)
        name = "image_%04d.f32" % index
        buffer.tofile(os.path.join(folder, name))
        manifest.append({"name": image.name, "file": name, "width": width, "height": height,
                         "channels": channels, "float": bool(image.is_float),
                         "colorspace": str(image.colorspace_settings.name),
                         "alpha_mode": str(image.alpha_mode)})
    return manifest


def write(purpose: str = "job") -> dict:
    """Write the whole document as a snapshot; returns
    ``{"folder", "path", "images", "bytes", "save_s", "images_s"}``."""
    global _counter
    _counter += 1
    folder = os.path.join(supervisor.root_dir(), "snapshots", "%s-%d" % (purpose, _counter))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, SNAPSHOT_PREFIX + str(_counter) + ".blend")
    started = time.perf_counter()
    images = dirty_images()
    manifest = _write_images(images, folder) if images else []
    images_path = ""
    if manifest:
        images_path = os.path.join(folder, "images.json")
        with open(images_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
    images_s = time.perf_counter() - started
    kwargs = dict(filepath=path, copy=True, compress=False, relative_remap=True)
    with _keep_bubble_windows():
        try:
            result = bpy.ops.wm.save_as_mainfile(thumbnail=False, **kwargs)
        except TypeError:  # a binary without Mixar's ``thumbnail`` property
            result = bpy.ops.wm.save_as_mainfile(**kwargs)
    if "FINISHED" not in result or not os.path.isfile(path):
        remove_folder(folder)
        raise RuntimeError("snapshot_failed")
    return {"folder": folder, "path": path, "images": images_path,
            "image_count": len(manifest), "bytes": os.path.getsize(path),
            "save_s": round(time.perf_counter() - started - images_s, 4),
            "images_s": round(images_s, 4)}


def fingerprint(scene, revision) -> tuple:
    """What a reused preview snapshot must still match: the viewport depsgraph
    revision plus the render-facing settings an RNA write may change without
    a depsgraph update."""
    render = scene.render
    view = scene.view_settings
    camera = scene.camera
    return (revision, scene.name, str(render.engine), int(render.resolution_x),
            int(render.resolution_y), int(render.resolution_percentage), int(scene.frame_current),
            str(view.view_transform), str(view.look), float(view.exposure), float(view.gamma),
            str(scene.display_settings.display_device),
            camera.name if camera is not None else "",
            scene.world.name if scene.world is not None else "",
            bool(bpy.data.is_dirty))


def write_or_reuse(purpose: str, key_fn, after_write=None) -> dict:
    """Reuse the last ``purpose`` snapshot while ``key_fn()`` is unchanged and
    no image holds unsaved pixels; otherwise write a new one. ``after_write``
    runs before the new key is taken (the caller flushes the depsgraph tags the
    save's own handlers left, so they do not read as a change next time)."""
    cached = _cached.get(purpose)
    key = key_fn()
    if cached is not None and cached[0] == key and not dirty_images() \
            and os.path.isfile(cached[1]["path"]):
        return dict(cached[1], reused=True, save_s=0.0, images_s=0.0)
    record = write(purpose)
    if after_write is not None:
        after_write()
    previous = _cached.pop(purpose, None)
    _cached[purpose] = (key_fn(), record)
    if previous is not None and not _users.get(previous[1]["folder"]):
        remove_folder(previous[1]["folder"])
    return dict(record, reused=False)


def acquire(record) -> None:
    _users[record["folder"]] = _users.get(record["folder"], 0) + 1


def release(record) -> None:
    folder = record.get("folder") if isinstance(record, dict) else None
    if not folder:
        return
    count = _users.get(folder, 0) - 1
    if count > 0:
        _users[folder] = count
        return
    _users.pop(folder, None)
    if any(cached[1]["folder"] == folder for cached in _cached.values()):
        return  # kept for reuse until replaced
    remove_folder(folder)


def invalidate() -> None:
    """Forget reusable snapshots (a file load replaced the document)."""
    for purpose in list(_cached):
        _key, record = _cached.pop(purpose)
        if not _users.get(record["folder"]):
            remove_folder(record["folder"])


def remove_folder(folder) -> None:
    import shutil
    if folder and os.path.basename(os.path.dirname(folder)) == "snapshots":
        shutil.rmtree(folder, ignore_errors=True)
