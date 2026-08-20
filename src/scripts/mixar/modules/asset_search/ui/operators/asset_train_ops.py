# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asset Training Operators — modal with prepare/diff step for incremental training."""

import json
import threading

import bpy
from bpy.props import BoolProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import Operator, PropertyGroup

from mixar.config.config import get_server_url
from mixar.config.logging_config import get_logger
from mixar.modules.common.api.client import HTTPClient

logger = get_logger(__name__)
from mixar.modules.asset_search.constants import (
    ASSET_TRAIN_ENDPOINT,
    ASSET_TRAIN_PREPARE_ENDPOINT,
)


class MixieAssetTrainingState(PropertyGroup):
    """Scene-level properties tracking asset training progress."""

    is_training: BoolProperty(name="Is Training", default=False)
    progress: FloatProperty(
        name="Training Progress", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
    )
    search_prompt: StringProperty(name="Search", default="")
    needs_retraining: BoolProperty(name="Needs Retraining", default=False)
    retraining_message: StringProperty(name="Retraining Message", default="")
    search_message: StringProperty(name="Search Message", default="")
    is_searching: BoolProperty(name="Is Searching", default=False)
    is_refreshing: BoolProperty(name="Is Refreshing", default=False)
    has_model: BoolProperty(name="Has Trained Model", default=False)
    auto_check_done: BoolProperty(name="Auto Check Done", default=False)
    search_image: PointerProperty(type=bpy.types.Image, name="Search Image")


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
    # INIT -> SCANNING -> PREPARING -> RENDERING -> UPLOADING -> WAITING -> DONE
    _phase = 'INIT'
    _bg_thread = None
    _bg_result = None
    _scan_metadata = None
    _train_mode = "full"
    _removed_assets = []
    _metadata_checksum = None  # Full-library checksum from /train/prepare

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
        self._phase = 'INIT'
        self._bg_thread = None
        self._bg_result = None
        self._scan_metadata = None
        self._train_mode = "full"
        self._removed_assets = []
        self._metadata_checksum = None

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {"PASS_THROUGH"}

        state = context.scene.mixie_asset_training

        if self._phase == 'INIT':
            state.progress = 0.0
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

    def _handle_scanning(self, context, state):
        """Lightweight scan of asset libraries (no rendering)."""
        from .asset_search_ops import _scan_asset_library_metadata

        self._scan_metadata = _scan_asset_library_metadata(context)
        if not self._scan_metadata:
            self._finish(context, success=False,
                         message="No asset library found — add one "
                                 "from Edit > Preferences > File Paths")
            return {"CANCELLED"}

        state.progress = 0.1
        logger.debug("[Asset Training] Scanned %d assets", len(self._scan_metadata))

        # Launch prepare request in background
        self._bg_result = None
        self._bg_thread = threading.Thread(
            target=_prepare_api,
            args=(self._scan_metadata, self),
            daemon=True,
        )
        self._bg_thread.start()
        self._phase = 'PREPARING'
        self._redraw(context)
        return {"RUNNING_MODAL"}

    def _handle_preparing(self, context, state):
        """Wait for /train/prepare response, decide next action."""
        if self._bg_thread and self._bg_thread.is_alive():
            return {"RUNNING_MODAL"}

        res = self._bg_result or {}
        if not res.get("success"):
            # Prepare failed — fall back to full train
            logger.warning("[Asset Training] Prepare failed: %s, falling back to full train",
                          res.get('message'))
            self._train_mode = "full"
            self._removed_assets = []
            self._setup_rendering_phase(context, state, filter_assets=None)
            return {"RUNNING_MODAL"}

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

            if not new_assets and not self._removed_assets:
                self._finish(context, success=True,
                             message="Embeddings are up to date — nothing to do")
                return {"FINISHED"}

            if not new_assets:
                # Only removals — skip rendering, go straight to upload
                logger.debug("[Asset Training] Only removals (%d), skipping render",
                             len(self._removed_assets))
                state.progress = 0.5
                self._phase = 'UPLOADING'
                self._redraw(context)
                return {"RUNNING_MODAL"}

            self._setup_rendering_phase(context, state, filter_assets=new_assets)
            return {"RUNNING_MODAL"}

        # full_train or unknown action
        self._train_mode = "full"
        self._removed_assets = []
        self._setup_rendering_phase(context, state, filter_assets=None)
        return {"RUNNING_MODAL"}

    def _setup_rendering_phase(self, context, state, filter_assets):
        """Set render filter and advance to RENDERING phase."""
        from .asset_inspect_ops import clear_render_filter, set_render_filter

        if filter_assets is not None:
            set_render_filter(filter_assets)
            logger.debug("[Asset Training] Render filter set: %d assets", len(filter_assets))
        else:
            clear_render_filter()

        state.progress = 0.2
        self._phase = 'RENDERING'
        self._redraw(context)

    def _handle_rendering(self, context, state):
        """Run the inspect operator to render previews."""
        from .asset_inspect_ops import clear_render_filter, get_collected_asset_data

        result = bpy.ops.mixie.inspect_asset_libraries()
        clear_render_filter()

        if result != {"FINISHED"}:
            self._finish(context, success=False,
                         message="No asset library found — add one "
                                 "from Edit > Preferences > File Paths")
            return {"CANCELLED"}

        collected = get_collected_asset_data()
        if not collected and self._train_mode == "full":
            self._finish(context, success=False,
                         message="No objects or collections found "
                                 "in asset libraries")
            return {"CANCELLED"}

        state.progress = 0.5
        self._phase = 'UPLOADING'
        self._redraw(context)
        return {"RUNNING_MODAL"}

    def _handle_uploading(self, context, state):
        """Build payload and launch upload thread."""
        payload = self._prepare_payload()

        # For incremental with only removals, payload may be None but that's OK
        if payload is None and self._train_mode == "full":
            self._finish(context, success=False, message="No images to upload")
            return {"FINISHED"}

        self._bg_result = None
        self._bg_thread = threading.Thread(
            target=_post_to_api,
            args=(payload, self._train_mode, self._removed_assets,
                  self._metadata_checksum, self),
            daemon=True,
        )
        self._bg_thread.start()
        logger.debug("[Asset Training] Upload thread started (mode=%s)", self._train_mode)
        self._phase = 'WAITING'
        self._redraw(context)
        return {"RUNNING_MODAL"}

    def _handle_waiting(self, context, state):
        """Poll for upload thread completion."""
        if self._bg_thread and self._bg_thread.is_alive():
            return {"RUNNING_MODAL"}

        res = self._bg_result or {}
        success = res.get("success", False)
        state.progress = 1.0
        self._redraw(context)

        if success:
            state.needs_retraining = False
            state.retraining_message = ""

        msg = res.get("message", "API upload failed")
        self._finish(context, success=success, message=msg)
        return {"FINISHED"}

    def _prepare_payload(self):
        """Extract images + metadata on the main thread."""
        from .asset_inspect_ops import get_collected_asset_data

        assets = get_collected_asset_data()
        if not assets:
            logger.debug("[Asset Training] No asset data collected")
            return None

        logger.debug("[Asset Training] Collected %d assets, preparing...", len(assets))

        files = []
        for asset_info in assets:
            img_name = asset_info.get("image_name", "")
            if not img_name:
                continue
            img = bpy.data.images.get(img_name)
            if img is None:
                continue
            jpeg_bytes = _extract_image_bytes(img)
            if jpeg_bytes is None:
                continue
            files.append((f"{img_name}.jpg", jpeg_bytes))

        if not files:
            logger.warning("[Asset Training] No images could be extracted")
            return None

        return {
            "metadata_json": json.dumps(assets),
            "files": files,
        }

    def _finish(self, context, success, message):
        """Clean up timer and reset training state."""
        from .asset_inspect_ops import clear_render_filter

        clear_render_filter()

        state = context.scene.mixie_asset_training
        state.is_training = False
        if not success:
            state.progress = 0.0

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


