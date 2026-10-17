# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager-attached properties for the BYOK dialog.

Split into three groups:
- Form fields (transient input for the Save flow)
- Cached display fields (mirror of server BYOK state, drives the gear
  icon and the "Currently in use" dialog section)
- Dialog state machine (drives what draw() renders)

The provider and model EnumProperty items both come from cache-backed
callbacks — see core/model_suggestions.py for the cache and fetch wiring.
Users see friendly labels; the IDs are what get sent to the server.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ...constants import (
    BYOK_API_KEY_MAX_LENGTH,
    DIALOG_STATE_ITEMS,
    LOCAL_MODE_ITEMS,
    OPENROUTER_DEFAULT_MODEL,
)
from ...core.model_suggestions import (
    get_model_items,
    get_provider_items,
    is_local,
)


def _provider_items(self, context):
    """EnumProperty items callback — provider list comes from the
    backend cache (populated by the models-catalog fetch on login).
    Returns a "Loading…" or "No providers configured" sentinel when
    the cache is empty so the dropdown is never blank.
    """
    return get_provider_items()


def _model_items(self, context):
    """EnumProperty items callback — model list filtered to the
    currently-selected provider. Returns a "No models available"
    sentinel when the provider has no cached models so the dropdown
    is never blank. `self` is the WindowManager.
    """
    return get_model_items(getattr(self, 'byok_form_provider', '') or '')


# The provider / model picks are stored as IDENTIFIERS (the hidden `*_id`
# strings), not as Blender's enum number: with 3-tuple items that number is the
# list index, so a pick made while the catalog loads — or before a refresh
# reorders it — would silently become whichever item now sits at that index.
# get → the stored id's index in the CURRENT list (0, the first item, when
# unset or no longer listed); set → store the chosen item's identifier.

def _index_of(items, identifier) -> int:
    for index, item in enumerate(items):
        if item[0] == identifier:
            return index
    return 0


def _identifier_at(items, index) -> str:
    return items[index][0] if 0 <= index < len(items) else ''


def _provider_get(self):
    return _index_of(get_provider_items(), self.byok_form_provider_id)


def _provider_set(self, value):
    self.byok_form_provider_id = _identifier_at(get_provider_items(), value)
    # Run here rather than as `update=`: the reset must follow every write,
    # including assignments from Python (the dialog prefill).
    _provider_changed(self, None)


def _model_get(self):
    return _index_of(_model_items(self, None), self.byok_form_model_id)


def _model_set(self, value):
    self.byok_form_model_id = _identifier_at(_model_items(self, None), value)


def _remembered_model(wm, provider):
    """The model this account already uses with ``provider``: the key in use,
    else a paused key's model. "" when the provider has none."""
    if getattr(wm, 'byok_is_active', False) and getattr(wm, 'byok_current_provider', '') == provider:
        return getattr(wm, 'byok_current_model', '') or ''
    try:
        from ...core import credential_state
        paused_provider, paused_model = credential_state.resume_target()
    except Exception:
        return ''
    return paused_model if paused_provider == provider else ''


def _provider_changed(self, context):
    """When the user picks a different provider, reset the model
    selection so we don't end up with a model that doesn't belong to
    the new provider (which would be an invalid combo at save time).
    Coming back to the provider in use (or a paused key's) selects the model
    it runs, not the first in the list.
    """
    try:
        wm = context.window_manager if context is not None else self
        provider = getattr(wm, 'byok_form_provider', '') or ''
        items = get_model_items(provider)
        # Dynamic EnumProperties reject identifiers absent from their current
        # item callback.  Select the first real model for the new provider, or
        # the NONE sentinel only when that is what the callback exposes.
        remembered = _remembered_model(wm, provider)
        if remembered and any(item[0] == remembered for item in items):
            wm.byok_form_model = remembered
        else:
            wm.byok_form_model = items[0][0] if items else 'NONE'
        if is_local(provider):
            # Build the managed-model item cache (RAM fit + downloaded state)
            # and kick a background probe for user-run local apps, so the
            # Local form is populated by the time it draws.
            from ...core import local_provider
            local_provider.refresh_model_items()
            local_provider.refresh_detected_async()
    except Exception:
        pass


