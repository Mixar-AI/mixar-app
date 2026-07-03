# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Capability mode-selector helpers.

A "mode" is one service of a catalog capability surfaced in a moodboard tab
(e.g. capability ``model_gen`` → services ``model_3d`` / ``image_to_3d`` /
``hunyuan_rapid``). This module provides:

- ``get_service_enum_items()`` — EnumProperty items for a capability's
  services (the Mode dropdown), with the same LOADING/ERROR placeholder
  states as the catalog cache's model/style enum helpers.
- ``resolve_service_key()`` — maps a tab's current mode enum value to a
  valid service key (falling back to the capability's first service).
- ``draw_capability_selector()`` — renders the Mode dropdown (hidden when
  the capability has a single service), the Model dropdown (optionally
  with a refresh button) and the selected model's schema params. Returns
  False when the catalog isn't loaded so callers can fall back to their
  legacy hardcoded UI.

These are catalog *queries* layered on the public accessors of
``mixar.bootstrap.generation_catalog_cache`` — kept here (not in the
bootstrap module) to respect the 500-line file budget there.
"""

from typing import List, Optional, Tuple

from .draw import draw_service_params

# Enum identifiers that are placeholder states, never real catalog keys.
PLACEHOLDER_IDS = ("LOADING", "ERROR", "NONE", "")

_LOADING_ITEM = ("LOADING", "Loading...", "Fetching generation catalog")


def get_service_enum_items(
    capability_key: str, surface: str = "moodboard"
) -> List[Tuple[str, str, str]]:
    """(id, label, desc) tuples for a capability's services (Mode dropdown),
    with LOADING/ERROR placeholder states matching the catalog cache."""
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_cache_error,
            get_services,
            is_cache_loading,
            is_loaded,
        )
    except ImportError:
        return [_LOADING_ITEM]

    if not is_loaded():
        if is_cache_loading():
            return [_LOADING_ITEM]
        error = get_cache_error()
        if error:
            return [("ERROR", "Error", error)]
        return [_LOADING_ITEM]

    services = get_services(capability_key, surface=surface)
    items = []
    for svc in services:
        key = svc.get("key") or ""
        if not key:
            continue
        label = svc.get("label") or key
        items.append((key, label, label))
    return items or [("NONE", "No modes", "No services available")]


def resolve_service_key(
    capability_key: str, selected: str, surface: str = "moodboard"
) -> Optional[str]:
    """Map a mode enum value to a valid service key.

    Returns *selected* when it names one of the capability's services, the
    first service otherwise (placeholder values like LOADING resolve to the
    first service too), or None when the catalog has no services for the
    capability (not loaded / capability disabled).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import get_services
    except ImportError:
        return None
    services = get_services(capability_key, surface=surface)
    keys = [s.get("key") for s in services if s.get("key")]
    if not keys:
        return None
    if selected in keys:
        return selected
    return keys[0]


def resolve_model_slug(
    service_key: str, selected: str, fallback: str = ""
) -> str:
    """Map a model enum value to a valid model slug for *service_key*.

    Returns *selected* when it names one of the service's catalog models,
    the service's default model otherwise, and *fallback* when the catalog
    isn't loaded (or has no models for the service).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_default_model_slug,
            get_model,
        )
        slug = selected or ""
        if slug in PLACEHOLDER_IDS or get_model(service_key, slug) is None:
            slug = get_default_model_slug(service_key) or ""
        if slug and slug not in PLACEHOLDER_IDS:
            return slug
    except Exception:
        pass
    return fallback


def get_param_enum_items(
    service_key: str,
    model_slug: str,
    param_name: str,
    fallback=(),
) -> List[Tuple[str, str, str]]:
    """(id, label, desc) tuples for one enum-typed schema param of a
    catalog model (``choices`` or ``enum`` spec forms), *fallback* when
    the catalog / model / param is unavailable.

    Used by legacy enum properties (e.g. the offline aspect-ratio /
    resolution dropdowns) that mirror a schema param outside the dynamic
    param engine.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model

        model = get_model(service_key, model_slug)
        spec = ((model or {}).get("parameters") or {}).get(param_name) or {}
        choices = spec.get("choices") or [
            {"value": v, "label": str(v)} for v in (spec.get("enum") or [])
        ]
        items = []
        for choice in choices:
            value = choice.get("value")
            if value is None:
                continue
            ident = str(value)
            label = str(choice.get("label") or ident)
            items.append((ident, label, label))
        if items:
            return items
    except Exception:
        pass
    return list(fallback)


def _dropdown(layout, data, prop, text):
    """Enum prop via the Mixar styled dropdown when available."""
    if hasattr(layout, "mixar_dropdown"):
        layout.mixar_dropdown(data, prop, text=text)
    else:
        layout.prop(data, prop, text=text)


def draw_capability_selector(
    layout,
    data,
    capability_key: str,
    *,
    mode_prop: str = "mode",
    model_prop: str = "model",
    surface: str = "moodboard",
    model_refresh_op: Optional[str] = None,
) -> bool:
    """Render Mode dropdown → Model dropdown → schema params into *layout*.

    *data* is the tab PropertyGroup owning the mode/model EnumProperties.
    The Mode dropdown is hidden when the capability has exactly one
    service. When *model_refresh_op* is given, a refresh button is drawn
    next to the Model dropdown. Returns False when the catalog isn't
    loaded (or the capability has no services) so the caller can fall
    back to its legacy UI.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_services,
            is_loaded,
        )
    except ImportError:
        return False
    if not is_loaded():
        return False
    services = get_services(capability_key, surface=surface)
    if not services:
        return False

    if len(services) > 1:
        _dropdown(layout, data, mode_prop, "Mode")

    if model_refresh_op:
        row = layout.row(align=True)
        _dropdown(row, data, model_prop, "Model")
        row.operator(model_refresh_op, text="", icon='FILE_REFRESH')
    else:
        _dropdown(layout, data, model_prop, "Model")

    service_key = resolve_service_key(
        capability_key, getattr(data, mode_prop, ""), surface=surface
    )
    model_slug = getattr(data, model_prop, "")
    if service_key and model_slug and model_slug not in PLACEHOLDER_IDS:
        draw_service_params(layout, service_key, model_slug)
    return True
