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
    CODEX_DEFAULT_MODEL,
    DIALOG_STATE_ITEMS,
    OPENROUTER_DEFAULT_MODEL,
)
from ...core.model_suggestions import get_model_items, get_provider_items


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
    is never blank.
    """
    provider = getattr(context.window_manager, 'byok_form_provider', '') or ''
    return get_model_items(provider)


def _provider_changed(self, context):
    """When the user picks a different provider, reset the model
    selection so we don't end up with a model that doesn't belong to
    the new provider (which would be an invalid combo at save time).
    """
    try:
        wm = context.window_manager if context is not None else self
        provider = getattr(wm, 'byok_form_provider', '') or ''
        items = get_model_items(provider)
        # Dynamic EnumProperties reject identifiers absent from their current
        # item callback.  Select the first real model for the new provider, or
        # the NONE sentinel only when that is what the callback exposes.
        wm.byok_form_model = items[0][0] if items else 'NONE'
    except Exception:
        pass


def wipe_transient_secrets(wm) -> None:
    """Best-effort wipe of credential form fields on a WindowManager."""
    if wm is None:
        return
    for attr in ('byok_form_api_key', 'byok_form_codex_bundle'):
        try:
            setattr(wm, attr, '')
        except Exception:
            pass


_WM_ATTRS = (
    'byok_form_provider',
    'byok_form_model',
    'byok_form_api_key',
    'byok_form_openrouter_model',
    'byok_form_codex_bundle',
    'byok_form_codex_model',
    'byok_is_active',
    'byok_current_provider',
    'byok_current_model',
    'byok_current_supports_vision',
    'byok_key_preview',
    'byok_dialog_state',
    'byok_last_error',
)


def register():
    WM = bpy.types.WindowManager

    # --- Form fields (what the user picks / types into the dialog) ---
    # Both provider and model use dynamic EnumProperty callbacks so the
    # lists can change without re-registering the properties. NOTE: when
    # items is a callback, EnumProperty does not accept a string default
    # — whichever item is index 0 in the cache becomes the default.
    WM.byok_form_provider = EnumProperty(
        name="Provider",
        description="LLM provider",
        items=_provider_items,
        update=_provider_changed,
    )
    WM.byok_form_model = EnumProperty(
        name="Model",
        description="Model to use with the selected provider",
        items=_model_items,
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

    # --- Codex form fields (shown when provider == 'codex') ---
    # The bundle is the full ~/.codex/auth.json (multi-KB, contains JWTs), so
    # a generous maxlen; PASSWORD hides the tokens (the Paste button + a char
    # count confirm it landed). Model is a free-text slug (lineup varies per
    # subscription tier).
    WM.byok_form_codex_bundle = StringProperty(
        name="Codex auth.json",
        description="Contents of ~/.codex/auth.json (run `codex login` first)",
        maxlen=16384,
        default='',
        subtype='PASSWORD',
        options={'SKIP_SAVE'},
    )
    WM.byok_form_codex_model = StringProperty(
        name="Model",
        description="Codex model slug, e.g. gpt-5.5 / gpt-5.4 / gpt-5.4-mini",
        default=CODEX_DEFAULT_MODEL,
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
