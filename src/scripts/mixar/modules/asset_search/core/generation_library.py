# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Auto-curated "Mixar Generations" asset library.

Every completed image->3D / model-3D generation is archived into a
Mixar-owned asset library (registered like any user library) and, once the
generation queue has drained of qualifying jobs, embedded via the existing
incremental training flow — so past generations become reusable (agent
library picker + Assets-workspace search) instead of being regenerated.

Implemented entirely as a queue LISTENER so nothing in common/job_queue
changes: the listener fires on every job state change, saves newly-succeeded
qualifying jobs, and triggers one incremental retrain when the qualifying
queues drain (which also fires when the last job FAILS).
"""

import time

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.constants import (
    GENERATION_LIBRARY_JOB_TYPES,
    GENERATION_LIBRARY_NAME,
    GENERATION_LIBRARY_SUBPATH,
)

logger = get_logger(__name__)

# Feature-queue keys whose jobs can be qualifying generations. The per-job
# `job_type` guard is the real filter; these just tell us which queues to watch.
_QUALIFYING_FEATURE_KEYS = ("image_to_3d_pro", "model_3d")

# Jobs already archived (by id), so the repeatedly-firing listener never
# double-writes. Bounded implicitly by generation volume per session.
_saved_job_ids: set = set()
# At least one asset was saved since the last retrain — gate so an all-failed
# batch doesn't fire a pointless train.
_batch_dirty = False
_retrain_scheduled = False
_MAX_RETRAIN_WAIT_TICKS = 60  # ~60 * 2s = 2 min max wait for a busy manual train
# Deferred-archive queue: newly-succeeded jobs are archived one-per-timer-tick
# OFF the synchronous queue-notify path, so a completing generation never blocks
# the queue and each preview render is separated by a UI frame.
_archive_queue: list = []
_archive_timer_running = False


# --------------------------------------------------------------------------- #
# Library path + registration
# --------------------------------------------------------------------------- #

def get_library_path() -> str:
    """User-writable folder holding the Mixar Generations .blends."""
    try:
        return bpy.utils.user_resource(
            "DATAFILES", path=GENERATION_LIBRARY_SUBPATH, create=True
        )
    except Exception:
        import os
        path = os.path.join(
            os.path.expanduser("~"), ".mixar", "generations"
        )
        os.makedirs(path, exist_ok=True)
        return path


def ensure_registered() -> None:
    """Idempotently register the Mixar Generations library in preferences.

    Runs every startup — Blender persists library registration in userpref,
    but re-adding here makes fresh machines / lost prefs self-heal without a
    (blocking, risky) save_userpref call.
    """
    try:
        path = get_library_path()
        libs = bpy.context.preferences.filepaths.asset_libraries
        for lib in libs:
            if lib.name == GENERATION_LIBRARY_NAME:
                # Keep the path correct if the resource dir moved.
                if bpy.path.abspath(lib.path) != bpy.path.abspath(path):
                    lib.path = path
                return
        new_lib = libs.new(name=GENERATION_LIBRARY_NAME)
        new_lib.path = path
        logger.info("[GenLibrary] Registered '%s' -> %s", GENERATION_LIBRARY_NAME, path)
        # Auto-enroll our OWN library the first time it is registered, so
        # archived generations are actually embedded and become reusable out of
        # the box (archival is a platform default, not an opt-in). Only on NEW
        # registration — a later deliberate un-enroll by the user is respected.
        try:
            from mixar.modules.asset_search.core.library_enrollment import (
                set_enrolled,
            )
            set_enrolled(GENERATION_LIBRARY_NAME, True)
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.debug("[GenLibrary] auto-enroll skipped: %s", exc)
    except Exception:
        logger.exception("[GenLibrary] Could not register the generations library")


def ensure_library_dirs() -> None:
    """Create any registered asset-library folder that is missing on disk.

    Saving into a library whose directory does not exist fails deep in Blender
    with an opaque "cannot open the target file path for writing (No such file
    or directory)" — the agent's save_to_asset_library runs in a no-``os``
    sandbox and cannot create it. A stale entry (e.g. an old build's
    "User Library" -> Documents/Mixar/Assets that was never created) then
    silently breaks every save that defaults to it. Self-heal here at startup,
    where ``os`` is available; best-effort and per-library so a path on a
    disconnected drive just skips.
    """
    import os

    try:
        libs = bpy.context.preferences.filepaths.asset_libraries
    except Exception:
        return
    for lib in libs:
        try:
            root = bpy.path.abspath(lib.path or "").strip()
            if not root or os.path.isdir(root):
                continue
            # NEVER materialize a missing dir over a removable/unmounted volume:
            # an unplugged external drive's mount point (e.g. /Volumes/Assets on
            # macOS) is "not a directory", and creating a real folder there
            # blocks the drive from remounting. Only self-heal a library whose
            # PARENT already exists — that's the stale-Mixar-default case the
            # heal is for — OR our own Generations library, whose path lives
            # under the user resource dir and is always safe to create.
            is_mixar = lib.name == GENERATION_LIBRARY_NAME
            if not (is_mixar or os.path.isdir(os.path.dirname(root))):
                logger.debug(
                    "[GenLibrary] Skipped missing library '%s' -> %s "
                    "(parent absent — likely an unmounted volume)",
                    getattr(lib, "name", "?"), root,
                )
                continue
            os.makedirs(root, exist_ok=True)
            logger.info("[GenLibrary] Created missing library dir for '%s' -> %s",
                        lib.name, root)
        except Exception as exc:  # noqa: BLE001 — non-local/removable paths just skip
            logger.debug("[GenLibrary] Skipped library dir for '%s': %s",
                         getattr(lib, "name", "?"), exc)


# --------------------------------------------------------------------------- #
# Listener wiring
# --------------------------------------------------------------------------- #

def attach_listeners() -> None:
    """Attach the save/retrain listener to the qualifying feature queues."""
    try:
        from mixar.modules.common.job_queue.core.helpers import (
            get_queue_with_listener,
        )
        for feature_key in _QUALIFYING_FEATURE_KEYS:
            get_queue_with_listener(feature_key, _on_queue_changed)
    except Exception:
        logger.exception("[GenLibrary] Could not attach queue listeners")


def _on_queue_changed(queue) -> None:
    """Listener: save newly-succeeded qualifying jobs; retrain on full drain.

    Called on every state change of a watched queue. Non-fatal throughout —
    a failure here must never disturb the user's generation.
    """
    try:
        from mixar.modules.common.job_queue.core.job import JobState

        enqueued = False
        for job in queue.snapshot():
            if job.id in _saved_job_ids:
                continue
            if job.state != JobState.SUCCESS:
                continue
            if not _is_qualifying(job):
                continue
            if not (job.imported_object_names or "").strip():
                continue
            _saved_job_ids.add(job.id)  # mark first — never retry a bad save
            # Archive OFF this synchronous notify call — the actual save renders
            # a 512² preview on the main thread, which must not block the queue.
            _archive_queue.append(job)
            enqueued = True

        if enqueued:
            _ensure_archive_timer()
        elif _batch_dirty and not _archive_queue and _all_qualifying_queues_idle():
            # No new archives pending and the queues have drained — kick the
            # retrain now (otherwise it fires when the archive queue empties).
            _schedule_retrain()
    except Exception:
        logger.exception("[GenLibrary] listener error")


def _ensure_archive_timer() -> None:
    global _archive_timer_running
    if _archive_timer_running:
        return
    _archive_timer_running = True
    bpy.app.timers.register(_process_archive_queue, first_interval=0.0)


def _process_archive_queue():
    """Archive ONE queued generation per tick, then reschedule if more remain.

    Runs on the main thread (bpy.data / rendering require it) but OFF the
    synchronous queue listener, so a completing generation returns immediately
    and the UI gets a frame between preview renders instead of freezing through
    a back-to-back burst."""
    global _archive_timer_running
    if not _archive_queue:
        _archive_timer_running = False
        if _batch_dirty and _all_qualifying_queues_idle():
            _schedule_retrain()
        return None

    job = _archive_queue.pop(0)
    try:
        _save_job(job)
    except Exception:
        logger.exception(
            "[GenLibrary] deferred archive failed for job %s",
            getattr(job, "id", "?")[:8],
        )

    if _archive_queue:
        return 0.0  # more to archive — next tick (UI redraws between)
    _archive_timer_running = False
    if _batch_dirty and _all_qualifying_queues_idle():
        _schedule_retrain()
    return None


# --------------------------------------------------------------------------- #
# Save + drain + retrain
# --------------------------------------------------------------------------- #

def _is_qualifying(job) -> bool:
    job_type = getattr(job, "job_type", "") or getattr(job, "service", "")
    return job_type in GENERATION_LIBRARY_JOB_TYPES


def _pick_mesh(object_names: str):
    """Choose the primary MESH datablock from a comma-separated name list.

    Mesh-only (no rigged hierarchies): skip empties/armatures; if several
    meshes, take the highest-poly one (the actual model, not a stray plane).
    """
    best = None
    best_polys = -1
    for name in (n.strip() for n in object_names.split(",")):
        if not name:
            continue
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH" or obj.data is None:
            continue
        polys = len(obj.data.polygons)
        if polys > best_polys:
            best, best_polys = obj, polys
    return best


def _save_job(job) -> None:
    """Archive one succeeded generation's mesh into the Mixar library."""
    global _batch_dirty
    try:
        mesh = _pick_mesh(job.imported_object_names or "")
        if mesh is None:
            logger.warning(
                "[GenLibrary] No mesh to archive for job %s (%s)",
                job.id[:8], job.imported_object_names,
            )
            return

        label = (getattr(job, "label", "") or "Generation").strip()
        # Unique, meaningful searchable name so repeat labels don't collide in
        # the embedding index (identity = name/library/blend_file).
        asset_name = f"{label} {job.id[:6]}"

        from mixar.modules.moodboard.core.scene_asset_exporter import (
            export_object_to_asset_library,
        )
        ok = export_object_to_asset_library(
            mesh,
            label,
            get_library_path(),
            asset_name=asset_name,
            description=label,
            tags=["generation"],
        )
        if ok:
            _batch_dirty = True
            logger.info("[GenLibrary] Archived generation '%s'", asset_name)
        else:
            logger.warning("[GenLibrary] Exporter declined job %s", job.id[:8])
    except Exception:
        logger.exception("[GenLibrary] Failed to archive generation")


