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

A fourth reader, `get_platform_models()`, serves the HOSTED agent model picker
(the footer / island dropdown) rather than the BYOK dialog. It returns full
records — the six per-model flags the catalog carries — in SERVER ORDER, and is
kept in a store parallel to the enum tuples on purpose (see `_platform_records`).

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
    LOCAL_PROVIDER_ID,
    LOCAL_PROVIDER_ITEM,
    MODEL_EMPTY_SENTINEL,
    OPENROUTER_PROVIDER_ID,
    OPENROUTER_PROVIDER_ITEM,
    PROVIDER_EMPTY_SENTINEL,
    PROVIDER_LOADING_SENTINEL,
)

# Providers whose model dropdown is served from another provider's catalog
# group. Codex runs OpenAI's gpt-5.x lineup through the user's ChatGPT
# subscription, so it reuses the "openai" models — no separate catalog rows.
_MODEL_SOURCE_PROVIDER: dict[str, str] = {CODEX_PROVIDER_ID: 'openai'}

# Module-level caches. Stored as Python-stable references so the
# EnumProperty callbacks can return them directly without GC issues.
_provider_cache: list[tuple[str, str, str]] = []
_model_cache: dict[str, list[tuple[str, str, str]]] = {}

# Full per-model records, flattened across providers and held in SERVER ORDER
# (providers as the backend sorted them, models by admin `display_order`).
#
# A PARALLEL store, deliberately: the enum tuples above are frozen at three
# elements because Blender's EnumProperty keeps the raw char* of every string it
# is handed (the reason `_retire_current()` exists). Widening them to carry
# `eligible` / `thinking_levels` would put the picker's data on the same
# lifetime as a live dropdown. These dicts are never handed to RNA, so they are
# free to change shape and free to be dropped outright.
_platform_records: list[dict] = []

# Defaults for the six per-model flags, applied when a field is absent.
#
# `platform_available` fails CLOSED (the backend column defaults FALSE and
# backend-authoritative lists never resurrect client-side guesses); everything
# else fails OPEN so an older backend degrades to "offer it" rather than to an
# empty picker. `byok_available` in particular is advisory today — the BYOK save
# endpoints do not refuse a model flagged false.
_RECORD_DEFAULTS = {
    "platform_available": False,
    "byok_available": True,
    "supports_vision": True,
    "eligible": True,
}

# ONE previous generation of item strings, kept alive deliberately.
# Blender's EnumProperty stores the raw char* of the identifier/name/description
# it is handed, not a Python reference. Dropping the last reference to those
# strings while a redraw is mid-flight is a use-after-free, and clear() now runs
# on the same main-thread tick as the logout redraw. Retiring rather than
# freeing gives the outgoing generation one full transition to die out — the
# same reason generation_catalog_cache prunes its enum cache at version - 1
# instead of version.
_retired: list = []

# Set to True once populate() has been called — even with an empty
# providers list. Used to distinguish "haven't fetched yet" from
# "fetched and the backend has nothing".
_populated_once: bool = False


def is_openrouter(provider: str) -> bool:
    """True when ``provider`` is the client-side OpenRouter option."""
    return provider == OPENROUTER_PROVIDER_ID


def is_codex(provider: str) -> bool:
    """True when ``provider`` is the client-side Codex (ChatGPT sub) option."""
    return provider == CODEX_PROVIDER_ID


def is_local(provider: str) -> bool:
    """True when ``provider`` is the client-side Local (this computer) option."""
    return provider == LOCAL_PROVIDER_ID


def get_provider_items() -> list[tuple[str, str, str]]:
    """EnumProperty items for the provider dropdown.

    Always ends with the client-side "OpenRouter", "Codex (ChatGPT sub)" and
    "Local (this computer)" options (none is part of the backend catalog), so a
    user can pick any of them even offline / before the catalog loads. The
    cloud providers come first (the cached catalog list, or a sentinel while it
    loads).
    """
    if _provider_cache:
        cloud = list(_provider_cache)
    elif _populated_once:
        cloud = [PROVIDER_EMPTY_SENTINEL]
    else:
        cloud = [PROVIDER_LOADING_SENTINEL]
    items = list(cloud)
    identifiers = {item[0] for item in items}
    for client_item in (
        OPENROUTER_PROVIDER_ITEM, CODEX_PROVIDER_ITEM, LOCAL_PROVIDER_ITEM,
    ):
        if client_item[0] not in identifiers:
            items.append(client_item)
    return items


def get_model_items(provider: str) -> list[tuple[str, str, str]]:
    """EnumProperty items for the model dropdown, for a given provider.

    Returns the provider's cached models when available; otherwise a
    single sentinel item. Always returns a non-empty list — Blender
    renders a blank/broken dropdown when items is [].

    Codex shows the "openai" group (see _MODEL_SOURCE_PROVIDER).
    """
    cached = _model_cache.get(_MODEL_SOURCE_PROVIDER.get(provider, provider))
    if cached:
        return cached
    return [MODEL_EMPTY_SENTINEL]


def is_valid_model(provider: str, model: str) -> bool:
    """True when *model* is a real cached model for *provider*.

    The ``NONE`` placeholder is intentionally never valid.  Save paths use
    this to reject a stale EnumProperty value left behind by a provider
    switch or catalog refresh.
    """
    if not provider or not model or model == "NONE":
        return False
    source = _MODEL_SOURCE_PROVIDER.get(provider, provider)
    return any(item[0] == model for item in (_model_cache.get(source) or ()))


