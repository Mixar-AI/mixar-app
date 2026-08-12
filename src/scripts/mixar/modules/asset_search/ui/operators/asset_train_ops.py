# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asset Training Operators — chunked/off-process training with live progress.

Phases: INIT -> SCANNING -> PREPARING -> (RENDERING | RENDER_WORKER)
        -> UPLOADING -> WAITING.

Small plans render in-process, a few assets per timer tick (embedded-preview
reuse makes most instant); large plans run in a HEADLESS WORKER process
(core/preview_worker) so the app never freezes — the modal polls its
results.jsonl for per-asset progress. Uploads are batched (core/train_api).
State PropertyGroups live in ui/properties/training_props.py.
"""

import threading
import time

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.core import preview_worker
from mixar.modules.asset_search.core.train_api import (
    build_upload_batches,
    post_batches,
    prepare_api,
)
from mixar.modules.asset_search.core.train_support import (
    extract_image_bytes,
    fmt_duration,
    set_failures,
)

logger = get_logger(__name__)

# Progress-bar weighting per phase (render dominates wall time).
_W_SCAN_END = 0.05
_W_PREPARE_END = 0.08
_W_RENDER_END = 0.80


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
    _worker_failures = []
    _render_started_at = 0.0
    _started_at = 0.0
    # Upload progress fields written by the post_batches thread:
    _upload_done = 0
    _upload_total = 0
    _upload_embedded = 0

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
        if not self._scan_metadata:
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

        state.progress = _W_SCAN_END
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
            state.prepare_note = f"{scanned} assets — full training"
            return self._start_rendering(context, state, filter_assets=None)

        action = res.get("action", "full_train")
        self._metadata_checksum = res.get("metadata_checksum")

        if action == "skip":
            state.needs_retraining = False
            state.retraining_message = ""
            self._finish(context, success=True,
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
                state.progress = _W_RENDER_END
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
        from mixar.modules.asset_search.core.render_session import build_render_plan
        from .asset_inspect_ops import clear_render_filter, get_render_filter, set_render_filter

        if filter_assets is not None:
            set_render_filter(filter_assets)
        else:
            clear_render_filter()

        items, discovery_failures = build_render_plan(context, get_render_filter())
        if not items and self._train_mode == "full":
            self._finish(context, success=False,
                         message="No objects or collections found in asset libraries")
            return {"CANCELLED"}

        state.assets_total = len(items)
        state.assets_done = 0
        state.progress = _W_PREPARE_END
        self._render_started_at = time.time()
        self._worker_failures = list(discovery_failures)

        if len(items) >= preview_worker.WORKER_MIN_ITEMS:
            self._worker = preview_worker.start_worker(items)
            if self._worker is not None:
                state.phase_text = (
                    f"Rendering previews in background 0/{len(items)} "
                    "(app stays responsive)"
                )
                self._phase = 'RENDER_WORKER'
                self._redraw(context)
                return {"RUNNING_MODAL"}
            logger.warning("[Asset Training] Worker unavailable — in-process render")

        return self._start_inprocess_session(context, state, items)

    def _start_inprocess_session(self, context, state, items):
        from mixar.modules.asset_search.core.render_session import RenderSession

        self._session = RenderSession(context, items)
        self._session.failures.extend(self._worker_failures)
        self._worker_failures = []
        self._session.start()
        state.phase_text = f"Rendering previews 0/{len(items)}"
        self._phase = 'RENDERING'
        self._redraw(context)
        return {"RUNNING_MODAL"}

    def _update_render_progress(self, state, done, total, current):
        state.assets_done = done
        state.assets_total = total
        state.current_item = current
        frac = done / total if total else 1.0
        state.progress = _W_PREPARE_END + (_W_RENDER_END - _W_PREPARE_END) * frac
        elapsed = time.time() - self._render_started_at
        if 3 <= done < total:
            state.eta_text = f"~{fmt_duration((elapsed / done) * (total - done))} remaining"

    def _handle_rendering(self, context, state):
        session = self._session
        if state.cancel_requested and not session.done:
            return self._cancel_render(context, state, session.collected,
                                       teardown=session.finish)
        if not session.done:
            session.step()
            self._update_render_progress(
                state, session.index, session.total, session.current_label)
            set_failures(state, session.failures)
            state.phase_text = f"Rendering previews {session.index}/{session.total}"
            self._redraw(context)
            return {"RUNNING_MODAL"}

        session.finish()
        # Rendered because no thumbnail existed -> write the render back as
        # the asset's thumbnail (fire-and-forget worker; never blocks).
        if session.rendered_items:
            from mixar.modules.asset_search.core.train_support import (
                launch_thumbnail_backfill,
            )
            launch_thumbnail_backfill(session.rendered_items)
        return self._renders_complete(context, state, session.collected,
                                      session.failures,
                                      reused=session.preview_reused)

    def _handle_render_worker(self, context, state):
        from .asset_train_worker_phase import handle_render_worker
        return handle_render_worker(self, context, state)

    def _renders_complete(self, context, state, collected, failures, reused=0):
        from .asset_inspect_ops import clear_render_filter, set_collected_asset_data

        set_collected_asset_data(collected)
        clear_render_filter()
        set_failures(state, failures)
        state.current_item = ""
        state.eta_text = ""
        # The full-library checksum marks the library FULLY embedded at this
        # content hash — the server then returns "skip" on the next train. Never
        # stamp it when assets are still un-embedded (any render/embed failure),
        # or those assets are marked trained and become unreachable until the
        # library's contents change. A clean run stamps it; a partial run leaves
        # it unstamped so the next train retries the remainder.
        if failures:
            self._metadata_checksum = None
        if reused:
            state.prepare_note = (
                (state.prepare_note + " · " if state.prepare_note else "")
                + f"{reused} thumbnails reused (not re-rendered)"
            )

        if not collected and self._train_mode == "full":
            self._finish(context, success=False,
                         message="No assets could be rendered")
            return {"CANCELLED"}
        state.progress = _W_RENDER_END
        self._phase = 'UPLOADING'
        self._redraw(context)
        return {"RUNNING_MODAL"}

    def _cancel_render(self, context, state, collected, teardown=None):
        """Incremental keeps finished work (durable server-side); full
        discards — a partial mode="full" upload would REPLACE the index."""
        from .asset_inspect_ops import clear_render_filter, set_collected_asset_data

        if teardown is not None:
            teardown()
        clear_render_filter()

        # A cancelled run is partial by definition: keep the finished assets
        # (incremental uploads are durable server-side) but NEVER stamp the
        # full-library checksum, or the un-rendered remainder is marked trained
        # and never retried.
        self._metadata_checksum = None

        if self._train_mode == "incremental" and collected:
            set_collected_asset_data(collected)
            state.phase_text = (
                f"Cancelled — saving the {len(collected)} finished assets…"
            )
            state.progress = _W_RENDER_END
            self._phase = 'UPLOADING'
            self._redraw(context)
            return {"RUNNING_MODAL"}

        set_collected_asset_data([])
        self._finish(context, success=False,
                     message="Training cancelled — nothing was changed")
        return {"CANCELLED"}

    # ------------------------------------------------------------------ #
    # Upload
    # ------------------------------------------------------------------ #

    def _handle_uploading(self, context, state):
        from .asset_inspect_ops import get_collected_asset_data

        assets = get_collected_asset_data()
        files_by_image = {}
        for info in assets:
            img_name = info.get("image_name", "")
            img = bpy.data.images.get(img_name) if img_name else None
            if img is None:
                continue
            jpeg = extract_image_bytes(img)
            if jpeg is not None:
                files_by_image[img_name] = jpeg

        batches = build_upload_batches(assets, files_by_image)
        if not batches and not self._removed_assets and self._train_mode == "full":
            self._finish(context, success=False, message="No images to upload")
            return {"FINISHED"}

        state.upload_total = max(len(batches), 1)
        state.upload_done = 0
        state.phase_text = f"Uploading & embedding — batch 0/{max(len(batches), 1)}"

        self._bg_result = None
        self._bg_thread = threading.Thread(
            target=post_batches,
            args=(batches, self._train_mode, self._removed_assets,
                  self._metadata_checksum, self),
            daemon=True,
        )
        self._bg_thread.start()
        self._phase = 'WAITING'
        self._redraw(context)
        return {"RUNNING_MODAL"}

    def _handle_waiting(self, context, state):
        done, total = self._upload_done, max(self._upload_total, 1)
        if done != state.upload_done or state.upload_total != total:
            state.upload_done = done
            state.upload_total = total
            state.phase_text = f"Uploading & embedding — batch {done}/{total}"
            state.progress = _W_RENDER_END + (1.0 - _W_RENDER_END) * (done / total)
            self._redraw(context)

        if self._bg_thread and self._bg_thread.is_alive():
            return {"RUNNING_MODAL"}

        res = self._bg_result or {}
        success = res.get("success", False)
        state.progress = 1.0
        if success:
            state.needs_retraining = False
            state.retraining_message = ""
        self._finish(context, success=success,
                     message=res.get("message", "API upload failed"))
        return {"FINISHED"}

    # ------------------------------------------------------------------ #
    # Teardown
    # ------------------------------------------------------------------ #

    def _finish(self, context, success, message):
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
        clear_render_filter()

        state = context.scene.mixie_asset_training
        state.is_training = False
        state.phase_text = ""
        state.current_item = ""
        state.eta_text = ""
        state.cancel_requested = False
        if not success:
            state.progress = 0.0

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

        self.report({"INFO" if success else "WARNING"}, message)
        logger.debug("[Asset Training] %s", message)
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
