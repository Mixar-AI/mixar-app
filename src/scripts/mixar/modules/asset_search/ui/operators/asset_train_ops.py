# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asset Training Operators — chunked/off-process training with live progress.

Phases: INIT -> SCANNING -> PREPARING -> (RENDERING | RENDER_WORKER) -> WAITING,
with UPLOADING inserted only when uploads cannot be streamed.

This module is the modal state machine and its lifecycle; the phases live
beside it — ``asset_train_render_phase`` (planning, in-process ticks,
completion/cancel), ``asset_train_worker_phase`` (the headless fan-out) and
``asset_train_upload_phase`` (streamed and barrier uploads). Small plans render
in-process, a few assets per timer tick (embedded-preview reuse makes most
instant); large plans render across HEADLESS WORKER processes
(core/preview_worker) so the app never freezes. Batches upload WHILE rendering
continues (core/train_stream). State PropertyGroups live in
ui/properties/training_props.py.
"""

import threading
import time

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.core import preview_worker
from mixar.modules.asset_search.core.train_api import prepare_api
from mixar.modules.asset_search.core.train_support import (
    W_RENDER_END,
    W_SCAN_END,
    fmt_duration,
)

logger = get_logger(__name__)


class MIXIE_OT_train_asset_model(Operator):
    """Render asset previews and send to training API"""

    bl_idname = "mixie.train_asset_model"
    bl_label = "Train Model"
    bl_description = (
        "Scan asset libraries, check for changes, render only new previews, "
        "and send to the training API"
    )
    bl_options = {"REGISTER"}

    _timer = None
    _phase = 'INIT'
    _bg_thread = None
    _bg_result = None
    _scan_metadata = None
    _train_mode = "full"
    _removed_assets = []
    _metadata_checksum = None
    _session = None              # in-process RenderSession
    _worker = None               # headless preview_worker handle
    # Directory holding this run's preview JPEGs. Previews are files, not
    # packed datablocks, so it must live until the upload has read them —
    # _finish owns its removal.
    _image_dir = None
    # Streaming upload (see core/train_stream): batches are posted WHILE the
    # remaining assets render, so the upload cost hides inside the render time.
    _stream = None
    _builder = None
    _collected = None            # finished assets, in arrival order
    _used_names = None           # image_name uniqueness across the whole run
    _stream_uploads = False      # safe to upload while rendering?
    _worker_failures = []
    _render_started_at = 0.0
    _started_at = 0.0
    # Upload progress fields written by the post_batches thread:
    _upload_done = 0
    _upload_total = 0
    _upload_embedded = 0

    # Set True by the auto-train scheduler (enrollment change / file load /
    # generation drain). Suppresses the "nothing to do" panel summary so a
    # background check that finds no changes leaves no banner behind.
    auto: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, 'mixie_asset_training', None)
        return not (state and state.is_training)

    def execute(self, context):
        state = context.scene.mixie_asset_training
        state.is_training = True
        state.progress = 0.0
        state.phase_text = "Starting…"
        state.current_item = ""
        state.assets_done = 0
        state.assets_total = 0
        state.upload_done = 0
        state.upload_total = 0
        state.eta_text = ""
        state.prepare_note = ""
        state.failed_count = 0
        state.failed_list = ""
        state.cancel_requested = False
        state.last_summary = ""

        self._phase = 'INIT'
        self._bg_thread = None
        self._bg_result = None
        self._scan_metadata = None
        self._train_mode = "full"
        self._removed_assets = []
        self._metadata_checksum = None
        self._session = None
        self._worker = None
        self._image_dir = None
        self._stream = None
        self._builder = None
        self._collected = []
        self._used_names = set()
        self._stream_uploads = False
        self._worker_failures = []
        self._started_at = time.time()
        self._upload_done = 0
        self._upload_total = 0
        self._upload_embedded = 0

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        state = context.scene.mixie_asset_training
        if event.type == 'ESC':
            state.cancel_requested = True
        if event.type != 'TIMER':
            return {"PASS_THROUGH"}

        if self._phase == 'INIT':
            state.phase_text = "Scanning libraries…"
            self._phase = 'SCANNING'
            self._redraw(context)
            return {"RUNNING_MODAL"}
        handler = getattr(self, f"_handle_{self._phase.lower()}", None)
        return handler(context, state) if handler else {"RUNNING_MODAL"}

    # ------------------------------------------------------------------ #
    # Scan + prepare
    # ------------------------------------------------------------------ #

    def _handle_scanning(self, context, state):
        from .asset_search_ops import _scan_asset_library_metadata

        self._scan_metadata = _scan_asset_library_metadata(context)
        if not self._scan_metadata and not self.auto:
            from mixar.modules.asset_search.core.library_enrollment import (
                enrolled_names,
            )
            if context.preferences.filepaths.asset_libraries and not enrolled_names():
                msg = ("No libraries selected — tick the libraries to train "
                       "in the list below, then train")
            else:
                msg = ("No asset library found — add one from "
                       "Edit > Preferences > File Paths")
            self._finish(context, success=False, message=msg)
            return {"CANCELLED"}
        # An AUTO train with an empty scan (e.g. the last enrolled library was
        # unenrolled) still proceeds to /train/prepare: the backend reports the
        # now-orphaned assets as removed and the removal path drops their
        # embeddings, so search stops returning them.

        state.progress = W_SCAN_END
        state.phase_text = (
            f"Checking what's new ({len(self._scan_metadata)} assets scanned)…"
        )
        self._bg_result = None
        self._bg_thread = threading.Thread(
            target=prepare_api, args=(self._scan_metadata, self), daemon=True,
        )
        self._bg_thread.start()
        self._phase = 'PREPARING'
        self._redraw(context)
        return {"RUNNING_MODAL"}

    def _handle_preparing(self, context, state):
        if self._bg_thread and self._bg_thread.is_alive():
            return {"RUNNING_MODAL"}

        res = self._bg_result or {}
        scanned = len(self._scan_metadata or [])
        if not res.get("success"):
            logger.warning("[Asset Training] Prepare failed: %s — full train",
                           res.get('message'))
            self._train_mode = "full"
            self._removed_assets = []
            # Prepare failed, so we do NOT know whether the user already has an
            # index. A streamed mode="full" first batch would REPLACE it before
            # the run can be cancelled, so this path keeps the old barrier:
            # render everything, then upload.
            self._stream_uploads = False
            state.prepare_note = f"{scanned} assets — full training"
            return self._start_rendering(context, state, filter_assets=None)

        action = res.get("action", "full_train")
        self._metadata_checksum = res.get("metadata_checksum")
        # Safe to upload while rendering: an incremental run is durable
        # server-side (that is already the cancel contract), and "full_train"
        # is the server telling us there is no existing index to lose.
        self._stream_uploads = action in ("incremental", "full_train")

        if action == "skip":
            state.needs_retraining = False
            state.retraining_message = ""
            self._finish(context, success=True, silent=self.auto,
                         message="Embeddings are up to date — nothing to do")
            return {"FINISHED"}

        if action == "incremental":
            new_assets = res.get("new_assets", [])
            self._removed_assets = res.get("removed_assets", [])
            self._train_mode = "incremental"
            unchanged = res.get("unchanged_count", scanned - len(new_assets))
            state.prepare_note = (
                f"{scanned} scanned · {unchanged} already embedded · "
                f"{len(new_assets)} new · {len(self._removed_assets)} removed"
            )
            if not new_assets and not self._removed_assets:
                self._finish(context, success=True,
                             message="Embeddings are up to date — nothing to do")
                return {"FINISHED"}
            if not new_assets:
                state.progress = W_RENDER_END
                state.phase_text = "Removing deleted assets…"
                self._phase = 'UPLOADING'
                self._redraw(context)
                return {"RUNNING_MODAL"}
            return self._start_rendering(context, state, filter_assets=new_assets)

        self._train_mode = "full"
        self._removed_assets = []
        state.prepare_note = f"{scanned} assets — full training"
        return self._start_rendering(context, state, filter_assets=None)

    # ------------------------------------------------------------------ #
    # Rendering — headless worker for large plans, in-process for small
    # ------------------------------------------------------------------ #

    def _start_rendering(self, context, state, filter_assets):
        from .asset_train_render_phase import start_rendering
        return start_rendering(self, context, state, filter_assets)

    def _start_inprocess_session(self, context, state, items):
        from .asset_train_render_phase import start_inprocess_session
        return start_inprocess_session(self, context, state, items)

    def _update_render_progress(self, state, done, total, current):
        from .asset_train_render_phase import update_progress
        update_progress(self, state, done, total, current)

    def _handle_rendering(self, context, state):
        from .asset_train_render_phase import handle_rendering
        return handle_rendering(self, context, state)

    def _handle_render_worker(self, context, state):
        from .asset_train_worker_phase import handle_render_worker
        return handle_render_worker(self, context, state)

    def _renders_complete(self, context, state, collected, failures, reused=0):
        from .asset_train_render_phase import complete
        return complete(self, context, state, collected, failures, reused=reused)

    def _cancel_render(self, context, state, collected, teardown=None):
        from .asset_train_render_phase import cancel
        return cancel(self, context, state, collected, teardown=teardown)

    # ------------------------------------------------------------------ #
    # Upload — thin delegates; the phase logic lives in the upload module
    # ------------------------------------------------------------------ #

    def _start_upload_stream(self):
        from .asset_train_upload_phase import start_stream
        start_stream(self)

    def _feed_collected(self, infos):
        from .asset_train_upload_phase import feed
        feed(self, infos)

    def _upload_note(self):
        from .asset_train_upload_phase import note
        return note(self)

    def _stop_upload_stream(self, drop=False):
        from .asset_train_upload_phase import stop_stream
        stop_stream(self, drop=drop)

    def _handle_uploading(self, context, state):
        from .asset_train_upload_phase import handle_uploading
        return handle_uploading(self, context, state)

    def _handle_waiting(self, context, state):
        from .asset_train_upload_phase import handle_waiting
        return handle_waiting(self, context, state)

    # ------------------------------------------------------------------ #
    # Teardown
    # ------------------------------------------------------------------ #

    def _finish(self, context, success, message, silent=False):
        from .asset_inspect_ops import clear_render_filter

        if self._session is not None:
            try:
                self._session.finish()
            except Exception:
                pass
            self._session = None
        if self._worker is not None:
            preview_worker.stop(self._worker)
            preview_worker.cleanup(self._worker)
            self._worker = None
        # An uploader thread still reading previews must not race the rmtree
        # below. WAITING only finishes once the thread is dead; the error and
        # stall paths land here with it alive, so drop and wait it out.
        self._stop_upload_stream(drop=True)
        self._stream = None
        if self._bg_thread is not None and self._bg_thread.is_alive():
            self._bg_thread.join(timeout=5.0)
        # The run is over either way — the preview JPEGs have been uploaded,
        # discarded, or abandoned, so the directory goes with it.
        if self._image_dir:
            preview_worker.cleanup(self._image_dir)
            self._image_dir = None
        clear_render_filter()

        state = context.scene.mixie_asset_training
        state.is_training = False
        state.phase_text = ""
        state.current_item = ""
        state.eta_text = ""
        state.cancel_requested = False
        if not success:
            state.progress = 0.0

        # A silent finish (auto-train that found nothing to do) leaves no panel
        # banner — a background check must not spam the UI. Real training still
        # reports its summary even under auto.
        if not silent:
            elapsed = fmt_duration(time.time() - self._started_at)
            skipped = f", {state.failed_count} skipped" if state.failed_count else ""
            state.last_summary = f"{message}{skipped} — {elapsed}"
            state.last_summary_success = success
            if success:
                state.last_trained_at = time.strftime("%d %b %H:%M")

        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
            self._timer = None
        self._bg_thread = None
        self._bg_result = None
        self._scan_metadata = None
        self._removed_assets = []
        self._metadata_checksum = None

        # A completed train changed the indexed libraries — drop the Library
        # chat-mode browse cache so its next search re-scans and reflects the
        # new/removed assets (fixes "search still shows the old library").
        if success:
            try:
                from mixar.modules.space_mixie_chat.core import library_browse
                library_browse.invalidate()
            except Exception:
                pass

        if not silent:
            self.report({"INFO" if success else "WARNING"}, message)
        logger.debug("[Asset Training] %s%s", message, " (auto)" if silent else "")
        self._redraw(context)

    def _redraw(self, context):
        for area in context.screen.areas:
            if area.type == 'FILE_BROWSER':
                area.tag_redraw()


class MIXIE_OT_cancel_asset_training(Operator):
    """Cancel the running training after the current asset finishes"""

    bl_idname = "mixie.cancel_asset_training"
    bl_label = "Cancel Training"
    bl_description = (
        "Stop training after the current asset. Incremental runs keep the "
        "already-embedded assets; a full run is discarded unchanged"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, 'mixie_asset_training', None)
        return bool(state and state.is_training and not state.cancel_requested)

    def execute(self, context):
        context.scene.mixie_asset_training.cancel_requested = True
        return {"FINISHED"}


classes = (
    MIXIE_OT_train_asset_model,
    MIXIE_OT_cancel_asset_training,
)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
