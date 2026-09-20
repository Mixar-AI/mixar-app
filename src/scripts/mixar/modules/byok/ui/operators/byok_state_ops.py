# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK cached-state mirror + fetch operators.

Split out of byok_ops.py (500-line rule). Owns the WindowManager mirror
of the server's BYOK state (`byok_is_active`, `byok_current_*`,
`byok_key_preview`), the redraw nudge that makes async state flips
visible, and the non-interactive fetch operators the auth hooks fire on
login/refresh. The dialog and its save/remove flow live in byok_ops.py.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import byok_client, model_suggestions

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


def _clear_cached_state(wm):
    """Reset all cached BYOK display fields to defaults."""
    wm.byok_is_active = False
    wm.byok_current_provider = ''
    wm.byok_current_model = ''
    wm.byok_current_supports_vision = True
    wm.byok_key_preview = ''


def _apply_cached_state(wm, data):
    """Write the server's `data.items[0]` into the cached display fields.

    All 4 items are identical per the backend contract; just read index 0.
    """
    if not isinstance(data, dict):
        return
    wm.byok_is_active = bool(data.get('byok_active', False))
    items = data.get('items') or []
    if items and isinstance(items[0], dict):
        wm.byok_current_provider = items[0].get('provider', '') or ''
        wm.byok_current_model = items[0].get('model', '') or ''
        # Absent on older backends → default to vision-capable (no false note).
        wm.byok_current_supports_vision = bool(items[0].get('supports_vision', True))
        wm.byok_key_preview = items[0].get('key_preview', '') or ''


# ---------------------------------------------------------------------------
# Fetch BYOK state (called from auth hooks on login / refresh)
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_fetch_state(Operator):
    """Refresh cached BYOK state from the server (non-interactive)"""
    bl_idname = "mixar_byok.fetch_state"
    bl_label = "Refresh BYOK State"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        byok_client.fetch_state(on_done=_on_fetch_done)
        return {'FINISHED'}


def _on_fetch_done(success: bool, data, err):
    """Main-thread fetch callback.

    On failure, leave cached state at defaults (byok_is_active=False).
    The profile menu falls back to "inactive" which is the safe failure mode —
    subsequent agent calls use Mixar's system keys.
    """
    try:
        wm = bpy.context.window_manager
        if success:
            _apply_cached_state(wm, data or {})
            logger.debug(
                "BYOK state fetched: is_active=%s provider=%s model=%s",
                wm.byok_is_active, wm.byok_current_provider, wm.byok_current_model,
            )
        else:
            logger.debug("BYOK state fetch failed: %s", err)
            _clear_cached_state(wm)
        _redraw_mixie_chat_areas()
    except Exception as e:
        logger.error("BYOK fetch callback failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Fetch models catalog (called from auth hooks on login)
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_fetch_models_catalog(Operator):
    """Refresh the provider+model catalog from the backend"""
    bl_idname = "mixar_byok.fetch_models_catalog"
    bl_label = "Refresh Models Catalog"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        byok_client.fetch_models_catalog(on_done=_on_models_catalog_done)
        return {'FINISHED'}


def _on_models_catalog_done(success: bool, data, err):
    """Main-thread callback for the GET /agent/models fetch.

    Response shape (inner `data`):
      { "providers": [
          { "id": "anthropic", "label": "Anthropic",
            "models": [ {"id": "claude-sonnet-4-5", "label": "..."}, ... ] },
          ...
      ] }
    """
    try:
        if not success:
            logger.debug("Models catalog fetch failed: %s", err)
            return

        envelope = data or {}
        provider_entries = envelope.get('providers') or []

        providers: list[tuple[str, str, str]] = []
        models: dict[str, list[tuple[str, str, str]]] = {}
        for entry in provider_entries:
            if not isinstance(entry, dict):
                continue
            pid = entry.get('id')
            if not pid:
                continue
            label = entry.get('label') or pid
            # EnumProperty items need a 3-tuple (id, label, description).
            # The API doesn't provide a description — the label doubles
            # as the tooltip.
            providers.append((pid, label, label))

            model_entries = entry.get('models') or []
            model_items: list[tuple[str, str, str]] = []
            for m in model_entries:
                if not isinstance(m, dict):
                    continue
                mid = m.get('id')
                if not mid:
                    continue
                mlabel = m.get('label') or mid
                # EnumProperty items are (id, label, description); the
                # API gives us id + label, so label doubles as description.
                model_items.append((mid, mlabel, mlabel))
            models[pid] = model_items

        model_suggestions.populate(providers, models)
        logger.debug(
            "Models catalog populated: %d providers, %d model lists",
            len(providers), len(models),
        )
        _redraw_mixie_chat_areas()
    except Exception as e:
        logger.error("Models catalog callback failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Registration (picked up by bootstrap auto-discovery)
# ---------------------------------------------------------------------------

classes = (
    MIXAR_BYOK_OT_fetch_state,
    MIXAR_BYOK_OT_fetch_models_catalog,
)
