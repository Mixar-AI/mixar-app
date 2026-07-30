# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asset Training Operators — chunked modal training with real-time progress.

Phases: INIT -> SCANNING -> PREPARING -> RENDERING -> UPLOADING -> WAITING.
Rendering is CHUNKED (a few assets per timer tick via core/render_session) and
uploads are BATCHED (core/train_api), so the panel shows a true fraction,
"N / M" counters, the current asset, per-batch upload progress, an ETA, and
every skipped asset — instead of a bar frozen at hardcoded checkpoints.
"""

import threading
import time

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, PropertyGroup

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.core.train_api import (
    build_upload_batches,
    post_batches,
    prepare_api,
)

logger = get_logger(__name__)

# Assets rendered per modal tick. 1 keeps the UI most responsive; 2 halves
# timer overhead at ~2x the per-tick stall. Renders are ~0.3-1s each, so 1.
RENDER_CHUNK = 1

# Progress-bar weighting per phase (render dominates wall time).
_W_SCAN_END = 0.05
_W_PREPARE_END = 0.08
_W_RENDER_END = 0.80


class MixieAssetSearchResult(PropertyGroup):
    """One structured search hit (name/score/library) for the results list."""

    name: StringProperty(name="Asset Name", default="")
    score: FloatProperty(name="Similarity", default=0.0, min=0.0, max=1.0)
    library: StringProperty(name="Library", default="")
    blend_file: StringProperty(name="Blend File", default="")
    asset_type: StringProperty(name="Type", default="")


class MixieAssetTrainingState(PropertyGroup):
    """Scene-level properties tracking asset training progress."""

    is_training: BoolProperty(name="Is Training", default=False)
    progress: FloatProperty(
        name="Training Progress", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
    )
    # -- Real-time progress detail (all display-only, written by the modal) --
    phase_text: StringProperty(name="Phase", default="")
    current_item: StringProperty(name="Current Item", default="")
    assets_done: IntProperty(name="Assets Done", default=0)
    assets_total: IntProperty(name="Assets Total", default=0)
    upload_done: IntProperty(name="Batches Uploaded", default=0)
    upload_total: IntProperty(name="Upload Batches", default=0)
    eta_text: StringProperty(name="ETA", default="")
    prepare_note: StringProperty(name="Prepare Summary", default="")
    failed_count: IntProperty(name="Failed Count", default=0)
    failed_list: StringProperty(name="Failed Assets", default="")
    show_failures: BoolProperty(
        name="Show Skipped",
        description="List the assets that could not be rendered/embedded",
        default=False,
    )
    cancel_requested: BoolProperty(name="Cancel Requested", default=False)
    # -- Persistent terminal summary (survives until the next run) --
    last_summary: StringProperty(name="Last Run Summary", default="")
    last_summary_success: BoolProperty(name="Last Run OK", default=True)

    # Client-side stamp of the last successful training (idle status block).
    last_trained_at: StringProperty(name="Last Trained", default="")

    search_prompt: StringProperty(name="Search", default="")
    search_results: CollectionProperty(type=MixieAssetSearchResult)
    needs_retraining: BoolProperty(name="Needs Retraining", default=False)
    retraining_message: StringProperty(name="Retraining Message", default="")
    search_message: StringProperty(name="Search Message", default="")
    is_searching: BoolProperty(name="Is Searching", default=False)
    is_refreshing: BoolProperty(name="Is Refreshing", default=False)
    has_model: BoolProperty(name="Has Trained Model", default=False)
    auto_check_done: BoolProperty(name="Auto Check Done", default=False)
    search_image: PointerProperty(type=bpy.types.Image, name="Search Image")
    match_threshold: FloatProperty(
        name="Match Threshold",
        description=(
            "Similarity cutoff (0-1) the modelling agent uses to reuse an asset "
            "from your library instead of modelling it from scratch. Higher = only "
            "very close matches are reused"
        ),
        default=0.7, min=0.0, max=1.0, subtype='FACTOR',
    )


def _set_failures(state, failures):
    """Publish (label, reason) pairs to the panel (capped, readable)."""
    state.failed_count = len(failures)
    lines = [f"{label} — {reason}" for label, reason in failures[:10]]
    if len(failures) > 10:
        lines.append(f"…and {len(failures) - 10} more (see console)")
    state.failed_list = "\n".join(lines)


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
    _session = None            # core.render_session.RenderSession
    _render_started_at = 0.0
    _started_at = 0.0
    # Upload progress fields written by the post_batches thread:
    _upload_done = 0
    _upload_total = 0
    _upload_embedded = 0

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, 'mixie_asset_training', None)
        if state and state.is_training:
            return False
        return True

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
        if self._phase == 'SCANNING':
            return self._handle_scanning(context, state)
        if self._phase == 'PREPARING':
            return self._handle_preparing(context, state)
        if self._phase == 'RENDERING':
            return self._handle_rendering(context, state)
        if self._phase == 'UPLOADING':
            return self._handle_uploading(context, state)
        if self._phase == 'WAITING':
            return self._handle_waiting(context, state)
        return {"RUNNING_MODAL"}

    # ------------------------------------------------------------------ #
    # Phases
    # ------------------------------------------------------------------ #

    def _handle_scanning(self, context, state):
        from .asset_search_ops import _scan_asset_library_metadata

        self._scan_metadata = _scan_asset_library_metadata(context)
        if not self._scan_metadata:
            self._finish(context, success=False,
                         message="No asset library found — add one "
                                 "from Edit > Preferences > File Paths")
            return {"CANCELLED"}

        state.progress = _W_SCAN_END
        state.phase_text = (
            f"Checking what's new ({len(self._scan_metadata)} assets scanned)…"
        )
        logger.debug("[Asset Training] Scanned %d assets", len(self._scan_metadata))

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
            return self._start_render_session(context, state, filter_assets=None)

        action = res.get("action", "full_train")
        self._metadata_checksum = res.get("metadata_checksum")
        logger.debug("[Asset Training] Prepare result: action=%s", action)

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
            return self._start_render_session(context, state, filter_assets=new_assets)

        self._train_mode = "full"
        self._removed_assets = []
        state.prepare_note = f"{scanned} assets — full training"
        return self._start_render_session(context, state, filter_assets=None)

    def _start_render_session(self, context, state, filter_assets):
        from mixar.modules.asset_search.core.render_session import (
            RenderSession, build_render_plan,
        )
        from .asset_inspect_ops import clear_render_filter, set_render_filter

        if filter_assets is not None:
            set_render_filter(filter_assets)
        else:
            clear_render_filter()
        from .asset_inspect_ops import get_render_filter

        items, discovery_failures = build_render_plan(context, get_render_filter())
        if not items and self._train_mode == "full":
            self._finish(context, success=False,
                         message="No objects or collections found in asset libraries")
            return {"CANCELLED"}

        self._session = RenderSession(context, items)
        self._session.failures.extend(discovery_failures)
        self._session.start()
        self._render_started_at = time.time()

        state.assets_total = len(items)
        state.assets_done = 0
        state.progress = _W_PREPARE_END
        state.phase_text = f"Rendering previews 0/{len(items)}"
        self._phase = 'RENDERING'
        self._redraw(context)
        return {"RUNNING_MODAL"}

    def _handle_rendering(self, context, state):
        session = self._session

        if state.cancel_requested and not session.done:
            return self._handle_cancel_during_render(context, state)

        if not session.done:
            session.step(RENDER_CHUNK)
            done, total = session.index, session.total
            state.assets_done = done
            state.assets_total = total
            state.current_item = session.current_label
            _set_failures(state, session.failures)
            frac = done / total if total else 1.0
            state.progress = _W_PREPARE_END + (_W_RENDER_END - _W_PREPARE_END) * frac
            state.phase_text = f"Rendering previews {done}/{total}"
            elapsed = time.time() - self._render_started_at
            if done >= 3 and done < total:
                remaining = (elapsed / done) * (total - done)
                state.eta_text = f"~{_fmt_duration(remaining)} remaining"
            self._redraw(context)
            return {"RUNNING_MODAL"}

        # Session exhausted — tear down the rig, publish results, upload.
        session.finish()
        from .asset_inspect_ops import clear_render_filter, set_collected_asset_data
        set_collected_asset_data(session.collected)
        clear_render_filter()
        _set_failures(state, session.failures)
        state.current_item = ""
        state.eta_text = ""

        if not session.collected and self._train_mode == "full":
            self._finish(context, success=False,
                         message="No assets could be rendered")
            return {"CANCELLED"}

        state.progress = _W_RENDER_END
        self._phase = 'UPLOADING'
        self._redraw(context)
        return {"RUNNING_MODAL"}

    def _handle_cancel_during_render(self, context, state):
        """Stop rendering. Incremental keeps what's done (durable server-side);
        full discards — a partial mode="full" upload would REPLACE the whole
        index with a fragment."""
        session = self._session
        session.finish()
        from .asset_inspect_ops import clear_render_filter, set_collected_asset_data
        clear_render_filter()

        if self._train_mode == "incremental" and session.collected:
            set_collected_asset_data(session.collected)
            state.phase_text = (
                f"Cancelled — saving the {len(session.collected)} finished assets…"
            )
            state.progress = _W_RENDER_END
            self._phase = 'UPLOADING'
            self._redraw(context)
            return {"RUNNING_MODAL"}

        set_collected_asset_data([])
        self._finish(context, success=False,
                     message="Training cancelled — nothing was changed")
        return {"CANCELLED"}

    def _handle_uploading(self, context, state):
        from .asset_inspect_ops import get_collected_asset_data

        assets = get_collected_asset_data()
        files_by_image = {}
        for info in assets:
            img_name = info.get("image_name", "")
            img = bpy.data.images.get(img_name) if img_name else None
            if img is None:
                continue
            jpeg = _extract_image_bytes(img)
            if jpeg is not None:
                files_by_image[img_name] = jpeg

        batches = build_upload_batches(assets, files_by_image)
        if not batches and not self._removed_assets:
            if self._train_mode == "full":
                self._finish(context, success=False, message="No images to upload")
                return {"FINISHED"}

        state.upload_total = max(len(batches), 1)
        state.upload_done = 0
        state.phase_text = (
            f"Uploading & embedding — batch 0/{max(len(batches), 1)}"
        )

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
        # Live batch progress from the upload thread.
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
        clear_render_filter()

        state = context.scene.mixie_asset_training
        state.is_training = False
        state.phase_text = ""
        state.current_item = ""
        state.eta_text = ""
        state.cancel_requested = False
        if not success:
            state.progress = 0.0

        # Persistent terminal summary (A10): stays until the next run.
        elapsed = _fmt_duration(time.time() - self._started_at)
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

        report_type = "INFO" if success else "WARNING"
        self.report({report_type}, message)
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


def _fmt_duration(seconds):
    seconds = max(int(seconds), 0)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _extract_image_bytes(img):
    """Extract JPEG bytes from a Blender image."""
    if img.packed_file and img.packed_file.data:
        return bytes(img.packed_file.data)

    import os
    import tempfile

    from mixar.modules.asset_search.utils.preview_render import safe_temp_filename

    tmp_path = os.path.join(
        tempfile.gettempdir(), f"_mixar_tmp_{safe_temp_filename(img.name)}.jpg"
    )
    try:
        img.save_render(filepath=tmp_path)
        with open(tmp_path, "rb") as fh:
            return fh.read()
    except Exception as exc:
        logger.error("[Asset Training] Fallback save failed for %s: %s", img.name, exc)
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


classes = (
    MixieAssetSearchResult,
    MixieAssetTrainingState,
    MIXIE_OT_train_asset_model,
    MIXIE_OT_cancel_asset_training,
)


def register():
    """Register operator classes and scene properties"""
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    bpy.types.Scene.mixie_asset_training = bpy.props.PointerProperty(
        type=MixieAssetTrainingState,
    )


def unregister():
    """Unregister operator classes and scene properties"""
    from bpy.utils import unregister_class

    if hasattr(bpy.types.Scene, 'mixie_asset_training'):
        del bpy.types.Scene.mixie_asset_training

    for cls in reversed(classes):
        unregister_class(cls)
