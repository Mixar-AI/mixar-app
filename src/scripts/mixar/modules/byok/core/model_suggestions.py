# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cached provider + model catalog fetched from the backend.

Endpoint: GET /api/v1/agent/models

The cache is populated by `populate(...)` (called from the models-catalog
fetch callback in byok_ops.py) and cleared by `clear()` (called from the
logout hook). Three reader functions are the public API:

- get_provider_items()    — for the provider EnumProperty items callback
- get_model_items(pid)    — for the model EnumProperty items callback
- is_loaded()             — has populate() been called at least once

Both dropdowns use EnumProperty, so items are 3-tuples of
(identifier, label, description). Blender renders the label as primary
and stores the identifier separately — user sees friendly labels, the
ID is what gets sent to the server.

Providers-reader semantics:
- Fetch not yet completed          → "Loading…"                 sentinel
- Fetch succeeded with empty list  → "No providers configured"  sentinel
- Fetch succeeded with real list   → the list

Models-reader semantics:
- Provider has no cached models    → "No models available"      sentinel
- Provider has cached models       → the list

All sentinels share the id 'NONE' so Save's poll() blocks in any
combination of "no real selection yet".
"""

from ..constants import (
    CODEX_PROVIDER_ID,
    CODEX_PROVIDER_ITEM,
    MODEL_EMPTY_SENTINEL,
    PROVIDER_EMPTY_SENTINEL,
    PROVIDER_LOADING_SENTINEL,
)

# Module-level caches. Stored as Python-stable references so the
# EnumProperty callbacks can return them directly without GC issues.
_provider_cache: list[tuple[str, str, str]] = []
_model_cache: dict[str, list[tuple[str, str, str]]] = {}

# Set to True once populate() has been called — even with an empty
# providers list. Used to distinguish "haven't fetched yet" from
# "fetched and the backend has nothing".
_populated_once: bool = False


def is_codex(provider: str) -> bool:
    """True when ``provider`` is the client-side Codex (ChatGPT sub) option."""
    return provider == CODEX_PROVIDER_ID


def get_provider_items() -> list[tuple[str, str, str]]:
    """EnumProperty items for the provider dropdown.

    Always ends with the client-side "Codex (ChatGPT sub)" option (not part of
    the backend catalog), so a subscriber can pick it even before the catalog
    loads. The cloud providers come first (cached catalog, or a sentinel).
    """
    if _provider_cache:
        cloud = list(_provider_cache)
    elif _populated_once:
        cloud = [PROVIDER_EMPTY_SENTINEL]
    else:
        cloud = [PROVIDER_LOADING_SENTINEL]
    return cloud + [CODEX_PROVIDER_ITEM]


def get_model_items(provider: str) -> list[tuple[str, str, str]]:
    """EnumProperty items for the model dropdown, for a given provider.

    Returns the provider's cached models when available; otherwise a
    single sentinel item. Always returns a non-empty list — Blender
    renders a blank/broken dropdown when items is [].
    """
    cached = _model_cache.get(provider)
    if cached:
        return cached
    return [MODEL_EMPTY_SENTINEL]


def is_loaded() -> bool:
    """True iff populate() has been called at least once, regardless of
    whether it populated any real providers.

    Used to decide "should we trigger another fetch?" — a successful
    fetch that returned an empty list should NOT trigger repeated
    refetches; the backend is authoritative.
    """
    return _populated_once


def populate(providers, models) -> None:
    """Replace the caches from a successful models-catalog response.

    Args:
        providers: iterable of (id, label, description) tuples — the
            EnumProperty items shape Blender expects. May be empty
            if the backend has no providers enabled.
        models: dict mapping provider_id -> list[(id, label, description)]
            for that provider's models. May be empty.
    """
    global _populated_once
    _provider_cache.clear()
    if providers:
        _provider_cache.extend(tuple(p) for p in providers)
    _model_cache.clear()
    if models:
        for provider_id, model_list in models.items():
            _model_cache[provider_id] = [tuple(m) for m in model_list]
    _populated_once = True


def clear() -> None:
    """Drop all cached data. Called on logout — resets the populated
    flag so the next login triggers a fresh fetch.
    """
    global _populated_once
    _provider_cache.clear()
    _model_cache.clear()
    _populated_once = False
