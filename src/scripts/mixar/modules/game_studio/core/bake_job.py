# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material baking for a game build, in a BACKGROUND Mixar process.

The user's session does one fast thing on the main thread (``prepare``): it
saves a temporary copy of the file (``copy=True``, no thumbnail, Agent Bubble
windows kept open), or, for an unmodified file on disk, leaves the copying
to the worker. It also reads the pixels of painted-but-unsaved images,
which a file copy would hold stale. A worker then runs ``stage``, which starts

    <this Mixar> -b <copy> --python bake_child.py -- --mixar-bake <config>

through ``godot_runner.run``, the same runner the Godot steps use. It reads
``MIXAR_PROGRESS`` lines into the job, honours cancel, and has a timeout. The
child bakes and writes the whole game package; the Godot stages then run
on it. The copy and its folder are deleted afterwards, and only the bake
cache (``<game_dir>/bake_cache``) stays. A scene with nothing to bake never
comes here, and keeps the in-process export.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid

from ..constants import BAKE_DIRNAME, BAKE_CACHE_DIRNAME, BAKE_TIMEOUT_S
from . import godot_runner
from .jobs import JobError

CHILD_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bake_child.py")
RESULT_SCHEMA = "mixar_bake_result_v1"
MESSAGES = {"cancelled": "Cancelled.", "timeout": "Baking took too long and was stopped.",
            "launch_failed": "The background bake process could not be started."}


def dirty_images():
    """``[(name, width, height, pixels)]`` for images painted but not saved:
    a file copy holds their OLD pixels, so the live ones travel beside it.
    Main thread (pixel reads only; the worker writes them to disk)."""
    import bpy
    import numpy as np
    found = []
    for image in bpy.data.images:
        if not image.is_dirty or not image.has_data or image.size[0] == 0:
            continue
        pixels = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(pixels)
        found.append((image.name, image.size[0], image.size[1], pixels))
    return found


def prepare(scene, game_dir: str) -> dict:
    """Main thread: capture what the copy needs and write the child's config.
    Returns the plain ``bake`` context the worker needs.

    An unmodified file that exists on disk is copied by the worker; otherwise
    a ``copy=True`` save (no thumbnail, Agent Bubble windows kept) writes it.
    Painted-but-unsaved images go along as raw pixels (``dirty_images``)."""
    import bpy
    folder = os.path.join(game_dir, BAKE_DIRNAME, uuid.uuid4().hex[:12])
    os.makedirs(folder, exist_ok=True)
    copy = os.path.join(folder, "scene.mixar")
    dirty = dirty_images()
    source = bpy.data.filepath
    if bpy.data.is_dirty or dirty or not source or not os.path.isfile(source):
        source = ""
        try:
            from mixar.modules.agent_bubble.core.bubble_lifecycle import keep_windows_for_snapshot
        except Exception:  # noqa: BLE001 — headless builds have no bubble
            from contextlib import nullcontext as keep_windows_for_snapshot
        with keep_windows_for_snapshot():
            bpy.ops.wm.save_as_mainfile(filepath=copy, copy=True, thumbnail=False)
    config = {"game_dir": game_dir, "cache_dir": os.path.join(game_dir, BAKE_CACHE_DIRNAME),
              "scene": scene.name, "dirty_images": os.path.join(folder, "dirty.json") if dirty else ""}
    config_path = os.path.join(folder, "config.json")
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump(config, handle)
    return {"folder": folder, "copy": copy, "config": config_path, "binary": bpy.app.binary_path,
            "result": os.path.join(folder, "result.json"), "source": source, "dirty": dirty}


def _materialize(bake: dict) -> None:
    """Worker: copy an unmodified source file, and write the live pixels."""
    import numpy as np
    if bake.get("source"):
        shutil.copyfile(bake["source"], bake["copy"])
    dirty = bake.get("dirty") or []
    if dirty:
        folder = os.path.join(bake["folder"], "dirty")
        os.makedirs(folder, exist_ok=True)
        manifest = []
        for index, (name, width, height, pixels) in enumerate(dirty):
            path = os.path.join(folder, f"{index}.npy")
            np.save(path, pixels.astype(np.float32, copy=False))
            manifest.append({"name": name, "width": width, "height": height, "pixels": path})
        with open(os.path.join(bake["folder"], "dirty.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
        bake["dirty"] = []  # release the memory


def discard(bake: dict) -> None:
    shutil.rmtree(bake.get("folder") or "", ignore_errors=True)


def stage(bake: dict, handle, low: float = 0.0, high: float = 100.0, runner=godot_runner.run) -> dict:
    """Worker thread: run the bake child; returns its result dict or raises
    ``JobError``. The temporary copy is always removed."""
    def report(pct, _step, message):
        handle.progress(low + (high - low) * pct / 100.0, message or "Baking materials")

    handle.progress(low, "Baking materials in the background", force=True)
    try:
        _materialize(bake)
        result = runner(bake["binary"], ["-b", bake["copy"], "-noaudio", "--python", CHILD_SCRIPT, "--",
                                         "--mixar-bake", bake["config"]],
                        bake["result"], "bake", on_progress=report, cancel=handle.cancel_event,
                        timeout=BAKE_TIMEOUT_S, schema=RESULT_SCHEMA)
    finally:
        discard(bake)
    if not result.get("ok"):
        code = result.get("error_code") or "bake_failed"
        raise JobError(MESSAGES.get(code) or result.get("error") or "Baking failed.", code, result)
    return result


class ScaledHandle:
    """A job handle whose 0–100 progress lands in ``[low, high]`` of the
    real one (the Godot stages after a bake)."""

    def __init__(self, handle, low: float, high: float):
        self._handle, self._low, self._high = handle, low, high
        self.job_id, self.cancel_event = handle.job_id, handle.cancel_event

    @property
    def cancelled(self) -> bool:
        return self._handle.cancelled

    def progress(self, pct: float, message=None, force: bool = False) -> None:
        self._handle.progress(self._low + (self._high - self._low) * float(pct) / 100.0, message, force)


def with_bake(bake: dict, work, share: float = 55.0):
    """Wrap a job ``work(handle)`` so the bake runs first (``share`` % of
    the bar) and the Godot work takes the rest."""
    def wrapped(handle):
        result = stage(bake, handle, 0.0, share)
        outcome = work(ScaledHandle(handle, share, 100.0))
        if isinstance(outcome, dict):
            outcome = dict(outcome, bake=result.get("bake"),
                           warnings=list(outcome.get("warnings") or [])
                           + list((result.get("package") or {}).get("warnings") or []))
        return outcome
    return wrapped
