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
pixels, listed in ``images.json``, and the worker puts them back after it loads
the file (``worker_jobs.restore_images``). A byte image is written as uint8
(its own precision, a quarter of the float32 size), a float image as float32;
the manifest names the ``dtype``.

A preview snapshot is reused while the scene fingerprint holds and every dirty
image still has the pixels it was written with: each written image keeps a
change key (size, channels and a CRC-32 of the whole pixel buffer), and a
reuse re-reads the buffers to compare. Blender has no pixel revision in
Python; the read plus CRC costs about a tenth of the write it saves (4K float:
~0.1 s against ~1 s).

Only the pixel read (``foreach_get``, a few ms for a 4K image) runs on the main
thread, for images within :data:`STAGE_BUDGET_BYTES` of staged copies (1 GiB;
the rest are read, written and freed one at a time there, as before). Converting a byte image to uint8 and writing the files (about 50 ms and
75 ms for a 4K image, measured) happens on a background thread
(``write(..., background=True)``): the record carries a ``pending`` event, and
the caller hands :func:`ready` to ``supervisor.submit`` so the job is dispatched
once the files exist. An image whose change key equals the previous snapshot's
is hard-linked from that snapshot instead of written again; the previous
folder is retired only once the new writer is done with it.

Snapshots live under ``supervisor.root_dir()``; :func:`acquire` /
:func:`release` count the jobs that still need one (a crashed job is sent
again on the same file) and delete it after the last.
"""

import json
import os
import threading
import time

import bpy

from . import supervisor

SNAPSHOT_PREFIX = "mixar_worker_snapshot_"
_counter = 0
_users = {}       # snapshot folder -> jobs still using it
_cached = {}      # purpose -> (fingerprint, record): the reusable preview snapshot
_retired = []     # folders to remove once no background writer may link from them
_writers = []     # records whose pixel files are still being written


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
            # Generated images are type UV_TEST; only the render and compositor
            # results are not document data.
            if image.type in ("RENDER_RESULT", "COMPOSITING") or image.source == "TILED" \
                    or not image.is_dirty:
                continue
            if not image.has_data or image.size[0] <= 0 or image.size[1] <= 0:
                continue
        except (ReferenceError, AttributeError, RuntimeError):
            continue
        found.append(image)
    return found


def _pixels(image):
    import numpy as np

    width, height, channels = int(image.size[0]), int(image.size[1]), int(image.channels)
    buffer = np.empty(width * height * channels, dtype=np.float32)
    image.pixels.foreach_get(buffer)
    return buffer, width, height, channels


def _key(name, is_float, buffer, width, height, channels) -> tuple:
    import zlib
    return (name, width, height, channels, bool(is_float), zlib.crc32(memoryview(buffer)))


def _change_key(image, buffer, width, height, channels) -> tuple:
    return _key(image.name, image.is_float, buffer, width, height, channels)


def image_keys(images) -> list:
    """The change key of each image's current pixels (one full read each)."""
    keys = []
    for image in images:
        buffer, width, height, channels = _pixels(image)
        keys.append(_change_key(image, buffer, width, height, channels))
    return keys


#: At most this many bytes of pixel copies wait for the background writer. Each
#: staged image is a float32 copy (a 4K RGBA map is 256 MiB, even a byte image),
#: and they are held through the .blend save, so an unbounded stage could add
#: gigabytes to the app on a texture-heavy document. Images past the budget are
#: read, written and freed one at a time on the calling thread, as before.
STAGE_BUDGET_BYTES = 1 << 30


def _read_one(image, index) -> dict:
    """Main thread: one dirty image's pixels and settings."""
    buffer, width, height, channels = _pixels(image)
    return {"index": index, "name": image.name, "buffer": buffer, "width": width,
            "height": height, "channels": channels, "float": bool(image.is_float),
            "colorspace": str(image.colorspace_settings.name),
            "alpha_mode": str(image.alpha_mode)}


def _read_images(images) -> list:
    """Main thread: every dirty image's pixels and settings, nothing written."""
    return [_read_one(image, index) for index, image in enumerate(images)]


