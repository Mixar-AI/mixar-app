# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK operators: dialog + save/remove/fetch actions.

State machine lives on WindowManager (see ui/properties/byok_props.py).
The dialog operator's draw() dispatches on `wm.byok_dialog_state` to
render IDLE / SAVING / ERROR / CONFIRM_REMOVE. Save and Remove spawn
async work through `core/byok_client.py`; callbacks mutate WM state on
the main thread and the props dialog redraws on the next tick.
"""

import os

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import byok_client, model_suggestions

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


def _lookup_model_label(provider_id: str, model_id: str) -> str:
    """Resolve a model ID to its human-readable label from the cache.

    Falls back to the raw ID when the cache is empty or the model
    isn't known (e.g. admin removed the model after the user saved).
    """
    for mid, mlabel, _desc in model_suggestions.get_model_items(provider_id):
        if mid == model_id:
            return mlabel
    return model_id


def _lookup_provider_label(provider_id: str) -> str:
    """Resolve a provider ID to its human-readable label from the cache."""
    for pid, plabel, _desc in model_suggestions.get_provider_items():
        if pid == provider_id:
            return plabel
    return provider_id


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
        wm.byok_form_api_key = ''
        wm.byok_form_codex_bundle = ''  # never prefill the token bundle
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
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        wm = context.window_manager

        state = wm.byok_dialog_state

        # Header — always shown
        hero = layout.box()
        header = hero.row(align=True)
        header.scale_y = 1.25
        header.label(text="AI Provider Settings", icon='PREFERENCES')
        status = header.row(align=True)
        status.alignment = 'RIGHT'
        if wm.byok_is_active:
            status.label(text="Active", icon='KEY_HLT')
        else:
            status.label(text="Not configured", icon='UNLOCKED')

        subtitle = hero.row()
        subtitle.enabled = False
        subtitle.label(text="Choose the provider and model the Mixar agent should use.")
        layout.separator(factor=0.9)

        if state == 'CONFIRM_REMOVE':
            self._draw_confirm_remove(layout)
            return

        # "Currently in use" info strip — only when active and not mid-edit error
        if wm.byok_is_active and state != 'ERROR':
            self._draw_current_usage(layout, wm)
            layout.separator(factor=0.8)

        # The form — visible in IDLE, SAVING, ERROR
        self._draw_form(layout, wm, disabled=(state == 'SAVING'))

        # Error message, if any
        if state == 'ERROR' and wm.byok_last_error:
            layout.separator(factor=0.4)
            err_box = layout.box()
            err_box.alert = True
            err_col = err_box.column(align=True)
            err_col.label(text="Save failed", icon='ERROR')
            for line in _wrap(wm.byok_last_error, width=68):
                err_col.label(text=line)

        layout.separator(factor=0.9)

        # Action row
        actions = layout.row(align=True)
        actions.scale_y = 1.35
        if state == 'SAVING':
            actions.enabled = False
            actions.label(text="Validating with provider...", icon='SORTTIME')
        else:
            if wm.byok_is_active:
                remove_col = actions.row(align=True)
                remove_col.alert = True
                remove_col.operator(
                    MIXAR_BYOK_OT_request_remove.bl_idname,
                    text="Remove",
                    icon='TRASH',
                )
            actions.operator(
                MIXAR_BYOK_OT_save.bl_idname,
                text="Save",
                icon='CHECKMARK',
            )

    # --- sub-sections ---

    def _draw_current_usage(self, layout, wm):
        box = layout.box()
        heading = box.row()
        heading.scale_y = 1.15
        heading.label(text="Current configuration", icon='KEY_HLT')
        provider_label = _lookup_provider_label(wm.byok_current_provider)
        model_label = _lookup_model_label(wm.byok_current_provider, wm.byok_current_model)

        col = box.column(align=True)
        col.separator(factor=0.35)
        self._draw_value_row(col, "Provider", provider_label)
        self._draw_value_row(col, "Model", model_label)
        if model_suggestions.is_codex(wm.byok_current_provider):
            self._draw_value_row(col, "Account", wm.byok_key_preview or "ChatGPT subscription")
        else:
            self._draw_value_row(col, "API Key", wm.byok_key_preview or "Stored securely")

        # Text-only model note: chat works, but 3D modeling/texturing runs
        # without the viewport visual-feedback loop (images can't be sent).
        if not wm.byok_current_supports_vision:
            box.separator(factor=0.4)
            note = box.column(align=True)
            note.scale_y = 0.85
            note.enabled = False
            note.label(text="Text-only model — no image input.", icon='INFO')
            note.label(text="Chat works; 3D tasks run without visual feedback.")

    def _draw_form(self, layout, wm, disabled: bool):
        box = layout.box()
        heading = box.row()
        heading.scale_y = 1.15
        heading.label(text="Provider setup", icon='PREFERENCES')

        col = box.column(align=True)
        col.separator(factor=0.45)
        col.enabled = not disabled
        self._draw_tall_prop(col, wm, 'byok_form_provider', "Provider")

        if model_suggestions.is_openrouter(wm.byok_form_provider):
            self._draw_openrouter_fields(box, col, wm)
        elif model_suggestions.is_codex(wm.byok_form_provider):
            self._draw_codex_fields(box, col, wm)
        else:
            self._draw_cloud_fields(box, col, wm)

    def _draw_cloud_fields(self, box, col, wm):
        self._draw_tall_prop(col, wm, 'byok_form_model', "Model")
        self._draw_tall_prop(col, wm, 'byok_form_api_key', "API Key")

        box.separator(factor=0.55)
        hint = box.row()
        hint.enabled = False
        hint.label(
            text="Your API key is stored encrypted and used only for Mixar agent requests.",
            icon='INFO',
        )
        preview_hint = box.row()
        preview_hint.enabled = False
        preview_hint.label(text="After saving, only a masked preview is shown.")

    def _draw_openrouter_fields(self, box, col, wm):
        """Free-text model slug + API key for OpenRouter (base_url is fixed)."""
        self._draw_tall_prop(col, wm, 'byok_form_openrouter_model', "Model")
        self._draw_tall_prop(col, wm, 'byok_form_api_key', "API Key")

        box.separator(factor=0.55)
        warn = box.row()
        warn.alert = True
        warn.label(
            text="Pick a model that supports tool / function calling — the agent needs it.",
            icon='ERROR',
        )
        hint = box.row()
        hint.enabled = False
        hint.label(
            text="Any slug from openrouter.ai/models, e.g. anthropic/claude-opus-4.8.",
            icon='INFO',
        )
        key_hint = box.row()
        key_hint.enabled = False
        key_hint.label(text="Your key is stored encrypted; only a masked preview is shown after saving.")

    def _draw_codex_fields(self, box, col, wm):
        """Model slug + auto-load / paste of the ~/.codex/auth.json token bundle."""
        self._draw_tall_prop(col, wm, 'byok_form_codex_model', "Model")

        # Easy path: read ~/.codex/auth.json straight off this machine.
        load_row = col.row()
        load_row.scale_y = 1.35
        load_row.operator(
            MIXAR_BYOK_OT_codex_load_file.bl_idname,
            text="Load from ~/.codex/auth.json",
            icon='FILE_REFRESH',
        )
        col.separator(factor=0.35)

        # Fallback: the (hidden) field + a Paste-from-clipboard button and a
        # char-count confirmation, since the field masks the tokens.
        label_row = col.row()
        label_row.enabled = False
        label_row.label(text="…or paste it manually")
        paste_row = col.row(align=True)
        paste_row.scale_y = 1.45
        paste_row.prop(wm, 'byok_form_codex_bundle', text="")
        paste_row.operator(MIXAR_BYOK_OT_codex_paste.bl_idname, text="", icon='PASTEDOWN')
        n = len(wm.byok_form_codex_bundle or "")
        status = col.row()
        status.enabled = False
        status.label(
            text=(f"{n} characters pasted" if n else "Empty — paste your auth.json"),
            icon='CHECKMARK' if n else 'INFO',
        )
        col.separator(factor=0.45)

        box.separator(factor=0.55)
        for line in (
            "Run  codex login  in your terminal, then paste the full contents of",
            "~/.codex/auth.json here (the Paste button reads your clipboard).",
            "Uses your ChatGPT subscription — Mixar credits are not charged.",
        ):
            row = box.row()
            row.enabled = False
            row.label(text=line, icon='INFO')

    def _draw_tall_prop(self, layout, data, prop_name: str, label: str):
        label_row = layout.row()
        label_row.enabled = False
        label_row.label(text=label)

        field_row = layout.row()
        field_row.scale_y = 1.45
        field_row.prop(data, prop_name, text="")
        layout.separator(factor=0.45)

    def _draw_value_row(self, layout, label: str, value: str):
        row = layout.split(factor=0.24, align=True)
        row.scale_y = 1.15
        label_col = row.row()
        label_col.enabled = False
        label_col.label(text=label)
        row.label(text=value)

    def _draw_confirm_remove(self, layout):
        box = layout.box()
        col = box.column(align=True)
        col.alert = True
        col.label(text="Remove your API key?", icon='QUESTION')
        body = box.column(align=True)
        body.enabled = False
        body.label(text="The agent will use Mixar's default provider again.")
        body.label(text="Mixar credits will be charged for future agent requests.")

        layout.separator(factor=0.8)
        row = layout.row(align=True)
        row.operator(
            MIXAR_BYOK_OT_cancel_remove.bl_idname,
            text="Cancel",
            icon='CANCEL',
        )
        confirm = row.row(align=True)
        confirm.alert = True
        confirm.operator(
            MIXAR_BYOK_OT_confirm_remove.bl_idname,
            text="Confirm Remove",
            icon='TRASH',
        )


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
        wm = context.window_manager
        if wm.byok_dialog_state == 'SAVING':
            return False
        if model_suggestions.is_openrouter(wm.byok_form_provider):
            # OpenRouter needs a model slug + API key.
            return bool(wm.byok_form_openrouter_model.strip()) and bool(
                wm.byok_form_api_key.strip()
            )
        if model_suggestions.is_codex(wm.byok_form_provider):
            # Codex needs a model slug + the pasted auth.json bundle.
            return bool(wm.byok_form_codex_model.strip()) and bool(
                wm.byok_form_codex_bundle.strip()
            )
        return (
            wm.byok_form_provider != 'NONE'   # block while only a sentinel is selectable
            and wm.byok_form_model != 'NONE'
            and bool(wm.byok_form_api_key.strip())
        )

    def execute(self, context):
        wm = context.window_manager
        provider = wm.byok_form_provider

        if model_suggestions.is_openrouter(provider):
            return self._execute_openrouter(wm)
        if model_suggestions.is_codex(provider):
            return self._execute_codex(wm)

        model = wm.byok_form_model
        api_key = wm.byok_form_api_key.strip()

        if provider == 'NONE' or model == 'NONE' or not api_key:
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = "Provider, model, and API key are required."
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
            wm.byok_form_api_key = ''
            wm.byok_form_codex_bundle = ''  # don't retain the token bundle
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
            wm.byok_form_api_key = ''
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
# Utilities
# ---------------------------------------------------------------------------

def _wrap(text: str, width: int) -> list[str]:
    """Dumb word-wrap for error rendering inside a box (Blender labels
    don't wrap on their own).
    """
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            if current:
                lines.append(current)
            current = word if len(word) <= width else word[:width]
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


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
