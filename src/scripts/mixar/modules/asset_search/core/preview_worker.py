# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parent-side management of the headless preview-render workers.

For large training plans, preview rendering runs in SEPARATE windowless
Mixar/Blender processes (``-b --factory-startup --python preview_worker_script``)
so the user's session never freezes. Each worker streams one JSON line per
finished asset into its own ``results.jsonl``; the training modal polls them for
real-time progress and loads the produced JPEGs (packed) when done.

Big plans are SHARDED across several processes (rendering is CPU-bound and
perfectly parallel). Shards are split on **.blend boundaries** so no two
processes open — or, during thumbnail backfill, save — the same library file,
and so each shard keeps the benefit of the linked-library reuse in
``preview_worker_script`` (consecutive items from one file are parsed once).

Fallback contract: any failure to start — or workers that die before producing
a single result — makes the caller fall back to the in-process chunked
RenderSession, so training always works.
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

# Assets per shard, at minimum: another Blender process costs ~5-15s of startup
# and a few hundred MB of RSS, so it has to have real work to repay that.
SHARD_MIN_ITEMS = 50
# Hard ceiling on concurrent worker processes. Each is a full Blender; on a
# many-core machine an unbounded fan-out trades a frozen UI for a swapping one.
MAX_SHARDS = 6