def _staged_bytes(image) -> int:
    return int(image.size[0]) * int(image.size[1]) * int(image.channels) * 4


def _link_or_none(source, target) -> bool:
    try:
        os.link(source, target)
        return True
    except OSError:
        return False


def _store_one(entry, folder, previous=None) -> tuple:
    """Any thread, no ``bpy``: write one image read by :func:`_read_one` (its
    buffer is released), or hard-link it from ``previous`` (``{name: (key,
    path)}``) when unchanged. Returns ``(index, manifest item, key, path)``."""
    import numpy as np

    entry = dict(entry)
    buffer = entry.pop("buffer")
    index = entry.pop("index")
    width, height, channels = entry["width"], entry["height"], entry["channels"]
    key = _key(entry["name"], entry["float"], buffer, width, height, channels)
    dtype = "float32" if entry["float"] else "uint8"
    name = "image_%04d.%s" % (index, "f32" if entry["float"] else "u8")
    path = os.path.join(folder, name)
    old = (previous or {}).get(entry["name"])
    if not (old and tuple(old[0]) == key and _link_or_none(old[1], path)):
        if not entry["float"]:
            # A byte image holds 8 bits per channel: x255 rounds back exactly.
            np.multiply(buffer, 255.0, out=buffer)
            np.rint(buffer, out=buffer)
            np.clip(buffer, 0.0, 255.0, out=buffer)
            buffer = buffer.astype(np.uint8)
        buffer.tofile(path)
    del buffer
    return index, dict(entry, file=name, dtype=dtype), key, path


def _collect(results) -> tuple:
    """``(manifest, keys, files)`` in the images' original order."""
    manifest, keys, files = [], [], {}
    for _index, item, key, path in sorted(results, key=lambda r: r[0]):
        manifest.append(item)
        keys.append(key)
        files[item["name"]] = (key, path)
    return manifest, keys, files


def _store_images(entries, folder, previous=None):
    """Store every entry (releasing each buffer as it goes); returns
    ``(manifest, keys, files)``."""
    results = []
    while entries:
        results.append(_store_one(entries.pop(0), folder, previous))
    return _collect(results)


def _write_images(images, folder):
    """Write the pixels now; returns ``(manifest, change keys)``."""
    manifest, keys, _files = _store_images(_read_images(images), folder)
    return manifest, keys


def _finish_images(record, entries, previous, done=()):
    """Store ``entries`` and write the manifest, with ``done`` (results already
    stored on the calling thread) merged in their original order."""
    started = time.perf_counter()
    try:
        results = list(done)
        while entries:
            results.append(_store_one(entries.pop(0), record["folder"], previous))
        manifest, keys, files = _collect(results)
        with open(record["images"], "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
        record.update(image_keys=keys, image_files=files)
    except Exception:  # disk full, a removed folder: the job falls back in-process
        record["error"] = "snapshot_failed"
    record["images_write_s"] = round(time.perf_counter() - started, 4)


def ready(record) -> bool:
    """Whether the snapshot's files are all on disk (main thread). Raises
    ``RuntimeError`` when the background writer failed."""
    pending = record.get("pending")
    if pending is not None and not pending.is_set():
        return False
    if record.get("error"):
        raise RuntimeError(record["error"])
    _sweep_retired()
    return True


def write(purpose: str = "job", background: bool = False, previous=None) -> dict:
    """Write the whole document as a snapshot; returns
    ``{"folder", "path", "images", "bytes", "save_s", "images_s"}``.

    The .blend is saved and the dirty pixels are read here, on the calling
    (main) thread. With ``background`` the pixel files of the images that fit
    :data:`STAGE_BUDGET_BYTES` are written on a thread (the rest here, one at a
    time): the record then has a ``pending`` event and :func:`ready` says when
    it is complete. ``previous`` (a record) lends unchanged image files."""
    global _counter
    _counter += 1
    folder = os.path.join(supervisor.root_dir(), "snapshots", "%s-%d" % (purpose, _counter))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, SNAPSHOT_PREFIX + str(_counter) + ".blend")
    started = time.perf_counter()
    lend = dict((previous or {}).get("image_files") or {})
    entries, done, staged = [], [], 0
    for index, image in enumerate(dirty_images()):
        size = _staged_bytes(image)
        if background and staged + size <= STAGE_BUDGET_BYTES:
            entries.append(_read_one(image, index))
            staged += size
        else:  # over the budget (or synchronous): read, write, free, one at a time
            try:
                done.append(_store_one(_read_one(image, index), folder, lend))
            except Exception:
                remove_folder(folder)
                raise RuntimeError("snapshot_failed")
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
    record = {"folder": folder, "path": path,
              "images": os.path.join(folder, "images.json") if entries or done else "",
              "image_count": len(entries) + len(done), "image_keys": [], "image_files": {},
              "staged_bytes": staged,
              "bytes": os.path.getsize(path),
              "save_s": round(time.perf_counter() - started - images_s, 4),
              "images_s": round(images_s, 4)}
    if not entries and not done:
        return record
    if entries:
        record["pending"] = threading.Event()
        _writers.append(record)

        def run():
            try:
                _finish_images(record, entries, lend, done)
            finally:
                record["pending"].set()

        threading.Thread(target=run, name="mixar-snapshot-images", daemon=True).start()
        return record
    _finish_images(record, entries, lend, done)
    if record.get("error"):
        remove_folder(folder)
        raise RuntimeError("snapshot_failed")
    return record


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