def _prepare_api(metadata, operator):
    """POST metadata to /train/prepare in a background thread."""
    try:
        client = HTTPClient(base_url=get_server_url())
        resp = client.post(
            ASSET_TRAIN_PREPARE_ENDPOINT,
            data={"metadata": json.dumps(metadata)},
            timeout=30,
            raise_for_status=False,
        )

        if not resp.success:
            msg = resp.message or f"Server returned {resp.status_code}"
            operator._bg_result = {"success": False, "message": msg}
            return

        data = resp.data or {}
        inner = data.get("data", data)
        operator._bg_result = {
            "success": True,
            "action": inner.get("action", "full_train"),
            "new_assets": inner.get("new_assets", []),
            "removed_assets": inner.get("removed_assets", []),
            "asset_count": inner.get("asset_count", 0),
            "unchanged_count": inner.get("unchanged_count", 0),
            "metadata_checksum": inner.get("metadata_checksum"),
        }
    except Exception as exc:
        logger.error("[Asset Training] Prepare error: %s", exc)
        operator._bg_result = {
            "success": False,
            "message": f"Prepare failed: {exc}",
        }


def _post_to_api(payload, mode, removed_assets, metadata_checksum, operator):
    """POST images + metadata to the training API in a background thread."""
    files_list = []
    form_data = {
        "mode": mode,
        "removed_assets": json.dumps(removed_assets),
    }
    if metadata_checksum:
        form_data["metadata_checksum"] = metadata_checksum

    if payload:
        files_list = [
            ("images", (fname, data, "image/jpeg"))
            for fname, data in payload["files"]
        ]
        form_data["metadata"] = payload["metadata_json"]
        total_bytes = sum(len(d) for _, d in payload["files"])
        logger.debug("[Asset Training] Sending %d images (%d bytes) via backend proxy (mode=%s)",
                     len(files_list), total_bytes, mode)
    else:
        form_data["metadata"] = "[]"
        logger.debug("[Asset Training] Sending removal-only request (%d to remove)",
                     len(removed_assets))

    try:
        client = HTTPClient(base_url=get_server_url())
        resp = client.post(
            ASSET_TRAIN_ENDPOINT,
            data=form_data,
            files=files_list if files_list else None,
            timeout=300,
            raise_for_status=False,
        )

        if not resp.success:
            msg = resp.message or f"Server returned {resp.status_code}"
            logger.error("[Asset Training] Server error: %s", msg)
            operator._bg_result = {"success": False, "message": msg}
            return

        result = resp.data or {}
        inner = result.get("data", result)
        logger.debug("[Asset Training] Server response received")
        images_embedded = inner.get("images_embedded", 0)
        removed = inner.get("removed", 0)

        if mode == "incremental":
            total = inner.get("total", images_embedded)
            msg = (f"Incremental update — {images_embedded} added, "
                   f"{removed} removed, {total} total")
        else:
            msg = f"Training data sent — {images_embedded} images embedded"

        operator._bg_result = {
            "success": result.get("status") == "success",
            "message": msg,
        }
    except Exception as exc:
        logger.error("[Asset Training] Upload error: %s", exc)
        operator._bg_result = {
            "success": False,
            "message": f"Upload failed: {exc}",
        }


def _extract_image_bytes(img):
    """Extract JPEG bytes from a Blender image."""
    if img.packed_file and img.packed_file.data:
        return bytes(img.packed_file.data)

    import os
    import tempfile

    tmp_path = os.path.join(tempfile.gettempdir(), f"_mixar_tmp_{img.name}.jpg")
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
    MixieAssetTrainingState,
    MIXIE_OT_train_asset_model,
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
