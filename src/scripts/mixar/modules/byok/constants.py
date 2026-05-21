# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK module constants.

Provider and model lists are fetched from the backend at login time —
see core/model_suggestions.py for the cache and fetch wiring. The only
client-side enum left here is the dialog state machine.
"""

# Dialog state machine — drives what the dialog renders on each draw.
DIALOG_STATE_ITEMS = (
    ('IDLE',            "Idle",            "Ready for input"),
    ('SAVING',          "Saving",          "Request in flight"),
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