def get_platform_models() -> list[dict]:
    """Rows for the hosted agent model picker, in SERVER ORDER.

    Filtered to `platform_available` — a model the account can only reach with
    its own key belongs in the BYOK dialog, not in the platform picker.
    Ineligible rows are KEPT: the backend is explicit that they are shown greyed
    rather than hidden, so the user can see what a higher tier would unlock.

    Copies are returned so a caller cannot mutate the cache in place.
    """
    return [dict(record) for record in _platform_records if record["platform_available"]]


def is_loaded() -> bool:
    """True iff populate() has been called at least once, regardless of
    whether it populated any real providers.

    Used to decide "should we trigger another fetch?" — a successful
    fetch that returned an empty list should NOT trigger repeated
    refetches; the backend is authoritative.
    """
    return _populated_once


def populate(providers, models, records=None) -> None:
    """Replace the caches from a successful models-catalog response.

    Args:
        providers: iterable of (id, label, description) tuples — the
            EnumProperty items shape Blender expects. May be empty
            if the backend has no providers enabled.
        models: dict mapping provider_id -> list[(id, label, description)]
            for that provider's models. May be empty.
        records: flat list of per-model dicts in server order, for the hosted
            picker. Optional so the BYOK-only callers (and their tests) keep
            working unchanged; omitting it empties the picker rather than
            leaving the previous account's rows behind.
    """
    global _populated_once
    _retire_current()
    _provider_cache.clear()
    if providers:
        _provider_cache.extend(tuple(p) for p in providers)
    _model_cache.clear()
    if models:
        for provider_id, model_list in models.items():
            _model_cache[provider_id] = [tuple(m) for m in model_list]
    _platform_records.clear()
    if records:
        _platform_records.extend(dict(r) for r in records)
    _populated_once = True


def clear() -> None:
    """Drop all cached data. Called on logout — resets the populated
    flag so the next login triggers a fresh fetch.
    """
    global _populated_once
    _retire_current()
    _provider_cache.clear()
    _model_cache.clear()
    _platform_records.clear()
    _populated_once = False


def _retire_current() -> None:
    """Hold the outgoing item strings for one more transition (see ``_retired``)."""
    _retired.clear()
    _retired.append(list(_provider_cache))
    _retired.append({k: list(v) for k, v in _model_cache.items()})


def populate_from_payload(payload) -> None:
    """Populate from a raw ``GET /agent/models`` payload.

    Shape:
        {"providers": [{"id", "label", "models": [
            {"id", "label", "platform_available", "byok_available",
             "supports_vision", "min_tier", "eligible", "thinking_levels"},
            ...]}, ...]}

    Single writer into the caches, so the disk load and the network refresh can
    never disagree about how a payload is parsed. Unknown/!dict entries are
    skipped rather than raising — the backend is authoritative about which
    options exist, and a malformed row should cost one option, not the dialog.

    Order is the server's and is never re-sorted: `providers` arrives sorted by
    label and each `models` list in the admin-configured `display_order`.
    """
    if not isinstance(payload, dict):
        return

    providers: list[tuple[str, str, str]] = []
    models: dict[str, list[tuple[str, str, str]]] = {}
    records: list[dict] = []

    for entry in payload.get("providers") or []:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("id")
        if not pid:
            continue
        label = entry.get("label") or pid
        # EnumProperty items are (id, label, description); the API gives id +
        # label, so the label doubles as the tooltip.
        providers.append((pid, label, label))

        items: list[tuple[str, str, str]] = []
        for model in entry.get("models") or []:
            if not isinstance(model, dict):
                continue
            mid = model.get("id")
            if not mid:
                continue
            mlabel = model.get("label") or mid
            record = _build_record(pid, label, mid, mlabel, model)
            records.append(record)
            # BYOK's own dropdowns show only what a user key can drive. The
            # flag defaults True, so an older backend that omits it keeps the
            # pre-filter behaviour exactly.
            if record["byok_available"]:
                items.append((mid, mlabel, mlabel))
        models[pid] = items

    populate(providers, models, records)


def _build_record(provider_id, provider_label, model_id, model_label, raw) -> dict:
    """One `get_platform_models()` row from a raw catalog model entry."""
    levels = raw.get("thinking_levels")
    thinking_levels = (
        [level for level in levels if isinstance(level, str) and level]
        if isinstance(levels, list)
        else []
    )
    min_tier = raw.get("min_tier")
    return {
        "provider_id": provider_id,
        "provider_label": provider_label,
        "model_id": model_id,
        "model_label": model_label,
        "platform_available": bool(
            raw.get("platform_available", _RECORD_DEFAULTS["platform_available"])
        ),
        "byok_available": bool(
            raw.get("byok_available", _RECORD_DEFAULTS["byok_available"])
        ),
        "supports_vision": bool(
            raw.get("supports_vision", _RECORD_DEFAULTS["supports_vision"])
        ),
        "min_tier": min_tier if isinstance(min_tier, str) else "",
        "eligible": bool(raw.get("eligible", _RECORD_DEFAULTS["eligible"])),
        "thinking_levels": thinking_levels,
    }
