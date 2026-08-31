# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Asset Search & Status Operators

Modal operators for searching indexed assets and checking whether
the training embeddings are stale.
"""

import json
import threading
from pathlib import Path

import bpy
from bpy.types import Operator

from mixar.config.config import get_server_url
from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.core.api_client import metered_client
from mixar.modules.common.api.client import HTTPClient

logger = get_logger(__name__)
from mixar.modules.asset_search.constants import (
    ASSET_SEARCH_ENDPOINT,
    ASSET_STATUS_ENDPOINT,
)


# ======================================================================
# Search Operator
# ======================================================================

class MIXIE_OT_search_assets(Operator):
    """Search indexed assets by text prompt or image"""

    bl_idname = "mixie.search_assets"
    bl_label = "Search Assets"
    bl_description = "Search the trained asset index using text and/or an image"
    bl_options = {"REGISTER"}

    _timer = None
    _phase = 'INIT'
    _thread = None
    _result = None
    _image_bytes = None  # extracted on main thread before background work

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, 'mixie_asset_training', None)
        if not state or state.is_searching:
            return False
        has_text = bool(state.search_prompt.strip())
        has_image = state.search_image is not None
        return has_text or has_image

    def execute(self, context):
        state = context.scene.mixie_asset_training
        state.search_message = ""
        state.is_searching = True
        self._phase = 'INIT'
        self._thread = None
        self._result = None
        self._image_bytes = None

        # Extract image bytes on main thread (bpy.data access required)
        if state.search_image is not None:
            self._image_bytes = _extract_search_image_bytes(state.search_image)

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {"PASS_THROUGH"}

        state = context.scene.mixie_asset_training

        if self._phase == 'INIT':
            prompt = state.search_prompt.strip()
            self._result = None
            self._thread = threading.Thread(
                target=_search_api,
                args=(prompt, self._image_bytes, self),
                daemon=True,
            )
            self._thread.start()
            self._phase = 'WAITING'
            return {"RUNNING_MODAL"}

        if self._phase == 'WAITING':
            if self._thread and self._thread.is_alive():
                return {"RUNNING_MODAL"}

            res = self._result or {}
            state.search_message = res.get("message", "Search failed")
            # Structured rows for the actionable results list (panel).
            state.search_results.clear()
            for hit in res.get("results", []):
                row = state.search_results.add()
                row.name = hit.get("name", "?")
                row.score = float(hit.get("score", 0.0))
                row.library = hit.get("library", "")
                row.blend_file = hit.get("blend_file", "")
                row.asset_type = hit.get("type", "")
            self._cleanup(context)

            report_type = "INFO" if res.get("success") else "WARNING"
            self.report({report_type}, state.search_message)
            return {"FINISHED"}

        return {"RUNNING_MODAL"}

    def _cleanup(self, context):
        state = context.scene.mixie_asset_training
        state.is_searching = False
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
            self._timer = None
        self._thread = None
        self._result = None
        self._image_bytes = None
        for area in context.screen.areas:
            if area.type == 'FILE_BROWSER':
                area.tag_redraw()


# ======================================================================
# Refresh Status Operator
# ======================================================================

class MIXIE_OT_refresh_asset_status(Operator):
    """Refresh asset library status to check if retraining is needed"""

    bl_idname = "mixie.refresh_asset_status"
    bl_label = "Refresh Asset Status"
    bl_description = (
        "Scan asset libraries and check the server to see if "
        "retraining is needed"
    )
    bl_options = {"REGISTER"}

    _timer = None
    _phase = 'INIT'
    _thread = None
    _result = None
    _metadata = None

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, 'mixie_asset_training', None)
        if not state or state.is_refreshing or state.is_training:
            return False
        return True

    def execute(self, context):
        state = context.scene.mixie_asset_training
        state.is_refreshing = True
        self._phase = 'INIT'
        self._thread = None
        self._result = None
        self._metadata = None

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {"PASS_THROUGH"}

        state = context.scene.mixie_asset_training

        if self._phase == 'INIT':
            self._phase = 'SCANNING'
            return {"RUNNING_MODAL"}

        if self._phase == 'SCANNING':
            self._metadata = _scan_asset_library_metadata(context)
            self._result = None
            self._thread = threading.Thread(
                target=_status_api,
                args=(self._metadata, self),
                daemon=True,
            )
            self._thread.start()
            self._phase = 'WAITING'
            return {"RUNNING_MODAL"}

        if self._phase == 'WAITING':
            if self._thread and self._thread.is_alive():
                return {"RUNNING_MODAL"}

            res = self._result or {}
            if res.get("success"):
                state.needs_retraining = res.get("needs_retraining", False)
                state.retraining_message = res.get("message", "")
            else:
                state.needs_retraining = True
                state.retraining_message = res.get(
                    "message", "Could not check status")

            self._cleanup(context)
            report_type = "INFO" if not state.needs_retraining else "WARNING"
            msg = state.retraining_message or "Embeddings are up to date"
            self.report({report_type}, msg)
            return {"FINISHED"}

        return {"RUNNING_MODAL"}

    def _cleanup(self, context):
        state = context.scene.mixie_asset_training
        state.is_refreshing = False
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
            self._timer = None
        self._thread = None
        self._result = None
        self._metadata = None
        for area in context.screen.areas:
            if area.type == 'FILE_BROWSER':
                area.tag_redraw()


# ======================================================================
# Background-thread helpers (no bpy access)
# ======================================================================

def _extract_search_image_bytes(img):
    """Extract JPEG bytes from a Blender image for search queries.

    Must be called on the main thread (accesses bpy.data).
    """
    import os
    import tempfile

    # Try packed data first
    if img.packed_file and img.packed_file.data:
        return bytes(img.packed_file.data)

    # Fall back to saving a render to a temp file
    tmp_path = os.path.join(
        tempfile.gettempdir(), f"_mixar_search_{img.name}.jpg",
    )
    try:
        img.save_render(filepath=tmp_path)
        with open(tmp_path, "rb") as fh:
            return fh.read()
    except Exception as exc:
        logger.error("[Asset Search] Could not extract image bytes: %s", exc)
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _search_api(prompt, image_bytes, operator):
    """POST a search query to the backend proxy in a background thread."""
    try:
        # Credit-metered per call — never auto-retried (see core/api_client).
        client = metered_client()
        form_data = {"prompt": prompt or ""}
        files = None
        if image_bytes:
            files = {"image": ("search_query.jpg", image_bytes, "image/jpeg")}

        resp = client.post(
            ASSET_SEARCH_ENDPOINT,
            data=form_data,
            files=files,
            timeout=30,
            raise_for_status=False,
        )

        if resp.status_code == 404:
            operator._result = {
                "success": False,
                "message": "No trained model found. Please train first.",
            }
            return

        if not resp.success:
            msg = resp.message or f"Server returned {resp.status_code}"
            operator._result = {"success": False, "message": msg}
            return

        data = resp.data or {}
        # Backend wraps: {status, message, data: {results: [...]}}
        inner = data.get("data", data)
        results = inner.get("results", [])
        if not results:
            operator._result = {
                "success": True,
                "message": "No matching assets found",
                "results": [],
            }
            return

        # Structured rows: the panel renders these with score bars and a
        # "locate in browser" action, not raw text.
        rows = []
        for r in results:
            meta = r.get("metadata", {}) or {}
            rows.append({
                "name": meta.get("name") or r.get("model_name", "?"),
                "score": float(r.get("similarity_score", 0) or 0),
                "library": meta.get("library", ""),
                "blend_file": meta.get("blend_file", ""),
                "type": meta.get("type", ""),
            })
        operator._result = {
            "success": True,
            "message": f"Found {len(rows)} matching asset(s)",
            "results": rows,
        }
    except Exception as exc:
        operator._result = {
            "success": False,
            "message": f"Search failed: {exc}",
        }


def _status_api(metadata, operator):
    """POST metadata to the backend status proxy in a background thread."""
    try:
        client = HTTPClient(base_url=get_server_url())
        resp = client.post(
            ASSET_STATUS_ENDPOINT,
            data={"metadata": json.dumps(metadata)},
            timeout=30,
            raise_for_status=False,
        )

        if resp.status_code == 404:
            operator._result = {
                "success": True,
                "needs_retraining": True,
                "message": "No trained model found. Please train first.",
            }
            return

        if not resp.success:
            msg = resp.message or f"Server returned {resp.status_code}"
            operator._result = {"success": False, "message": msg}
            return

        data = resp.data or {}
        inner = data.get("data", data)
        operator._result = {
            "success": True,
            "needs_retraining": inner.get("needs_retraining", False),
            "message": inner.get("message", ""),
        }
    except Exception as exc:
        operator._result = {
            "success": False,
            "message": f"Status check failed: {exc}",
        }


def _scan_asset_library_metadata(context):
    """Scan ENROLLED asset libraries for names/metadata without rendering."""
    from mixar.modules.asset_search.core.library_enrollment import enrolled_libraries

    metadata = []
    for lib in enrolled_libraries(context):
        library_path = Path(lib.path)
        if not library_path.exists():
            continue
        for blend_file in library_path.glob("**/*.blend"):
            rel_path = blend_file.relative_to(library_path)
            try:
                with bpy.data.libraries.load(
                    str(blend_file), assets_only=True
                ) as (data_from, _):
                    for name in data_from.objects:
                        metadata.append({
                            "name": name,
                            "library": lib.name,
                            "blend_file": str(rel_path),
                        })
                    for name in data_from.collections:
                        metadata.append({
                            "name": name,
                            "library": lib.name,
                            "blend_file": str(rel_path),
                        })
            except Exception:
                continue
    return metadata


# ======================================================================
# Auto-check at startup
# ======================================================================

_auto_check_thread = None
_auto_check_result = None


def _auto_check_status():
    """Background thread: GET /api/v1/asset-search/status via backend."""
    from mixar.modules.auth.core.auth import get_access_token

    global _auto_check_result
    try:
        # Skip if user is not logged in (no auth token available)
        token = get_access_token()
        if not token:
            logger.debug("[Asset Search] Skipping auto-check: not logged in")
            _auto_check_result = {"success": False}
            return

        client = HTTPClient(base_url=get_server_url())
        resp = client.get(
            ASSET_STATUS_ENDPOINT,
            timeout=5,
            raise_for_status=False,
        )

        if not resp.success:
            _auto_check_result = {"success": False}
            return

        data = resp.data or {}
        inner = data.get("data", data)
        _auto_check_result = {
            "success": True,
            "has_embeddings": inner.get("has_embeddings", False),
            "stored_asset_count": inner.get("stored_asset_count", 0),
        }
    except Exception:
        _auto_check_result = {"success": False}


def _auto_check_poll():
    """Timer: poll thread completion, apply results to scene state."""
    global _auto_check_thread, _auto_check_result

    if _auto_check_thread and _auto_check_thread.is_alive():
        return 0.5  # keep polling

    state = getattr(bpy.context.scene, 'mixie_asset_training', None)
    if state is None:
        return None

    if _auto_check_result and _auto_check_result.get("success"):
        state.has_model = _auto_check_result["has_embeddings"]
        if not state.has_model:
            state.needs_retraining = True
            state.retraining_message = (
                "No trained model found. Please train first."
            )
    state.auto_check_done = True

    _auto_check_thread = None
    _auto_check_result = None

    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'FILE_BROWSER':
                area.tag_redraw()
    return None  # stop polling


def _start_auto_check():
    """Deferred startup: launch thread + register poll timer."""
    global _auto_check_thread

    state = getattr(bpy.context.scene, 'mixie_asset_training', None)
    if state and state.is_refreshing:
        return None

    if _auto_check_thread and _auto_check_thread.is_alive():
        return None

    _auto_check_thread = threading.Thread(
        target=_auto_check_status, daemon=True,
    )
    _auto_check_thread.start()
    bpy.app.timers.register(_auto_check_poll, first_interval=0.5)
    return None  # one-shot


def _start_generation_library():
    """Deferred startup: register the Mixar Generations library + attach the
    queue listener that archives generations and triggers incremental
    embedding when the generation queue drains. One-shot, non-fatal."""
    try:
        from mixar.modules.asset_search.core import generation_library
        generation_library.ensure_registered()
        # Self-heal stale/uncreated library folders so agent saves that default
        # to a missing directory don't fail with an opaque write error.
        generation_library.ensure_library_dirs()
        generation_library.attach_listeners()
    except Exception as exc:
        logger.warning("[Asset Search] Generation library init failed: %s", exc)
    return None  # one-shot


@bpy.app.handlers.persistent
def _auto_train_on_load(_dummy):
    """After a file loads, catch library changes made while the app was closed
    by scheduling a debounced auto-train (silent no-op if nothing changed)."""
    try:
        from mixar.modules.asset_search.core.auto_train import schedule_auto_train
        schedule_auto_train("file_load")
    except Exception:  # noqa: BLE001 — a load handler must never raise
        pass


classes = (
    MIXIE_OT_search_assets,
    MIXIE_OT_refresh_asset_status,
)


def register():
    """Register operator classes and auto-check timer"""
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)
    bpy.app.timers.register(
        _start_auto_check, first_interval=2.0, persistent=True,
    )
    # Register the Mixar Generations library + generation-archive listener.
    # Slightly after the auto-check so preferences/queues are settled.
    bpy.app.timers.register(
        _start_generation_library, first_interval=3.0, persistent=True,
    )
    # Auto-train on file open so a library altered while the app was closed is
    # re-embedded without a manual Train click.
    if _auto_train_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_auto_train_on_load)


def unregister():
    """Unregister operator classes and timers"""
    if _auto_train_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_auto_train_on_load)
    for fn in (_start_auto_check, _auto_check_poll, _start_generation_library):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)

    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