def _local_model_items(self, context):
    """Managed local-model dropdown — cache-backed (see core/local_provider)."""
    from ...core.local_provider import get_model_items as _local_items
    return _local_items()


def _local_detected_items(self, context):
    """Detected local apps dropdown — main-thread mirror of the async probe."""
    from ...core.local_provider import get_detected_items
    return get_detected_items()


def _local_detected_changed(self, context):
    """Selecting a detected app prefills the custom base URL + model."""
    try:
        wm = context.window_manager if context is not None else self
        ident = getattr(wm, 'byok_form_local_detected', 'NONE')
        if ident and ident != 'NONE':
            from ...core.local_provider import apply_detected_selection
            apply_detected_selection(wm, ident)
    except Exception:
        pass


def _local_mode_changed(self, context):
    """Switching to Custom kicks (or refreshes) the local-app probe."""
    try:
        wm = context.window_manager if context is not None else self
        if getattr(wm, 'byok_form_local_mode', 'MANAGED') == 'CUSTOM':
            from ...core.local_provider import refresh_detected_async
            refresh_detected_async()
    except Exception:
        pass


def wipe_transient_secrets(wm) -> None:
    """Best-effort wipe of credential form fields on a WindowManager."""
    if wm is None:
        return
    for attr in (
        'byok_form_api_key',
        'byok_form_local_custom_key',
    ):
        try:
            setattr(wm, attr, '')
        except Exception:
            pass


_WM_ATTRS = (
    'byok_form_provider',
    'byok_form_model',
    'byok_form_provider_id',
    'byok_form_model_id',
    'byok_form_api_key',
    'byok_form_openrouter_model',
    'byok_form_codex_path',
    'byok_form_local_mode',
    'byok_form_local_model',
    'byok_form_local_detected',
    'byok_form_local_custom_base',
    'byok_form_local_custom_model',
    'byok_form_local_custom_key',
    'byok_is_active',
    'byok_current_provider',
    'byok_current_model',
    'byok_current_supports_vision',
    'byok_key_preview',
    'byok_device_key_missing',
    'byok_key_resumable',
    'byok_dialog_state',
    'byok_last_error',
)


