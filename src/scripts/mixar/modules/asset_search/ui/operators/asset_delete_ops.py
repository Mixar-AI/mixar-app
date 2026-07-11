# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Asset Embeddings Delete Operator

Deletes ALL of the user's asset-search embeddings on the backend (the whole
library row; CASCADE removes every stored vector). Confirmation dialog first —
this is destructive and the next training run starts from scratch.
"""

import threading

import bpy
from bpy.types import Operator

from mixar.config.config import get_server_url
from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.constants import ASSET_EMBEDDINGS_DELETE_ENDPOINT
from mixar.modules.common.api.client import HTTPClient

logger = get_logger(__name__)


def _delete_api(operator):
    """DELETE the user's embeddings in a background thread (no bpy access)."""
    try:
        client = HTTPClient(base_url=get_server_url())
        resp = client.delete(
            ASSET_EMBEDDINGS_DELETE_ENDPOINT,
            timeout=30,
            raise_for_status=False,
        )
        if not resp.success:
            msg = resp.message or f"Server returned {resp.status_code}"
            operator._result = {"success": False, "message": msg}
            return
        data = resp.data or {}
        inner = data.get("data", data)
        deleted = bool(inner.get("deleted"))
        operator._result = {
            "success": True,
            "deleted": deleted,
            "message": (
                "All asset embeddings deleted — train again to re-enable search"
                if deleted else "No embeddings to delete"
            ),
        }
    except Exception as exc:
        logger.error("[Asset Delete] Request failed: %s", exc)
        operator._result = {"success": False, "message": f"Delete failed: {exc}"}


class MIXIE_OT_delete_asset_embeddings(Operator):
    """Delete ALL your asset-library embeddings from the server"""

    bl_idname = "mixie.delete_asset_embeddings"
    bl_label = "Delete All Embeddings?"
    bl_description = (
        "Delete every stored asset embedding for your account. "
        "Library search (and the agent's library reuse) stops working "
        "until you train again"
    )
    bl_options = {"REGISTER"}

    _timer = None
    _thread = None
    _result = None

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, 'mixie_asset_training', None)
        if not state or state.is_training or state.is_refreshing:
            return False
        return True

    def invoke(self, context, event):
        # Destructive: always confirm via the standard dialog.
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        state = context.scene.mixie_asset_training
        state.is_refreshing = True  # reuse the busy flag to grey out the panel
        self._result = None
        self._thread = threading.Thread(
            target=_delete_api, args=(self,), daemon=True,
        )
        self._thread.start()

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {"PASS_THROUGH"}
        if self._thread and self._thread.is_alive():
            return {"RUNNING_MODAL"}

        state = context.scene.mixie_asset_training
        res = self._result or {}
        if res.get("success"):
            state.has_model = False
            state.needs_retraining = False
            state.retraining_message = ""
            state.search_message = ""

        self._cleanup(context)
        report_type = "INFO" if res.get("success") else "WARNING"
        self.report({report_type}, res.get("message", "Delete failed"))
        return {"FINISHED"}

    def _cleanup(self, context):
        state = context.scene.mixie_asset_training
        state.is_refreshing = False
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
            self._timer = None
        self._thread = None
        self._result = None
        for area in context.screen.areas:
            if area.type == 'FILE_BROWSER':
                area.tag_redraw()


classes = (
    MIXIE_OT_delete_asset_embeddings,
)
