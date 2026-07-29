# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK operators: dialog + save/remove/fetch actions.

State machine lives on WindowManager (see ui/properties/byok_props.py).
Save and Remove spawn async work through `core/byok_client.py`; callbacks
mutate WM state on the main thread and the props dialog redraws on the
next tick.

Everything the dialog puts on screen — including which state renders
what — lives in `ui/byok_dialog_drawer.py`; this module is control flow.
"""

import os

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import byok_client, model_suggestions
from ..byok_dialog_drawer import draw_dialog, save_blocker

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
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


def _wipe_form_secrets(wm):
    """Remove transient API/token material from the live WindowManager."""
    for attr in ('byok_form_api_key', 'byok_form_codex_bundle'):
        try:
            setattr(wm, attr, '')
        except Exception:
            pass


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
# Dialog entry point
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_open_dialog(Operator):
    """Configure your own API provider and key for the Mixar agent"""
    bl_idname = "mixar_byok.open_dialog"
    bl_label = "AI Provider Settings"
    bl_description = (
        "Use your own API key for the Mixar agent. "
        "While active, Mixar credits are not charged for agent requests."
    )

    def invoke(self, context, event):
        wm = context.window_manager
        # Reset dialog-local state on open. Never prefill the api_key field.
        wm.byok_dialog_state = 'IDLE'
        wm.byok_last_error = ''
        _wipe_form_secrets(wm)  # never prefill credential material
        # If we already have an active config, prefill provider/model so
        # the user sees what's currently saved and can edit from there.
        # Provider assignment can fail if the cache hasn't been populated
        # yet (the saved provider isn't in the current EnumProperty items)
        # — guard against TypeError.
        if wm.byok_is_active:
            if wm.byok_current_provider:
                try:
                    wm.byok_form_provider = wm.byok_current_provider
                except TypeError:
                    logger.debug(
                        "Could not prefill provider %s — not in cache yet",
                        wm.byok_current_provider,
                    )
            if model_suggestions.is_openrouter(wm.byok_current_provider):
                # OpenRouter uses a free-text model slug, not the catalog dropdown.
                if wm.byok_current_model:
                    wm.byok_form_openrouter_model = wm.byok_current_model
            elif model_suggestions.is_codex(wm.byok_current_provider):
                # Codex uses a free-text model slug, not the catalog dropdown.
                if wm.byok_current_model:
                    wm.byok_form_codex_model = wm.byok_current_model
            elif wm.byok_current_model:
                try:
                    wm.byok_form_model = wm.byok_current_model
                except TypeError:
                    logger.debug(
                        "Could not prefill model %s — not in cache for this provider",
                        wm.byok_current_model,
                    )
        # If the provider+model cache is empty, kick off a fetch so the
        # dropdown becomes populated by the time the user picks. (Belt-
        # and-suspenders — the auth login hook normally fires this already.)
        if not model_suggestions.is_loaded():
            byok_client.fetch_models_catalog(on_done=_on_models_catalog_done)
        # invoke_props_dialog (not invoke_popup) so the dialog redraws
        # continuously — state flips from SAVING → IDLE / ERROR during
        # the async save must be visible without user interaction.
        return wm.invoke_props_dialog(self, width=640)

    def execute(self, context):
        # No-op: Save / Remove are their own operators, invoked from draw().
        _wipe_form_secrets(context.window_manager)
        return {'FINISHED'}

    def cancel(self, context):
        """Esc/click-away must not leave JWTs or API keys in RNA memory."""
        _wipe_form_secrets(context.window_manager)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        draw_dialog(layout, context.window_manager)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_save(Operator):
    """Validate with the provider and save your API key"""
    bl_idname = "mixar_byok.save"
    bl_label = "Save"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        # Requirements come from save_blocker so the greyed-out button and
        # the hint rendered beside it can never disagree. SAVING is checked
        # separately: it blocks the button but isn't a missing requirement.
        wm = context.window_manager
        return wm.byok_dialog_state != 'SAVING' and save_blocker(wm) is None

    def execute(self, context):
        wm = context.window_manager
        provider = wm.byok_form_provider

        if model_suggestions.is_openrouter(provider):
            return self._execute_openrouter(wm)
        if model_suggestions.is_codex(provider):
            return self._execute_codex(wm)

        model = wm.byok_form_model
        api_key = wm.byok_form_api_key.strip()

        if (
            provider == 'NONE'
            or not model_suggestions.is_valid_model(provider, model)
            or not api_key
        ):
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = "Choose a model for this provider and enter an API key."
            return {'CANCELLED'}

        wm.byok_dialog_state = 'SAVING'
        wm.byok_last_error = ''
        _redraw_mixie_chat_areas()

        byok_client.save_credentials(
            provider=provider,
            model=model,
            api_key=api_key,
            on_done=_on_save_done,
        )
        return {'FINISHED'}

    def _execute_openrouter(self, wm):
        """OpenRouter save: no client-side ping — the backend can reach
        OpenRouter directly, so it validates the key + model slug on Save."""
        model = wm.byok_form_openrouter_model.strip()
        api_key = wm.byok_form_api_key.strip()
        if not model or not api_key:
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = "Model slug and API key are required."
            return {'CANCELLED'}

        wm.byok_dialog_state = 'SAVING'
        wm.byok_last_error = ''
        _redraw_mixie_chat_areas()

        byok_client.save_credentials(
            provider='openrouter',
            model=model,
            api_key=api_key,
            on_done=_on_save_done,
        )
        return {'FINISHED'}

    def _execute_codex(self, wm):
        """Codex save: send the pasted auth.json bundle as the credential. The
        backend refreshes the token (validating it) and stores the bundle."""
        model = wm.byok_form_codex_model.strip()
        bundle = wm.byok_form_codex_bundle.strip()
        if not model or not bundle:
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = "Model and your auth.json bundle are required."
            return {'CANCELLED'}

        wm.byok_dialog_state = 'SAVING'
        wm.byok_last_error = ''
        _redraw_mixie_chat_areas()

        byok_client.save_credentials(
            provider='codex',
            model=model,
            api_key=bundle,
            on_done=_on_save_done,
        )
        return {'FINISHED'}


def _on_save_done(success: bool, data, err):
    """Main-thread save callback."""
    try:
        wm = bpy.context.window_manager
        if success:
            _apply_cached_state(wm, data or {})
            _wipe_form_secrets(wm)
            wm.byok_dialog_state = 'IDLE'
            wm.byok_last_error = ''
            logger.info("BYOK saved: provider=%s model=%s", wm.byok_current_provider, wm.byok_current_model)
        else:
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = err or "Save failed."
            logger.warning("BYOK save failed: %s", err)
        _redraw_mixie_chat_areas()
    except Exception as e:
        logger.error("BYOK save callback failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Codex — paste auth.json from clipboard
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_codex_load_file(Operator):
    """Read ~/.codex/auth.json from this machine into the field"""
    bl_idname = "mixar_byok.codex_load_file"
    bl_label = "Load from ~/.codex/auth.json"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        path = os.path.expanduser(os.path.join("~", ".codex", "auth.json"))
        if not os.path.exists(path):
            self.report({'WARNING'}, "~/.codex/auth.json not found — run `codex login` first")
            return {'CANCELLED'}
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("Codex auth.json read failed: %s", e)
            self.report({'ERROR'}, "Could not read ~/.codex/auth.json")
            return {'CANCELLED'}
        if not content:
            self.report({'WARNING'}, "~/.codex/auth.json is empty")
            return {'CANCELLED'}
        wm.byok_form_codex_bundle = content
        if len(wm.byok_form_codex_bundle) < len(content):
            # StringProperty maxlen truncates silently — a clipped bundle is
            # invalid JSON and the save fails with an error the user can't
            # connect to truncation.
            self.report(
                {'ERROR'},
                "auth.json is too large for this field and was truncated — "
                "it will not save correctly",
            )
            _wipe_form_secrets(wm)
            return {'CANCELLED'}
        _redraw_mixie_chat_areas()
        self.report({'INFO'}, "Loaded auth.json")
        return {'FINISHED'}


class MIXAR_BYOK_OT_codex_paste(Operator):
    """Paste your ~/.codex/auth.json from the clipboard into the field"""
    bl_idname = "mixar_byok.codex_paste"
    bl_label = "Paste auth.json"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        # Read the clipboard directly — this preserves the multi-line JSON that
        # a single-line prop field can't accept via a manual paste.
        clip = (wm.clipboard or "").strip()
        if not clip:
            self.report({'WARNING'}, "Clipboard is empty")
            return {'CANCELLED'}
        wm.byok_form_codex_bundle = clip
        if len(wm.byok_form_codex_bundle) < len(clip):
            self.report(
                {'ERROR'},
                "Pasted auth.json is too large for this field and was "
                "truncated — it will not save correctly",
            )
            _wipe_form_secrets(wm)
            return {'CANCELLED'}
        _redraw_mixie_chat_areas()
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Remove (two-click confirm)
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_request_remove(Operator):
    """Start the remove-confirmation flow"""
    bl_idname = "mixar_byok.request_remove"
    bl_label = "Remove"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.window_manager.byok_dialog_state = 'CONFIRM_REMOVE'
        return {'FINISHED'}


class MIXAR_BYOK_OT_cancel_remove(Operator):
    """Cancel the remove flow and return to the main dialog"""
    bl_idname = "mixar_byok.cancel_remove"
    bl_label = "Cancel"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.window_manager.byok_dialog_state = 'IDLE'
        return {'FINISHED'}


class MIXAR_BYOK_OT_confirm_remove(Operator):
    """Delete the stored API key server-side"""
    bl_idname = "mixar_byok.confirm_remove"
    bl_label = "Confirm Remove"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        wm.byok_dialog_state = 'SAVING'
        wm.byok_last_error = ''
        _redraw_mixie_chat_areas()

        byok_client.delete_credentials(on_done=_on_delete_done)
        return {'FINISHED'}


def _on_delete_done(success: bool, removed_count: int, err):
    """Main-thread delete callback."""
    try:
        wm = bpy.context.window_manager
        if success:
            _clear_cached_state(wm)
            _wipe_form_secrets(wm)
            wm.byok_dialog_state = 'IDLE'
            wm.byok_last_error = ''
            logger.info("BYOK removed: %d row(s) deleted", removed_count)
        else:
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = err or "Remove failed."
            logger.warning("BYOK remove failed: %s", err)
        _redraw_mixie_chat_areas()
    except Exception as e:
        logger.error("BYOK delete callback failed: %s", e, exc_info=True)


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

    Response parsing lives in `core/model_suggestions.parse_catalog`.
    """
    try:
        if not success:
            logger.debug("Models catalog fetch failed: %s", err)
            return

        providers, models = model_suggestions.parse_catalog(data)
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
    MIXAR_BYOK_OT_open_dialog,
    MIXAR_BYOK_OT_save,
    MIXAR_BYOK_OT_codex_load_file,
    MIXAR_BYOK_OT_codex_paste,
    MIXAR_BYOK_OT_request_remove,
    MIXAR_BYOK_OT_cancel_remove,
    MIXAR_BYOK_OT_confirm_remove,
    MIXAR_BYOK_OT_fetch_state,
    MIXAR_BYOK_OT_fetch_models_catalog,
)
