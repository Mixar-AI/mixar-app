# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Catalog availability shared by canvas menus and template execution."""


def _enabled(record):
    # Public catalogs normally omit disabled records. Also honor explicit flags
    # in persisted/admin catalog snapshots, without requiring optional fields.
    return record.get("enabled", True) and record.get("is_enabled", True)


def capability_available(capability: str, *, action_type=None) -> bool:
    """Require an enabled model on a service this moodboard action can execute."""
    from mixar.bootstrap.generation_catalog_cache import (
        get_capability, get_models, get_services,
    )

    if not _enabled(get_capability(capability) or {}):
        return False
    services = get_services(capability, surface="moodboard")
    if action_type is not None:
        from .node_schema import services_for_action

        services = services_for_action(action_type, services)
    return any(
        _enabled(service) and any(_enabled(model) and model.get("slug")
                                  for model in get_models(service.get("key") or ""))
        for service in services
    )
