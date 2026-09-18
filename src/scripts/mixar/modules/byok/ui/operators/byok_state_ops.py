# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK refresh operators + the WindowManager mirror helpers.

State and parsing live in `core/credential_state.py` (credentials) and
`core/models_cache.py` (the provider/model catalog); this module is the operator
surface the dialog, the auth hooks and QA drive, plus the redraw nudge that makes
async state flips visible.

The delegating helpers `_apply_cached_state` / `_clear_cached_state` /
`_on_fetch_done` keep their names: byok_ops imports all three, and the
non-destructive-failure contract is pinned against `_on_fetch_done` directly.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import credential_state, models_cache

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared WM-state helpers (also used by byok_ops)
# ---------------------------------------------------------------------------

def _redraw_mixie_chat_areas():
    """Force a redraw after a state change.

    Two consumers need to update:
    - The profile popover entry point in the top bar.
    - The BYOK dialog popup (rendered as a props dialog; its region
      picks up the next redraw tick but we nudge it by tagging every
      region, since the popup isn't a predictable area.type).
    """
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
                for region in area.regions:
                    region.tag_redraw()
    except Exception as e:
        logger.debug("BYOK area redraw failed: %s", e)


def _clear_cached_state(wm=None):
    """Reset the cached BYOK display state to defaults."""
    credential_state.clear(wm)


def _apply_cached_state(wm, data, epoch=None):
    """Adopt a server payload the caller already holds (e.g. a save's echo).

    Returns False when ``epoch`` is stale (a logout landed first) and the
    payload was dropped.
    """
    return credential_state.apply_from_payload(data, wm, epoch=epoch)


def _on_fetch_done(success: bool, data, err):
    """Main-thread fetch callback.

    A failure LEAVES the cached state alone rather than clearing it. Only the
    server can tell us a credential is gone, and it does that through the
    success path (``byok_active: false``). Clearing here would turn a transient
    miss into a session-long "Not configured" over a credential that is still
    stored and still being resolved on every turn.
    """
    try:
        if success:
            credential_state.apply_from_payload(data)
            snapshot = credential_state.snapshot()
            logger.debug(
                "BYOK state fetched: is_active=%s provider=%s model=%s",
                snapshot["byok_is_active"],
                snapshot["byok_current_provider"],
                snapshot["byok_current_model"],
            )
        else:
            logger.debug("BYOK state fetch failed (keeping cached state): %s", err)
        _redraw_mixie_chat_areas()
    except Exception as e:
        logger.error("BYOK fetch callback failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Fetch operators (auth hooks, the dialog and QA drive these)
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_fetch_state(Operator):
    """Refresh cached BYOK state from the server (non-interactive)"""
    bl_idname = "mixar_byok.fetch_state"
    bl_label = "Refresh BYOK State"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        credential_state.refresh()
        return {'FINISHED'}


class MIXAR_BYOK_OT_fetch_models_catalog(Operator):
    """Revalidate the provider+model catalog from the backend"""
    bl_idname = "mixar_byok.fetch_models_catalog"
    bl_label = "Refresh Models Catalog"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        models_cache.refresh()
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Registration (picked up by bootstrap auto-discovery)
# ---------------------------------------------------------------------------

classes = (
    MIXAR_BYOK_OT_fetch_state,
    MIXAR_BYOK_OT_fetch_models_catalog,
)
