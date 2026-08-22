# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK operators: dialog + save/remove actions.

State machine lives on WindowManager (see ui/properties/byok_props.py).
The dialog operator's draw() delegates to `byok_dialog_ui.draw_dialog`,
which dispatches on `wm.byok_dialog_state` (IDLE / SAVING / REMOVING /
SAVED / REMOVED / ERROR / CONFIRM_REMOVE) and renders with the profile
card's design system. Save and Remove spawn async work through
`core/byok_client.py`; callbacks mutate WM state on the main thread and
the props dialog redraws on the next tick.

The dialog draws its own single-primary-action footer and always marks
one button active-default, which suppresses the props dialog's automatic
OK/Cancel row (`wm_block_dialog_create` skips it when the block already
has a default button) — the redundant Save-plus-OK pair is gone. Success
lands on an explicit SAVED / REMOVED recap with one Done button, so
"did it save?" is never a question.
"""

import os

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import byok_client, model_suggestions
from . import byok_dialog_ui
from .byok_state_ops import (
    _apply_cached_state,
    _clear_cached_state,
    _on_models_catalog_done,
    _redraw_mixie_chat_areas,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _wipe_form_secrets(wm):
    """Remove transient API/token material from the live WindowManager."""
    for attr in (
        'byok_form_api_key',
        'byok_form_codex_bundle',
        'byok_form_local_custom_key',
    ):
        try:
            setattr(wm, attr, '')
        except Exception:
            pass


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
            elif model_suggestions.is_local(wm.byok_current_provider):
                pass  # prefilled below by byok_local_ops.prepare_dialog
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
        # Local provider: refresh the managed-model item cache and prefill
        # mode/model from the last registration (cheap; guarded — the local
        # runtime module may be unavailable in stripped builds).
        try:
            from . import byok_local_ops
            byok_local_ops.prepare_dialog(wm)
        except Exception as e:
            logger.debug("Local provider dialog prep failed: %s", e)
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
        # All rendering lives in byok_dialog_ui (500-line rule): the
        # card-styled states AND the single-primary-action footer whose
        # active-default button suppresses the native OK/Cancel row.
        byok_dialog_ui.draw_dialog(self.layout, context.window_manager)


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
        # In-flight guard only. Field validation deliberately lives in
        # execute(), which routes problems to the ERROR state with a
        # message the user can act on — the old silently-greyed Save
        # button gave no clue what was missing (and the card-styled
        # button has no disabled look to lean on).
        return context.window_manager.byok_dialog_state not in ('SAVING', 'REMOVING')

    def execute(self, context):
        wm = context.window_manager
        if wm.byok_dialog_state in ('SAVING', 'REMOVING'):
            return {'CANCELLED'}
        provider = wm.byok_form_provider

        if model_suggestions.is_openrouter(provider):
            return self._execute_openrouter(wm)
        if model_suggestions.is_codex(provider):
            return self._execute_codex(wm)
        if model_suggestions.is_local(provider):
            return self._execute_local(wm)

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

    def _execute_local(self, wm):
        """Local save: managed requires the supervised server healthy;
        custom pings the user's server off-thread first. Both end in the
        same PUT /agent/byok (with base_url + supports_vision) and the
        shared _on_save_done callback."""
        from . import byok_local_ops
        result = byok_local_ops.execute_local(self, wm, on_done=_on_save_done)
        _redraw_mixie_chat_areas()
        return result

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


def _deregister_local_if_switched_away(active_provider):
    """The credential set now points at ``active_provider`` (None = removed).
    If a managed local registration is still on disk, tear it down — the
    backend will never relay to it again, so keeping llama-server running
    (and resurrecting it every startup) would waste the user's RAM.
    Main thread."""
    try:
        from mixar.modules.byok.constants import LOCAL_PROVIDER_ID
        if active_provider == LOCAL_PROVIDER_ID:
            return
        from mixar.modules.local_models.core import manifest, orchestrator
        if manifest.get_registered() is None:
            return
        logger.info("BYOK switched off local — deregistering local runtime")
        orchestrator.deregister()
    except Exception as e:
        logger.warning("Local deregistration skipped: %s", e)


def _on_save_done(success: bool, data, err):
    """Main-thread save callback."""
    try:
        wm = bpy.context.window_manager
        if success:
            _apply_cached_state(wm, data or {})
            _wipe_form_secrets(wm)
            # SAVED, not IDLE: the dialog shows an explicit recap with a
            # single Done button, so the user never has to wonder
            # whether the save landed.
            wm.byok_dialog_state = 'SAVED'
            wm.byok_last_error = ''
            logger.info("BYOK saved: provider=%s model=%s", wm.byok_current_provider, wm.byok_current_model)
            _deregister_local_if_switched_away(wm.byok_current_provider)
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
        wm.byok_dialog_state = 'REMOVING'
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
            # REMOVED, not IDLE — explicit recap, same as the save path.
            wm.byok_dialog_state = 'REMOVED'
            wm.byok_last_error = ''
            logger.info("BYOK removed: %d row(s) deleted", removed_count)
            _deregister_local_if_switched_away(None)
        else:
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = err or "Remove failed."
            logger.warning("BYOK remove failed: %s", err)
        _redraw_mixie_chat_areas()
    except Exception as e:
        logger.error("BYOK delete callback failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Registration (picked up by bootstrap auto-discovery)
# ---------------------------------------------------------------------------
# The fetch operators (mixar_byok.fetch_state / fetch_models_catalog)
# and the cached-state mirror live in byok_state_ops.py.

classes = (
    MIXAR_BYOK_OT_open_dialog,
    MIXAR_BYOK_OT_save,
    MIXAR_BYOK_OT_codex_load_file,
    MIXAR_BYOK_OT_codex_paste,
    MIXAR_BYOK_OT_request_remove,
    MIXAR_BYOK_OT_cancel_remove,
    MIXAR_BYOK_OT_confirm_remove,
)
