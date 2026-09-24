# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Which catalog models the Character Sheet to 3D workflow builds with.

The workflow wires a sheet into Generate Image cards and their results into
Generate-to-3D cards, so it is only offered when both ends publish an IMAGE
input socket. A capability that exists but cannot take the sheet would make
every build roll back, so the gate reads the same socket contract the cards
are built from.

Pure catalog reads: safe in menu draws, never cached (a catalog swap must
reach the menus immediately).
"""

from __future__ import annotations

from collections import namedtuple

from .capabilities import _enabled
from .node_schema import build_input_contract, services_for_action

Preflight = namedtuple(
    "Preflight", "image_slug image_socket_count model3d_service model3d_slug"
)

# The workflow's reference cards run the plain image service; its run path
# (and the MASK_DETAIL cards) key on this exact service.
IMAGE_SERVICE_KEY = 'image_gen'
# Preferred for every reference card: the edit-precision gpt-image model keeps
# a sheet's design most faithfully. Used only while the catalog publishes it
# enabled with reference inputs; otherwise the catalog decides as before.
PREFERRED_IMAGE_SLUG = 'gpt-image-2.5-sunburst'


def image_socket_count(service: dict, model: dict) -> int:
    """How many IMAGE inputs a card on this (service, model) would mint."""
    contract = build_input_contract(service, model)
    return sum(1 for socket in contract["sockets"] if "IMAGE" in socket["accepted_types"])


def _reference_capacity(service: dict, model: dict) -> int:
    """Sheets a Generate Image card can actually send.

    The run refuses more references than the model's ``max_reference_images``
    (fail closed when it is absent), so a socket the model cannot use counts
    for nothing here either.
    """
    try:
        limit = int(model.get("max_reference_images") or 0)
    except (TypeError, ValueError, OverflowError):
        limit = 0
    return min(image_socket_count(service, model), max(limit, 0))


def _enabled_models(service_key: str, get_models) -> list:
    return [
        model for model in get_models(service_key)
        if _enabled(model) and model.get("slug")
    ]


def _ordered_models(service_key: str, get_models, get_default_model_slug) -> list:
    """The service's enabled models, its catalog default first."""
    models = _enabled_models(service_key, get_models)
    default = get_default_model_slug(service_key) or ""
    return sorted(models, key=lambda model: model.get("slug") != default)


def _image_side(catalog):
    services = [
        service for service in services_for_action('IMAGE_GEN', catalog.get_services('image_gen'))
        if service.get("key") == IMAGE_SERVICE_KEY and _enabled(service)
    ]
    if not services:
        return None
    service = services[0]
    default = catalog.get_default_model_slug(IMAGE_SERVICE_KEY) or ""
    ranked = [
        (model["slug"], _reference_capacity(service, model))
        for model in _enabled_models(IMAGE_SERVICE_KEY, catalog.get_models)
    ]
    # The preferred model, then the catalog default, when it takes references
    # at all; otherwise the model that takes the most (ties keep catalog order).
    capacity = dict(ranked)
    if capacity.get(PREFERRED_IMAGE_SLUG, 0) > 0:
        return PREFERRED_IMAGE_SLUG, capacity[PREFERRED_IMAGE_SLUG]
    if capacity.get(default, 0) > 0:
        return default, capacity[default]
    best = max(ranked, key=lambda entry: entry[1], default=None)
    if best is None or best[1] <= 0:
        return None
    return best


def _model3d_side(catalog):
    services = services_for_action('MODEL_3D', catalog.get_services('model_gen'))
    for service in services:
        key = str(service.get("key") or "")
        if not key or not _enabled(service):
            continue
        for model in _ordered_models(key, catalog.get_models, catalog.get_default_model_slug):
            if image_socket_count(service, model) > 0:
                return key, model["slug"]
    return None


def preflight() -> Preflight | None:
    """The models a workflow build would use, or None when it cannot wire."""
    from mixar.bootstrap import generation_catalog_cache as catalog

    image = _image_side(catalog)
    if image is None:
        return None
    model3d = _model3d_side(catalog)
    if model3d is None:
        return None
    return Preflight(image[0], image[1], model3d[0], model3d[1])
