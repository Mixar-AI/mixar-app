# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK module constants.

Provider and model lists are fetched from the backend at login time —
see core/model_suggestions.py for the cache and fetch wiring. The only
client-side enum left here is the dialog state machine.
"""

# Explicitly allow long provider keys in the Blender RNA string backing
# the password field. Some provider-issued keys can exceed Blender's
# implicit/default text input storage.
BYOK_API_KEY_MAX_LENGTH = 256

# Dialog state machine — drives what the dialog renders on each draw.
# The dialog owns its whole footer (the native OK/Cancel row is
# suppressed — see ui/operators/byok_dialog_ui.py), so every state must
# resolve to exactly one primary action:
#
#   IDLE            form + [Cancel][Save & Activate]
#   SAVING          disabled form + progress pill (validation in flight)
#   REMOVING        config card + progress pill (delete in flight)
#   SAVED           recap card + [Done] — the explicit "it saved" moment
#   REMOVED         recap card + [Done]
#   ERROR           form + inline error + [Cancel][Try Again]
#   CONFIRM_REMOVE  config card + warning + [Keep My Key][Remove API Key]
DIALOG_STATE_ITEMS = (
    ('IDLE',            "Idle",            "Ready for input"),
    ('SAVING',          "Saving",          "Save request in flight"),
    ('REMOVING',        "Removing",        "Delete request in flight"),
    ('SAVED',           "Saved",           "Save confirmed — showing the recap"),
    ('REMOVED',         "Removed",         "Delete confirmed — showing the recap"),
    ('ERROR',           "Error",           "Last request failed"),
    ('CONFIRM_REMOVE',  "Confirm Remove",  "Awaiting delete confirmation"),
)

# Sentinels shown in the provider dropdown when no real providers are
# available. Both share the id 'NONE' so Save's poll() blocks while
# either is selected — the labels differ so the user sees the right
# message for each situation:
#
#   LOADING — fetch hasn't completed yet (cold-start pre-login, or
#             transient fetch failure; next open retries).
#   EMPTY   — fetch succeeded but the backend has no providers enabled;
#             this is an admin-configuration state, user can't self-serve.
PROVIDER_LOADING_SENTINEL = ('NONE', "Loading…",                 "Fetching supported providers")
PROVIDER_EMPTY_SENTINEL   = ('NONE', "No providers configured", "Contact support — no providers are currently enabled")

# Shown in the model dropdown when the currently-selected provider has
# no models available (either the catalog hasn't loaded, the provider is
# the 'NONE' sentinel itself, or the provider genuinely has no models).
# Same 'NONE' id so Save's poll() also blocks on model.
MODEL_EMPTY_SENTINEL = ('NONE', "No models available", "Select a provider with available models")

# The "OpenRouter" provider is a client-side-only option in the dropdown: the user
# supplies a key and any model slug OpenRouter exposes (no fixed catalog list),
# so it's always offered and selecting it swaps the form to a key + free-text
# model field. The base_url is fixed server-side (not user-entered).
OPENROUTER_PROVIDER_ID = 'openrouter'
OPENROUTER_PROVIDER_ITEM = (
    OPENROUTER_PROVIDER_ID,
    "OpenRouter",
    "Use your OpenRouter key with any model on openrouter.ai/models",
)

# Prefilled model slug — a sensible, widely-available default the user can edit.
OPENROUTER_DEFAULT_MODEL = "anthropic/claude-opus-4.8"

# "Codex (ChatGPT)" — a client-side-only provider option (not in the backend
# catalog). Selecting it swaps the credential field to a paste field for the
# ~/.codex/auth.json bundle; the user routes the agent through their ChatGPT
# subscription instead of an API key. The model dropdown reuses the backend
# catalog's "openai" group (see model_suggestions._MODEL_SOURCE_PROVIDER).
CODEX_PROVIDER_ID = 'codex'
CODEX_PROVIDER_ITEM = (
    CODEX_PROVIDER_ID,
    "Codex (ChatGPT sub)",
    "Use your ChatGPT/Codex subscription — paste ~/.codex/auth.json after `codex login`",
)

# "Local (this computer)" — a client-side-only provider option: the agent's
# LLM calls are relayed over the agent WebSocket to a model server running on
# the user's own machine (managed llama-server via modules/local_models, or a
# custom OpenAI-compatible server like Ollama / LM Studio). No cloud key.
LOCAL_PROVIDER_ID = 'local'
LOCAL_PROVIDER_ITEM = (
    LOCAL_PROVIDER_ID,
    "Local (this computer)",
    "Run the agent on a model on this computer — private, no API key required",
)

# Managed vs custom sub-mode of the Local provider form.
LOCAL_MODE_ITEMS = (
    ('MANAGED', "Managed by Mixar",
     "Mixar downloads and runs a curated model on this computer"),
    ('CUSTOM', "Custom local server",
     "Point Mixar at an OpenAI-compatible server you already run "
     "(Ollama, LM Studio, llama.cpp, ...)"),
)