def register():
    WM = bpy.types.WindowManager

    # --- Form fields (what the user picks / types into the dialog) ---
    # Both provider and model use dynamic EnumProperty callbacks so the
    # lists can change without re-registering the properties. The pick lives
    # in the hidden `*_id` strings (see `_provider_get`); unset, the dropdown
    # shows the list's first item. Runtime-only: nothing goes into a .blend.
    WM.byok_form_provider_id = StringProperty(default='', options={'SKIP_SAVE'})
    WM.byok_form_model_id = StringProperty(default='', options={'SKIP_SAVE'})
    WM.byok_form_provider = EnumProperty(
        name="Provider",
        description="LLM provider",
        items=_provider_items,
        get=_provider_get,
        set=_provider_set,
        options={'SKIP_SAVE'},
    )
    WM.byok_form_model = EnumProperty(
        name="Model",
        description="Model to use with the selected provider",
        items=_model_items,
        get=_model_get,
        set=_model_set,
        options={'SKIP_SAVE'},
    )
    WM.byok_form_api_key = StringProperty(
        name="API Key",
        description=(
            "Your API key is stored encrypted and used only for Mixar agent requests. "
            "After saving, only a masked preview is shown."
        ),
        maxlen=BYOK_API_KEY_MAX_LENGTH,
        default='',
        subtype='PASSWORD',
        options={'SKIP_SAVE'},
    )

    # --- OpenRouter form field (shown when provider == 'openrouter'). The key
    # reuses byok_form_api_key; only the model is free-text and OpenRouter-specific.
    WM.byok_form_openrouter_model = StringProperty(
        name="Model",
        description="Any model slug from openrouter.ai/models (e.g. anthropic/claude-opus-4.8)",
        default=OPENROUTER_DEFAULT_MODEL,
    )

    # --- Codex form field (shown when provider == 'codex') ---
    # A PATH, not the tokens: Mixar reads the Codex CLI's own sign-in file
    # at use time (empty = $CODEX_HOME/auth.json, else ~/.codex/auth.json).
    # The model uses the shared catalog-backed byok_form_model dropdown
    # (served from the "openai" catalog group).
    WM.byok_form_codex_path = StringProperty(
        name="Codex sign-in file",
        description="Path to the Codex CLI's auth.json (leave empty for the default location)",
        maxlen=1024,
        default='',
        subtype='FILE_PATH',
        options={'SKIP_SAVE'},
    )

    # --- Local (this computer) form fields (shown when provider == 'local') ---
    WM.byok_form_local_mode = EnumProperty(
        name="Local mode",
        description="Managed by Mixar, or your own local server",
        items=LOCAL_MODE_ITEMS,
        default='MANAGED',
        update=_local_mode_changed,
    )
    WM.byok_form_local_model = EnumProperty(
        name="Local model",
        description="Curated model to download and run on this computer",
        items=_local_model_items,
    )
    WM.byok_form_local_detected = EnumProperty(
        name="Detected local apps",
        description="OpenAI-compatible servers found running on this computer",
        items=_local_detected_items,
        update=_local_detected_changed,
    )
    WM.byok_form_local_custom_base = StringProperty(
        name="Base URL",
        description="Your local server's base URL, e.g. http://127.0.0.1:11434",
        default='',
    )
    WM.byok_form_local_custom_model = StringProperty(
        name="Model",
        description="Model name as your local server exposes it",
        default='',
    )
    WM.byok_form_local_custom_key = StringProperty(
        name="API Key (optional)",
        description="Only if your local server requires one — most do not",
        maxlen=BYOK_API_KEY_MAX_LENGTH,
        default='',
        subtype='PASSWORD',
        options={'SKIP_SAVE'},
    )

    # --- Cached display fields (mirror of server BYOK state) ---
    WM.byok_is_active = BoolProperty(
        name="BYOK Active",
        description="True when the server reports byok_active for this user",
        default=False,
    )
    WM.byok_current_provider = StringProperty(default='')
    WM.byok_current_model = StringProperty(default='')
    # Whether the saved model accepts image input. Text-only models (many
    # OpenRouter models) run chat fine but skip 3D visual feedback, so the
    # dialog surfaces a note. Defaults True (platform + vision models).
    WM.byok_current_supports_vision = BoolProperty(default=True)
    WM.byok_key_preview = StringProperty(default='')
    # The server holds metadata only; the key lives in this device's
    # credential store. True = active server-side but nothing usable here
    # (upgrade / second machine / expired Codex sign-in) — the dialog asks
    # for the key only. Mirrored from core/credential_state.
    WM.byok_device_key_missing = BoolProperty(
        name="Key needed on this device",
        default=False,
    )
    # The server holds nothing for a PAUSED key, but this computer does: the
    # island's Mixie half deleted the server rows and kept the key record,
    # and the model card's key tab re-sends it. True while inactive and such a record is
    # here (derived off-thread by core/credential_state); the dialog names
    # it and offers Use my key / Forget saved key.
    WM.byok_key_resumable = BoolProperty(
        name="Saved key paused",
        description="Your API key is saved on this computer and paused; Mixie is answering",
        default=False,
    )

    # --- Dialog state machine ---
    WM.byok_dialog_state = EnumProperty(
        name="Dialog State",
        items=DIALOG_STATE_ITEMS,
        default='IDLE',
    )
    WM.byok_last_error = StringProperty(default='')


def unregister():
    WM = bpy.types.WindowManager
    # Clear live values before unregistering their RNA definitions.  This is
    # particularly important during Reload Scripts, where the WindowManager
    # instance survives module teardown.
    seen = set()
    candidates = []
    try:
        candidates.extend(list(bpy.data.window_managers))
    except Exception:
        pass
    try:
        candidates.append(bpy.context.window_manager)
    except Exception:
        pass
    for wm in candidates:
        marker = id(wm)
        if marker not in seen:
            seen.add(marker)
            wipe_transient_secrets(wm)
    for attr in _WM_ATTRS:
        try:
            delattr(WM, attr)
        except AttributeError:
            pass