def _shard_count(item_count):
    """How many worker processes to run for ``item_count`` assets."""
    try:
        cores = os.cpu_count() or 1
    except Exception:  # noqa: BLE001 — an unknown core count is not fatal
        cores = 1
    # Leave headroom for the user's own session (UI + its render/depsgraph).
    budget = max(1, min(cores - 2, MAX_SHARDS))
    return max(1, min(budget, item_count // SHARD_MIN_ITEMS))


def _split_items(items, shards):
    """Split ``items`` into ``shards`` lists, never splitting a .blend file.

    Two processes must not touch the same library file: the worker's thumbnail
    backfill REOPENS AND SAVES each .blend it rendered from, so a file split
    across shards would have one shard's previews overwritten by the other's
    save. Grouping also preserves the linked-library reuse inside each worker.

    Groups are placed largest-first into the currently-lightest shard (greedy
    bin packing), which keeps the finish times close without any coordination.
    """
    if shards <= 1:
        return [list(items)]

    by_blend = {}
    for item in items:
        by_blend.setdefault(item["blend_str"], []).append(item)

    buckets = [[] for _ in range(shards)]
    for group in sorted(by_blend.values(), key=len, reverse=True):
        smallest = min(range(shards), key=lambda i: len(buckets[i]))
        buckets[smallest].extend(group)
    return [b for b in buckets if b]


class _Shard:
    """One running worker process and the output directory it owns."""

    def __init__(self, proc, work_dir, total):
        self.proc = proc
        self.dir = work_dir
        self.total = total
        self.results_path = os.path.join(work_dir, "results.jsonl")
        self.done_marker = os.path.join(work_dir, "done.marker")
        self.heartbeat_path = os.path.join(work_dir, "heartbeat")
        self._offset = 0
        self.results = []          # every parsed line, in order
        self.last_activity = time.time()
        self.done = False


class WorkerHandle:
    """State for one training run's worker processes (one or more shards)."""

    def __init__(self, work_dir, shards):
        self.work_dir = work_dir
        self.shards = shards
        self.total = sum(s.total for s in shards)

    @property
    def results(self):
        """Every parsed result line across all shards."""
        out = []
        for shard in self.shards:
            out.extend(shard.results)
        return out

    @property
    def ok_results(self):
        return [r for r in self.results if r.get("ok")]

    @property
    def failures(self):
        return [
            (r.get("label", "?"), r.get("reason", "failed"))
            for r in self.results if not r.get("ok")
        ]


def _spawn(script_path, plan_path, work_dir):
    """Launch one worker process for ``plan_path``. Returns the Popen."""
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    log_file = open(os.path.join(work_dir, "worker.log"), "w", encoding="utf-8")
    return subprocess.Popen(
        [bpy.app.binary_path, "-b", "--factory-startup",
         "--python", script_path, "--", plan_path],
        stdout=log_file, stderr=subprocess.STDOUT, creationflags=creationflags,
    )


def start_worker(items):
    """Launch the headless worker(s) for ``items``. Returns a handle or None."""
    try:
        from mixar.modules.asset_search.core import preview_worker_script
        script_path = os.path.abspath(preview_worker_script.__file__)
        if script_path.endswith((".pyc", ".pyo")):
            script_path = script_path[:-1]

        work_dir = tempfile.mkdtemp(prefix="mixar_previews_")
        # Combined plan at the root: never executed, it is what the caller
        # re-reads to rebuild the item list for the in-process fallback.
        with open(os.path.join(work_dir, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"items": items}, fh)

        chunks = _split_items(items, _shard_count(len(items)))
        shards = []
        for index, chunk in enumerate(chunks):
            shard_dir = os.path.join(work_dir, f"shard_{index:02d}")
            os.makedirs(shard_dir, exist_ok=True)
            plan_path = os.path.join(shard_dir, "plan.json")
            with open(plan_path, "w", encoding="utf-8") as fh:
                json.dump({"items": chunk, "out_dir": shard_dir}, fh)
            proc = _spawn(script_path, plan_path, shard_dir)
            shards.append(_Shard(proc, shard_dir, len(chunk)))

        logger.info(
            "[PreviewWorker] Started %d worker(s) for %d assets (%s): pids=%s",
            len(shards), len(items), work_dir,
            ",".join(str(s.proc.pid) for s in shards),
        )
        return WorkerHandle(work_dir, shards)
    except Exception as e:  # noqa: BLE001 — caller falls back to in-process
        logger.warning("[PreviewWorker] Could not start worker: %s", e)
        return None


def _poll_shard(shard):
    """Read one shard's new result lines; updates its done/activity state."""
    new = []
    try:
        if os.path.exists(shard.results_path):
            with open(shard.results_path, "r", encoding="utf-8") as fh:
                fh.seek(shard._offset)
                chunk = fh.read()
                shard._offset = fh.tell()
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    # Torn write of the final line — re-read next poll.
                    shard._offset -= len(line) + 1
                    break
                # Tag the owning directory: result `file` names are per-shard
                # indices, so they only resolve against their own shard dir.
                entry["_dir"] = shard.dir
                new.append(entry)
    except OSError as e:
        logger.warning("[PreviewWorker] poll read error: %s", e)

    if new:
        shard.results.extend(new)
        shard.last_activity = time.time()
    else:
        # A worker that is busy but between result lines still touches the
        # heartbeat file — count that as activity so the stall watchdog only
        # fires on a genuinely hung process.
        try:
            hb = os.path.getmtime(shard.heartbeat_path)
            if hb > shard.last_activity:
                shard.last_activity = hb
        except OSError:
            pass

    exited = shard.proc.poll() is not None
    shard.done = os.path.exists(shard.done_marker) or (
        exited and len(shard.results) >= shard.total
    )
    # An exited process that never wrote done.marker and has nothing more to
    # give is also terminal (crash) — but give one extra poll for lag.
    if exited and not new and not shard.done:
        shard.done = True
    stalled = (
        not exited and time.time() - shard.last_activity > STALL_TIMEOUT
    )
    return new, stalled


def poll(handle):
    """Read new result lines from every shard. Returns (new, done, stalled)."""
    new = []
    done = True
    stalled = False
    for shard in handle.shards:
        shard_new, shard_stalled = _poll_shard(shard)
        new.extend(shard_new)
        done = done and shard.done
        # A shard that is alive but silent past the timeout hangs the whole
        # run — the caller cannot finish without its assets.
        stalled = stalled or (shard_stalled and not shard.done)
    return new, done, stalled


def died_early(handle):
    """True when nothing at all was produced and every shard exited abnormally.

    The caller's cue to fall back to the in-process render session.
    """
    if handle.results:
        return False
    return all(s.proc.poll() not in (0, None) for s in handle.shards)


def stop(handle):
    """Terminate every worker process (cancel/stall)."""
    for shard in handle.shards:
        try:
            if shard.proc.poll() is None:
                shard.proc.terminate()
                try:
                    shard.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    shard.proc.kill()
        except Exception as e:  # noqa: BLE001
            logger.warning("[PreviewWorker] stop error: %s", e)


def results_to_infos(results, used_names):
    """Metadata dicts for finished assets, pointing at the JPEGs on disk.

    Nothing is loaded into ``bpy.data.images``: the upload phase reads these
    files directly, so a large library never packs hundreds of previews into
    the user's session (which also cost a second JPEG re-encode on the way
    out). The caller therefore OWNS the work dir until the upload finishes —
    call ``cleanup()`` only then.

    Takes RAW result lines rather than a handle so the caller can convert each
    poll's NEW results and hand them straight to the streaming uploader.
    ``used_names`` is the caller's running set: ``image_name`` is the key the
    SERVER pairs metadata to embeddings on, so it must be unique across the
    whole request — bpy's datablock suffixing used to provide that implicitly.
    """
    collected = []
    for r in results:
        if not r.get("ok"):
            continue
        path = os.path.join(r.get("_dir", ""), r.get("file", ""))
        info = r.get("info") or {}
        if not info or not os.path.isfile(path):
            continue
        img_name = f"asset_preview_{info.get('name', '')}"
        if img_name in used_names:
            suffix = 1
            while f"{img_name}.{suffix:03d}" in used_names:
                suffix += 1
            img_name = f"{img_name}.{suffix:03d}"
        used_names.add(img_name)
        info["image_name"] = img_name
        info["image_path"] = path
        collected.append(info)
    return collected


def backfill_entries(handle):
    """Assets the workers RENDERED, for the detached thumbnail backfill.

    Each shard records its own list rather than writing thumbnails back itself:
    that pass reopens and re-saves whole .blend files, so keeping it inside the
    render worker put gigabytes of writes between the last render and
    done.marker. Shards split on .blend boundaries, so the merged list never
    has two shards pointing at one file.
    """
    entries = []
    for shard in handle.shards:
        path = os.path.join(shard.dir, "backfill.json")
        try:
            with open(path, encoding="utf-8") as fh:
                entries.extend(json.load(fh))
        except (OSError, json.JSONDecodeError):
            continue
    return entries


def cleanup(handle_or_dir):
    """Remove a work dir. Accepts a handle or a path.

    MUST NOT run before the upload phase has read the previews — they are
    plain files now, not packed datablocks.
    """
    work_dir = getattr(handle_or_dir, "work_dir", handle_or_dir)
    if not work_dir:
        return
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        pass


def start_backfill(entries):
    """Fire-and-forget worker that writes rendered thumbnails back into their
    source .blend files (backfill-only mode; the worker deletes its own work
    dir when finished). Used after IN-PROCESS renders — worker-run renders
    backfill inside the worker itself.

    ``entries``: [{"blend_str", "name", "jpg"}] — jpg paths must live inside
    the plan's out_dir (the caller writes them there) so cleanup_self removes
    everything.
    """
    if not entries:
        return
    try:
        from mixar.modules.asset_search.core import preview_worker_script
        script_path = os.path.abspath(preview_worker_script.__file__)
        if script_path.endswith((".pyc", ".pyo")):
            script_path = script_path[:-1]

        work_dir = os.path.dirname(entries[0]["jpg"])
        plan_path = os.path.join(work_dir, "plan.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump({"backfill": entries, "out_dir": work_dir,
                       "cleanup_self": True}, fh)

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            [bpy.app.binary_path, "-b", "--factory-startup",
             "--python", script_path, "--", plan_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        logger.info("[PreviewWorker] Backfill launched for %d thumbnails",
                    len(entries))
    except Exception as e:  # noqa: BLE001 — backfill is best-effort
        logger.warning("[PreviewWorker] Could not start backfill: %s", e)


def worker_exit_summary(handle):
    """Short diagnostic for workers that died early (for logs/messages)."""
    parts = []
    for index, shard in enumerate(handle.shards):
        tail = ""
        try:
            with open(os.path.join(shard.dir, "worker.log"), "r",
                      encoding="utf-8", errors="replace") as fh:
                tail = fh.read()[-400:]
        except OSError:
            pass
        parts.append(
            f"shard{index}: exit={shard.proc.poll()} "
            f"done={len(shard.results)}/{shard.total} log_tail={tail!r}"
        )
    return " | ".join(parts)