def write_or_reuse(purpose: str, key_fn, after_write=None, background: bool = False) -> dict:
    """Reuse the last ``purpose`` snapshot while ``key_fn()`` is unchanged and
    every dirty image holds the pixels it was written with; otherwise write a
    new one (its unchanged images hard-linked from the last). ``after_write``
    runs before the new key is taken (the caller flushes the depsgraph tags
    the save's own handlers left, so they do not read as a change next time)."""
    _sweep_retired()
    cached = _cached.get(purpose)
    key = key_fn()
    previous = cached[1] if cached is not None and _settled(cached[1]) else None
    if previous is not None and cached[0] == key and os.path.isfile(previous["path"]):
        started = time.perf_counter()
        try:
            unchanged = image_keys(dirty_images()) == previous.get("image_keys")
        except (ReferenceError, RuntimeError, AttributeError):
            unchanged = False
        if unchanged:
            return dict(previous, reused=True, save_s=0.0,
                        images_s=round(time.perf_counter() - started, 4))
    record = write(purpose, background=background, previous=previous)
    if after_write is not None:
        after_write()
    old = _cached.pop(purpose, None)
    _cached[purpose] = (key_fn(), record)
    if old is not None and not _users.get(old[1]["folder"]):
        _retire(old[1]["folder"])
    # The live record, never a copy: its background writer fills it in, and
    # ``ready`` must see that writer's error on the object the caller holds.
    record["reused"] = False
    return record


def _settled(record) -> bool:
    pending = record.get("pending")
    return (pending is None or pending.is_set()) and not record.get("error")


def _retire(folder) -> None:
    if folder not in _retired:
        _retired.append(folder)
    _sweep_retired()


def _sweep_retired() -> None:
    """Remove retired snapshots, but only while no background writer runs: a
    writer may be hard-linking an unchanged image out of any of them."""
    _writers[:] = [r for r in _writers if not r["pending"].is_set()]
    if _writers:
        return
    for folder in list(_retired):
        _retired.remove(folder)
        if not _users.get(folder) and not any(c[1]["folder"] == folder for c in _cached.values()):
            remove_folder(folder)


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
    _retire(folder)


def invalidate() -> None:
    """Forget reusable snapshots (a file load replaced the document)."""
    _sweep_retired()
    for purpose in list(_cached):
        _key, record = _cached.pop(purpose)
        if not _users.get(record["folder"]):
            _retire(record["folder"])


def remove_folder(folder) -> None:
    import shutil
    if folder and os.path.basename(os.path.dirname(folder)) == "snapshots":
        shutil.rmtree(folder, ignore_errors=True)
