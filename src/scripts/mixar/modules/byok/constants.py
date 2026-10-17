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
#   CONFIRM_REMOVE  config card + warning + [Keep my key][Remove key]; also where a
#                   failed remove lands, with its error, so Remove retries
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

# --- Local key store + per-turn pass-through -------------------------------
# The backend stores BYOK metadata only; the key lives in the OS credential
# store on this machine (core/key_store.py) and rides every `chat` / `input`
# command as these payload fields (core/turn_credentials.py).
BYOK_TURN_KEY_FIELD = "byok_key"
BYOK_TURN_ACCOUNT_FIELD = "byok_account_id"
# The `input` action the server exempts from the key requirement (an abort
# makes no model call): sent at once, no store read, no Codex refresh.
BYOK_TURN_ABORT_ACTION = "abort"
# Command error code the server answers with when BYOK is active and the
# command carried no key (409). The detail also names the account's
# `provider` and `model`; the chat shows a desktop-owned card
# (`space_mixie_chat/core/byok_card.py`) whose actions resend the message.
BYOK_KEY_REQUIRED_CODE = "byok_key_required"
# Client-side pre-send refusals share the command-error path under these codes.
BYOK_CODEX_EXPIRED_CODE = "byok_codex_expired"
BYOK_CODEX_REFRESH_FAILED_CODE = "byok_codex_refresh_failed"
# Display names for the card line ("Enter your OpenAI API key to continue");
# any other provider id is shown capitalised.
BYOK_PROVIDER_DISPLAY_NAMES = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "google": "Gemini",
    "openrouter": "OpenRouter",
}
# Credential-store entry name prefix; the Mixar user id is appended so two
# accounts on one machine never share a key.
BYOK_KEY_STORE_PREFIX = "BYOK"

# --- Sealed keys in transit (core/transport_seal.py) ------------------------
# Every key field that leaves this device (`byok_key` per turn, `api_key` of
# a save) is sealed to the backend's X25519 key; the backend refuses
# plaintext. The wire format and KDF info are a frozen contract with the
# backend's `core/byok_transport.py`.
BYOK_TRANSPORT_ENVELOPE_PREFIX = "mxs1"
BYOK_TRANSPORT_ALGORITHM = "hpke-base/dhkem-x25519-hkdf-sha256/hkdf-sha256/aes-128-gcm"
BYOK_TRANSPORT_HKDF_INFO = b"mixar-byok-transport/v1"   # the HPKE application info
# How long a fetched server key is trusted before it is fetched again
# (the server's `Cache-Control: max-age`); a rotation inside the window is
# answered by `byok_transport_key_stale` and one automatic resend.
BYOK_TRANSPORT_KEY_TTL_S = 3600
# Server codes (HTTP on the PUT routes; over the socket like the 409 above).
BYOK_KEY_UNSEALED_CODE = "byok_key_unsealed"               # 400: plaintext / tampered
BYOK_TRANSPORT_KEY_STALE_CODE = "byok_transport_key_stale"  # 409: refetch, resend ONCE
BYOK_TRANSPORT_UNAVAILABLE_CODE = "byok_transport_unavailable"  # 503: no server key
# Client-side refusal when the server key could not be fetched over the network.
BYOK_TRANSPORT_UNREACHABLE_CODE = "byok_transport_unreachable"

# --- Codex (ChatGPT) token refresh ------------------------------------------
# The desktop keeps the refresh token and renews the access token itself
# (the server only ever sees the access token + account id).
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_TOKEN_SCOPE = "openid profile email offline_access"
CODEX_USER_AGENT = "codex_cli_rs/0.20.0"
CODEX_REFRESH_TIMEOUT_S = 10
# Refresh BEFORE sending when the access token expires within this window
# (or carries no `exp` at all).
CODEX_REFRESH_MARGIN_S = 24 * 60 * 60
# The ChatGPT account id claim inside Codex id/access tokens.
CODEX_AUTH_CLAIM = "https://api.openai.com/auth"
CODEX_ACCOUNT_ID_CLAIM = "chatgpt_account_id"

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
