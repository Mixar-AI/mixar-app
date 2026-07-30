# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Result download / import half of the job lifecycle.

Split out of ``queue_manager`` as a mixin so the download policy (total
deadline, ``Content-Length`` verification, bounded retries, prompt cancel,
progress reporting) has room to live somewhere readable. ``FeatureQueue``
inherits it; every method here is a ``FeatureQueue`` method and relies on
``self._notify`` / ``self._pump`` / ``self._jobs`` from that class.

Threading contract, which is the easiest thing to get wrong here:
``_bg_download`` is a daemon thread. Nothing it runs may touch ``bpy`` or
call ``self._notify()``. It writes plain byte counts onto the ``Job`` and a
main-thread ``bpy.app.timers`` tick turns those into UI updates.
"""

import os
import threading
import time

import bpy

from mixar.config.logging_config import get_logger

from ..constants import DOWNLOAD_PROGRESS_REFRESH_S, LOG_PREFIX
from .downloader import DownloadCancelled, download_file
from .error_helpers import classify_error
from .job import Job, JobState, TERMINAL_STATES
from .model_io import import_file

logger = get_logger(__name__)


class DownloadMixin:
    """``FeatureQueue`` methods covering RUNNING_DOWNLOAD through terminal."""

    def _finish_custom_success(self, job: Job, object_names=""):
        if job.state == JobState.CANCELLED:
            self._pump()
            return None
        job.imported_object_names = object_names
        job.state = JobState.SUCCESS
        self._notify()
        self._pump()
        return None

    def _begin_download(self, job: Job, result_files: list) -> None:
        # Hook: let the job handle non-standard results (images, textures, etc.)
        def _custom_done(names=""):
            return self._finish_custom_success(job, names)

        def _custom_error(msg):
            return self._finish_failed(job, msg)

        if job.handle_result(result_files, _custom_done, _custom_error):
            return  # Job takes responsibility

        # Pick best file (GLB > OBJ > FBX)
        preferred_order = ["GLB", "OBJ", "FBX"]
        chosen = None
        for pref in preferred_order:
            for rf in result_files or []:
                if rf.get("type", "").upper() == pref and rf.get("url"):
                    chosen = rf
                    break
            if chosen:
                break
        if not chosen and result_files:
            chosen = result_files[0]

        if not chosen or not chosen.get("url"):
            job.state = JobState.FAILED
            job.error = "No downloadable result file"
            job.user_message = "No result available — please retry"
            self._notify()
            self._pump()
            return

        file_type = chosen.get("type", "GLB").upper()
        url = chosen["url"]

        job.download_bytes = 0
        job.download_total_bytes = 0
        job.download_attempt = 0
        job.download_started_at = time.monotonic()

        # Deferred import: queue_manager imports this module at load time.
        from .queue_manager import _ensure_sync_watchdog

        # The watchdog is the backstop for a worker thread that dies without
        # registering either callback. Ensure it here too: a should_skip_poll
        # job reaches RUNNING_DOWNLOAD without ever passing through the poll
        # branch that normally starts it.
        _ensure_sync_watchdog()
        self._start_download_progress_timer(job)

        def _on_progress(transferred, total, attempt):
            # Runs on the download thread. Plain attribute writes ONLY —
            # bpy and self._notify() are main-thread-only. The queue UI picks
            # these up through _start_download_progress_timer below.
            job.download_bytes = transferred
            job.download_total_bytes = total
            job.download_attempt = attempt

        def _should_cancel():
            return job.state == JobState.CANCELLED

        def _bg_download():
            try:
                filepath = download_file(
                    url,
                    file_type,
                    on_progress=_on_progress,
                    should_cancel=_should_cancel,
                )
            except DownloadCancelled:
                # download_file already removed the temp file. Route through
                # the normal failure path, which no-ops on a CANCELLED job
                # and just pumps the queue.
                def _cancel_cb():
                    return self._finish_failed(job, "Download cancelled")

                bpy.app.timers.register(_cancel_cb, first_interval=0.0)
                return
            except Exception as e:
                logger.error(
                    "%s download failed for %s: %s", LOG_PREFIX, job.id, e
                )
                # Capture error message now — Python 3 deletes `e` when
                # the except block exits, so the closure can't reference it.
                err_msg = f"Download failed: {e}"
                friendly = (
                    getattr(e, "user_message", "")
                    or classify_error(e)
                    or "Download failed — please retry"
                )

                def _fail_cb():
                    return self._finish_failed(job, err_msg, friendly)

                bpy.app.timers.register(_fail_cb, first_interval=0.0)
                return

            def _import_cb():
                return self._finish_import(job, filepath, file_type)

            bpy.app.timers.register(_import_cb, first_interval=0.0)

        threading.Thread(target=_bg_download, daemon=True).start()

    def _start_download_progress_timer(self, job: Job) -> None:
        """Refresh the queue row while *job* downloads. Main thread only.

        The queue UIList reads ``substate_text`` off the WindowManager mirror,
        and that mirror is only rebuilt by ``_notify()`` — so byte counts
        written by the download thread are invisible until something on the
        main thread notifies. The blink pump redraws but does not re-sync, so
        it cannot serve this. Hence a timer: it is the main thread, so calling
        _notify() from it is safe, and it self-unregisters the moment the job
        leaves RUNNING_DOWNLOAD. Only notifies when the byte count actually
        moved, so a stalled transfer costs nothing.
        """
        last_seen = [-1]

        def _tick():
            if job.state != JobState.RUNNING_DOWNLOAD:
                return None  # terminal, cancelled, or import started
            if job.download_bytes != last_seen[0]:
                last_seen[0] = job.download_bytes
                self._notify()
            return DOWNLOAD_PROGRESS_REFRESH_S

        bpy.app.timers.register(
            _tick, first_interval=DOWNLOAD_PROGRESS_REFRESH_S,
        )

    def _finish_import(self, job: Job, filepath: str, file_type: str):
        # Cancelled, or already failed by the RUNNING_DOWNLOAD watchdog while
        # this thread was still running: drop the file, free the slot, and
        # never resurrect a job that has already reached a terminal state.
        if job.state != JobState.RUNNING_DOWNLOAD:
            try:
                os.remove(filepath)
            except OSError:
                pass
            self._pump()
            return None

        try:
            obj_names = import_file(
                filepath, file_type, getattr(job, "import_options", None),
            )
            job.on_imported(obj_names)
            job.state = JobState.SUCCESS
        except Exception as e:
            job.state = JobState.FAILED
            job.error = f"Import failed: {e}"
            job.user_message = "Failed to import the generated model"
            # Don't leave the downloaded temp file behind — repeated failed
            # imports would otherwise accumulate multi-MB files in tempdir.
            try:
                os.remove(filepath)
            except OSError:
                pass

        self._notify()
        self._pump()
        return None  # one-shot

    def _finish_failed(self, job: Job, message: str, user_message: str = ""):
        # Cancelled, or already failed by a watchdog — keep the first terminal
        # verdict (and its user-facing message) rather than overwriting it.
        if job.state in TERMINAL_STATES:
            self._pump()
            return None
        job.state = JobState.FAILED
        job.error = message
        if user_message:
            job.user_message = user_message
        self._notify()
        self._pump()
        return None  # one-shot

