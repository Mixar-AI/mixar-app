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

from mixar.modules.common.i18n import n_

from . import model_suggestions
from ..constants import CODEX_PROVIDER_ID, LOCAL_PROVIDER_ID, OPENROUTER_PROVIDER_ID

# The island key chip's short provider names (the design reads "Claude API").
# Brand names, so never translated; the dropdown's catalog labels stay the
# descriptive ones ("Codex (ChatGPT sub)"). Unknown ids fall back to the
# catalog label.
_CHIP_PROVIDER_LABELS = {
    'anthropic': "Claude API",
    'openai': "OpenAI API",
    'gemini': "Gemini API",
    'kimi': "Kimi API",
    'fugu': "Fugu API",
    OPENROUTER_PROVIDER_ID: "OpenRouter",
    CODEX_PROVIDER_ID: "Codex",
}
# The one chip name that is a word, not a brand: translated at display time.
LOCAL_CHIP_LABEL = n_("Local")


def lookup_provider_label(provider_id: str) -> str:
    """Catalog label for a provider id, or the id itself when unknown."""
    for pid, plabel, _desc in model_suggestions.get_provider_items():
        if pid == provider_id:
            return plabel
    return provider_id


def chip_provider_label(provider_id: str) -> str:
    """The island key chip's name for the key's provider ("Claude API"); the
    catalog label for a provider without a short name, "" for none."""
    if not provider_id:
        return ""
    if provider_id == LOCAL_PROVIDER_ID:
        return LOCAL_CHIP_LABEL
    return _CHIP_PROVIDER_LABELS.get(provider_id) or lookup_provider_label(provider_id)


def chip_model_label(provider_id: str, model_id: str) -> str:
    """The key chip's model name: the catalog label without a leading word
    that repeats the chip's brand ("Claude Opus 5.5" beside "Claude API"
    reads "Opus 5.5"). A label whose remainder starts with a digit keeps its
    brand ("Gemini 3.1 Pro" never becomes "3.1 Pro"), and a provider without
    a short brand name keeps every label whole."""
    if not model_id:
        return ""
    label = lookup_model_label(provider_id, model_id)
    # Only a known short name is a brand; a catalog fallback is not.
    brand = _CHIP_PROVIDER_LABELS.get(provider_id, "").split(" ", 1)[0].casefold()
    head, _, rest = label.partition(" ")
    if brand and rest and head.casefold() == brand and rest[0].isalpha():
        return rest
    return label


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
