# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Hunyuan 3D -- Callback & Timer Functions

Module-level functions invoked asynchronously by the API infrastructure.
All functions use ``bpy.context`` instead of a captured operator context
because the operator's ``execute()`` returns ``{'FINISHED'}`` before
these callbacks fire, making the original context a dangling C pointer.

Functions:
- _on_submit_success: handle successful job submission
- _on_submit_error: handle job submission failure
- _start_poll_timer: register a Blender timer to poll job status
- _on_poll_result: process a single poll response
- _download_and_import_result: download and import the final result
"""

import json
import threading
import time

import bpy

from mixar.config.logging_config import get_logger

from ..constants import MAX_CONSECUTIVE_POLL_ERRORS, MAX_POLL_DURATION
from mixar.modules.moodboard.core.generate_progress import (
    start_progress, complete_progress, reset_progress,
)
from .hunyuan_helpers import (
    _redraw_3d_views,
    download_file,
    get_poll_interval,
    import_file,
)

logger = get_logger(__name__)

# Map Hunyuan mode to moodboard header progress prefix
_MODE_PROGRESS_PREFIX = {
    'PRO': 'image_to_3d',
    'RAPID': 'image_to_3d',
    'TOPOLOGY': 'retopology',
}


# ============================================================================
# SUBMIT CALLBACKS
# ============================================================================


def _on_submit_success(mode, response):
    """Called on main thread when submit succeeds."""
    props = bpy.context.scene.hunyuan
    mode_props = getattr(props, mode.lower())
    job = mode_props.job

    try:
        data = response.data
        if isinstance(data, dict):
            inner = data.get("data", data)
            job.job_id = inner.get("job_id", "")
            job.api_type = inner.get("api_type", "")

        job.status = 'POLLING'
        job.progress = 0.3
        job.progress_label = "Queued"
        job.poll_count = 0
        job.poll_start_time = time.time()
        _redraw_3d_views()

        _start_poll_timer(mode)
    except Exception as e:
        job.status = 'FAILED'
        job.error_message = f"Failed to parse submit response: {e}"
        job.progress = 0.0
        _redraw_3d_views()


def _on_submit_error(mode, error):
    """Called on main thread when submit fails."""
    props = bpy.context.scene.hunyuan
    mode_props = getattr(props, mode.lower())
    job = mode_props.job

    job.status = 'FAILED'
    job.error_message = str(error)
    job.progress = 0.0

    prefix = _MODE_PROGRESS_PREFIX.get(mode)
    if prefix:
        reset_progress(prefix)

    _redraw_3d_views()


# ============================================================================
# POLL TIMER
# ============================================================================


def _start_poll_timer(mode):
    """Register a timer that polls the job status with progressive intervals."""
    from mixar.modules.common.api import get_hunyuan_service

    service = get_hunyuan_service()

    # Track consecutive errors across ticks via a mutable container
    consecutive_errors = [0]

    def poll_tick():
        props = bpy.context.scene.hunyuan
        mode_props = getattr(props, mode.lower())
        job = mode_props.job

        # Stop if cancelled or finished
        if job.status != 'POLLING':
            return None  # unregister timer

        # Check timeout
        elapsed = time.time() - job.poll_start_time
        if elapsed > MAX_POLL_DURATION:
            job.status = 'FAILED'
            job.error_message = "Job timed out after 20 minutes"
            job.progress = 0.0
            prefix = _MODE_PROGRESS_PREFIX.get(mode)
            if prefix:
                reset_progress(prefix)
            _redraw_3d_views()
            return None

        job.poll_count += 1

        def on_poll_success(response):
            consecutive_errors[0] = 0
            _on_poll_result(mode, response)

        def on_poll_error(error):
            consecutive_errors[0] += 1
            logger.warning("Poll error for %s: %s", mode, error)
            # After too many consecutive errors, fail the job
            if consecutive_errors[0] >= MAX_CONSECUTIVE_POLL_ERRORS:
                props_inner = bpy.context.scene.hunyuan
                mode_props_inner = getattr(props_inner, mode.lower())
                job_inner = mode_props_inner.job
                job_inner.status = 'FAILED'
                job_inner.error_message = (
                    f"Job failed after {MAX_CONSECUTIVE_POLL_ERRORS} "
                    f"consecutive poll errors: {error}"
                )
                job_inner.progress = 0.0
                prefix = _MODE_PROGRESS_PREFIX.get(mode)
                if prefix:
                    reset_progress(prefix)
                _redraw_3d_views()

        service.poll_job_async(
            job.job_id,
            api_type=job.api_type,
            on_success=on_poll_success,
            on_error=on_poll_error,
        )

        return get_poll_interval(job.poll_count)

    # Start first poll after initial interval
    bpy.app.timers.register(poll_tick, first_interval=get_poll_interval(0))


# ============================================================================
# POLL RESULT HANDLER
# ============================================================================


def _on_poll_result(mode, response):
    """Handle poll response on main thread."""
    props = bpy.context.scene.hunyuan
    mode_props = getattr(props, mode.lower())
    job = mode_props.job

    if job.status != 'POLLING':
        return  # cancelled or already done

    try:
        data = response.data
        if isinstance(data, dict):
            inner = data.get("data", data)
            status = inner.get("status", "")

            if status == "WAIT":
                job.progress = 0.3
                job.progress_label = "Queued"
            elif status == "RUN":
                job.progress = 0.5
                job.progress_label = "Processing..."
            elif status == "DONE":
                job.status = 'DOWNLOADING'
                job.progress = 0.8
                job.progress_label = "Downloading..."
                job.result_files_json = json.dumps(
                    inner.get("result_files", []),
                )
                _redraw_3d_views()
                # Download and import result
                _download_and_import_result(
                    mode, inner.get("result_files", []),
                )
                return
            elif status == "FAIL":
                error_msg = (
                    inner.get("error_message", "")
                    or inner.get("error_code", "")
                    or "Job failed"
                )
                job.status = 'FAILED'
                job.error_message = error_msg
                job.progress = 0.0
                prefix = _MODE_PROGRESS_PREFIX.get(mode)
                if prefix:
                    reset_progress(prefix)
    except Exception as e:
        job.status = 'FAILED'
        job.error_message = f"Error parsing poll response: {e}"
        job.progress = 0.0
        prefix = _MODE_PROGRESS_PREFIX.get(mode)
        if prefix:
            reset_progress(prefix)

    _redraw_3d_views()


# ============================================================================
# DOWNLOAD & IMPORT
# ============================================================================


def _download_and_import_result(mode, result_files):
    """Download the result file on a background thread, then import on main.

    The download (network I/O) runs in a daemon thread so the Blender UI
    stays responsive. Once the file is on disk, a one-shot
    ``bpy.app.timers`` callback runs the import operators on the main
    thread (required by Blender's data API).
    """
    props = bpy.context.scene.hunyuan
    mode_props = getattr(props, mode.lower())
    job = mode_props.job

    # Pick first available file (prefer GLB > OBJ > FBX)
    preferred_order = ["GLB", "OBJ", "FBX"]
    chosen = None
    for pref in preferred_order:
        for rf in result_files:
            if rf.get("type", "").upper() == pref and rf.get("url"):
                chosen = rf
                break
        if chosen:
            break

    if not chosen and result_files:
        chosen = result_files[0]

    if not chosen or not chosen.get("url"):
        job.status = 'FAILED'
        job.error_message = "No downloadable result file"
        job.progress = 0.0
        _redraw_3d_views()
        return

    file_type = chosen.get("type", "GLB").upper()
    url = chosen["url"]

    def _bg_download():
        """Run on a background thread — download only, no bpy calls."""
        try:
            filepath = download_file(url, file_type)
        except Exception as e:
            logger.error("Download failed for %s: %s", mode, e)
            # Schedule failure update on main thread
            bpy.app.timers.register(
                lambda: _finish_failed(mode, f"Download failed: {e}"),
            )
            return

        # Schedule the import back on the main thread
        bpy.app.timers.register(
            lambda: _finish_import(mode, filepath, file_type),
        )

    thread = threading.Thread(target=_bg_download, daemon=True)
    thread.start()


def _finish_import(mode, filepath, file_type):
    """Timer callback — import the downloaded file on the main thread."""
    props = bpy.context.scene.hunyuan
    mode_props = getattr(props, mode.lower())
    job = mode_props.job

    # Mark job as DONE *before* import_file(), because the gltf importer
    # pushes its own undo step.  If we set status after import, undo would
    # revert to the mid-import state where status is still POLLING, causing
    # the sidebar loader to reappear.
    job.progress = 1.0
    job.progress_label = "Complete!"
    job.status = 'DONE'

    prefix = _MODE_PROGRESS_PREFIX.get(mode)
    if prefix:
        complete_progress(prefix)

    try:
        obj_names = import_file(filepath, file_type)
        job.imported_object_name = obj_names
    except Exception as e:
        job.status = 'FAILED'
        job.error_message = f"Import failed: {e}"
        job.progress = 0.0

        if prefix:
            reset_progress(prefix)

    _redraw_3d_views()
    return None  # one-shot timer


def _finish_failed(mode, message):
    """Timer callback — mark job as failed on the main thread."""
    props = bpy.context.scene.hunyuan
    mode_props = getattr(props, mode.lower())
    job = mode_props.job

    job.status = 'FAILED'
    job.error_message = message
    job.progress = 0.0

    prefix = _MODE_PROGRESS_PREFIX.get(mode)
    if prefix:
        reset_progress(prefix)

    _redraw_3d_views()
    return None  # one-shot timer
