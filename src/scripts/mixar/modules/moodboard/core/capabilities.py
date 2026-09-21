# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Catalog availability shared by canvas menus and template execution."""


def capability_available(capability: str) -> bool:
    """Fail closed unless the catalog publishes a model for this surface."""
    from mixar.bootstrap.generation_catalog_cache import get_models, get_services

    return any(
        get_models(service.get("key") or "")
        for service in get_services(capability, surface="moodboard")
    )