def _all_qualifying_queues_idle() -> bool:
    """True when NO qualifying job is still active across ALL queues."""
    from mixar.modules.common.job_queue.core.job import TERMINAL_STATES
    from mixar.modules.common.job_queue.core.queue_manager import all_queues

    for queue in all_queues():
        for job in queue.snapshot():
            if _is_qualifying(job) and job.state not in TERMINAL_STATES:
                return False
    return True


def _schedule_retrain() -> None:
    """Fire ONE incremental retrain once the manual-train guard is free."""
    global _retrain_scheduled
    if _retrain_scheduled:
        return
    # Nothing enrolled → a train reports "No libraries selected" and paints a RED
    # failure banner in the asset panel after every unrelated generation. Skip
    # silently; the archived .blends stay on disk and get embedded whenever the
    # user next enrolls a library and trains.
    try:
        from mixar.modules.asset_search.core.library_enrollment import (
            enrolled_names,
        )
        if not enrolled_names():
            return
    except Exception:  # noqa: BLE001 — if we can't tell, fall through and train
        pass
    _retrain_scheduled = True

    state = {"ticks": 0}

    def _tick():
        global _retrain_scheduled, _batch_dirty
        # Poll-back path FIRST, OUTSIDE the try/finally: while a manual train is
        # running we return 2.0 to poll again, and the latch MUST stay set — the
        # timer is still pending. Clearing it here (the old `finally` ran on this
        # return too) released the guard mid-flight, so every queue change
        # registered ANOTHER _tick timer and several could fire the operator in
        # one frame.
        training = getattr(bpy.context.scene, "mixie_asset_training", None)
        if training is not None and getattr(training, "is_training", False):
            state["ticks"] += 1
            if state["ticks"] > _MAX_RETRAIN_WAIT_TICKS:
                _retrain_scheduled = False
                return None  # give up; next generation will retry
            return 2.0  # a train is running — poll back (latch stays SET)

        # Terminal from here: fire (or fail) once, then release the latch.
        try:
            win = bpy.context.window
            if win is None:
                wm = bpy.context.window_manager
                win = wm.windows[0] if wm and wm.windows else None
            if win is not None:
                with bpy.context.temp_override(window=win, screen=win.screen):
                    # auto=True, like auto_train.schedule_auto_train: a failed
                    # background retrain must not paint a red failure banner
                    # after every generation drain.
                    bpy.ops.mixie.train_asset_model(auto=True)
            else:
                bpy.ops.mixie.train_asset_model(auto=True)

            _batch_dirty = False
            logger.info("[GenLibrary] Incremental embedding retrain triggered")
        except Exception:
            logger.exception("[GenLibrary] Could not trigger retrain")
        finally:
            _retrain_scheduled = False
        return None  # one-shot

    bpy.app.timers.register(_tick, first_interval=1.0)
