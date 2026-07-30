# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parent-side management of the headless preview-render worker.

For large training plans, preview rendering runs in a SEPARATE windowless
Mixar/Blender process (``-b --factory-startup --python preview_worker_script``)
so the user's session never freezes. The worker streams one JSON line per
finished asset into ``results.jsonl``; the training modal polls it for
real-time progress and loads the produced JPEGs (packed) when done.

Fallback contract: any failure to start — or a worker that dies before
producing a single result — makes the caller fall back to the in-process
chunked RenderSession, so training always works.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Below this many assets the in-process chunked session is fine (and avoids
# a ~5-15s worker startup); above it, the headless worker keeps the app free.
WORKER_MIN_ITEMS = 25

# No new result line for this long while the process lives = hung worker.
STALL_TIMEOUT = 180.0


class WorkerHandle:
    """State for one running worker process."""

    def __init__(self, proc, work_dir, total):
        self.proc = proc
        self.work_dir = work_dir
        self.total = total
        self.results_path = os.path.join(work_dir, "results.jsonl")
        self.done_marker = os.path.join(work_dir, "done.marker")
        self._offset = 0
        self.results = []          # every parsed line, in order
        self.last_activity = time.time()

    @property
    def ok_results(self):
        return [r for r in self.results if r.get("ok")]

    @property
    def failures(self):
        return [
            (r.get("label", "?"), r.get("reason", "failed"))
            for r in self.results if not r.get("ok")
        ]


def start_worker(items):
    """Launch the headless worker for ``items``. Returns a handle or None."""
    try:
        from mixar.modules.asset_search.core import preview_worker_script
        script_path = os.path.abspath(preview_worker_script.__file__)
        if script_path.endswith((".pyc", ".pyo")):
            script_path = script_path[:-1]

        work_dir = tempfile.mkdtemp(prefix="mixar_previews_")
        plan_path = os.path.join(work_dir, "plan.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump({"items": items, "out_dir": work_dir}, fh)

        cmd = [
            bpy.app.binary_path, "-b", "--factory-startup",
            "--python", script_path, "--", plan_path,
        ]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        log_path = os.path.join(work_dir, "worker.log")
        log_file = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd, stdout=log_file, stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        logger.info("[PreviewWorker] Started pid=%s for %d assets (%s)",
                    proc.pid, len(items), work_dir)
        return WorkerHandle(proc, work_dir, len(items))
    except Exception as e:  # noqa: BLE001 — caller falls back to in-process
        logger.warning("[PreviewWorker] Could not start worker: %s", e)
        return None


def poll(handle):
    """Read new result lines. Returns (new_results, done, stalled)."""
    new = []
    try:
        if os.path.exists(handle.results_path):
            with open(handle.results_path, "r", encoding="utf-8") as fh:
                fh.seek(handle._offset)
                chunk = fh.read()
                handle._offset = fh.tell()
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    new.append(json.loads(line))
                except json.JSONDecodeError:
                    # Torn write of the final line — re-read next poll.
                    handle._offset -= len(line) + 1
                    break
    except OSError as e:
        logger.warning("[PreviewWorker] poll read error: %s", e)

    if new:
        handle.results.extend(new)
        handle.last_activity = time.time()

    exited = handle.proc.poll() is not None
    done = os.path.exists(handle.done_marker) or (
        exited and len(handle.results) >= handle.total
    )
    # An exited process that never wrote done.marker and has nothing more to
    # give is also terminal (crash) — but give one extra poll for lag.
    if exited and not new and not done:
        done = True
    stalled = (
        not exited and time.time() - handle.last_activity > STALL_TIMEOUT
    )
    return new, done, stalled


def stop(handle):
    """Terminate the worker process (cancel/stall)."""
    try:
        if handle.proc.poll() is None:
            handle.proc.terminate()
            try:
                handle.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                handle.proc.kill()
    except Exception as e:  # noqa: BLE001
        logger.warning("[PreviewWorker] stop error: %s", e)


def collect_images(handle):
    """Load + pack the worker's JPEGs; return metadata dicts (image_name set).

    Runs on the main thread after the worker finishes — loading a JPEG is
    milliseconds, so even hundreds stay far from a freeze.
    """
    collected = []
    for r in handle.ok_results:
        path = os.path.join(handle.work_dir, r.get("file", ""))
        info = r.get("info") or {}
        if not info or not os.path.isfile(path):
            continue
        img_name = f"asset_preview_{info.get('name', '')}"
        try:
            existing = bpy.data.images.get(img_name)
            if existing:
                bpy.data.images.remove(existing)
            img = bpy.data.images.load(path)
            img.name = img_name
            img.pack()
            info["image_name"] = img.name  # may differ if Blender suffixed it
            collected.append(info)
        except Exception as e:  # noqa: BLE001 — one bad file must not stop the run
            logger.warning("[PreviewWorker] Could not load %s: %s", path, e)
    return collected


def cleanup(handle):
    """Remove the work dir (images are packed into .blend datablocks by now)."""
    try:
        shutil.rmtree(handle.work_dir, ignore_errors=True)
    except Exception:
        pass


def worker_exit_summary(handle):
    """Short diagnostic for a worker that died early (for logs/messages)."""
    code = handle.proc.poll()
    log_path = os.path.join(handle.work_dir, "worker.log")
    tail = ""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            tail = fh.read()[-500:]
    except OSError:
        pass
    return f"exit={code} log_tail={tail!r}"
