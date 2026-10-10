# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalog labels for a BYOK provider/model id pair (raw ids as the fallback).

`bpy`-free so the picker menu's row model can name the key in use — "Your
key: OpenRouter · Claude Sonnet 4.6" — and the wording is unit-testable. The
AI Provider Settings dialog draws the same labels; it imports these rather
than keeping its own copy.
"""

from typing import Tuple

from . import model_suggestions
from ..constants import CODEX_PROVIDER_ID, LOCAL_PROVIDER_ID, OPENROUTER_PROVIDER_ID

# Client-side providers whose dropdown labels are descriptive ("Codex
# (ChatGPT sub)"); the island toggle names them in one short word.
_TOGGLE_LABELS = {
    CODEX_PROVIDER_ID: "Codex",
    LOCAL_PROVIDER_ID: "Local",
    OPENROUTER_PROVIDER_ID: "OpenRouter",
}


def lookup_provider_label(provider_id: str) -> str:
    """Catalog label for a provider id, or the id itself when unknown."""
    for pid, plabel, _desc in model_suggestions.get_provider_items():
        if pid == provider_id:
            return plabel
    return provider_id


def toggle_provider_label(provider_id: str) -> str:
    """The island toggle's name for the key's provider: a short word for the
    client-side options, the catalog label otherwise (raw id as fallback)."""
    if not provider_id:
        return ""
    return _TOGGLE_LABELS.get(provider_id) or lookup_provider_label(provider_id)


def lookup_model_label(provider_id: str, model_id: str) -> str:
    """Catalog label for a model id under a provider, or the id itself."""
    for mid, mlabel, _desc in model_suggestions.get_model_items(provider_id):
        if mid == model_id:
            return mlabel
    return model_id


def byok_current_labels() -> Tuple[str, str]:
    """(provider label, model label) of the key in use; both empty when none.

    Read from `credential_state` at call time — the menu builds its rows on
    every draw, so a credential fetch that lands after the menu opened is
    picked up by the next draw, never cached stale here.
    """
    from . import credential_state

    current = credential_state.snapshot()
    if not current.get("byok_is_active"):
        return "", ""
    provider = current.get("byok_current_provider") or ""
    model = current.get("byok_current_model") or ""
    return (
        lookup_provider_label(provider) if provider else "",
        lookup_model_label(provider, model) if model else "",
    )
