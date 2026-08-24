# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only typed queries over the cached generation catalog payload."""

from typing import Any, Callable, Dict, List, Optional


CatalogSnapshot = Callable[[], Optional[Dict[str, Any]]]


class GenerationCatalogQueries:
    """Typed catalog lookups backed by an atomic payload snapshot callback."""

    def __init__(self, snapshot: CatalogSnapshot):
        self._snapshot = snapshot

    def get_capabilities(self) -> List[Dict[str, Any]]:
        catalog = self._snapshot() or {}
        capabilities = catalog.get("capabilities") or []
        return sorted(
            capabilities,
            key=lambda capability: capability.get("sort_order", 0),
        )

    def get_capability(
        self, capability_key: str,
    ) -> Optional[Dict[str, Any]]:
        for capability in self.get_capabilities():
            if capability.get("key") == capability_key:
                return capability
        return None

    def get_capability_label(
        self, capability_key: str, default: str,
    ) -> str:
        """Capability label for UI surfaces (e.g. sidebar tab names).

        Returns ``default`` when the catalog isn't loaded, the key is
        absent, or the payload's label is empty/malformed.
        """
        capability = self.get_capability(capability_key) or {}
        label = capability.get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()
        return default

    def get_capability_for_service(
        self, service_key: str,
    ) -> Optional[Dict[str, Any]]:
        for capability in self.get_capabilities():
            if any(
                service.get("key") == service_key
                for service in (capability.get("services") or [])
            ):
                return capability
        return None

    def get_services(
        self, capability_key: str, surface: str = "moodboard",
    ) -> List[Dict[str, Any]]:
        capability = self.get_capability(capability_key)
        if not capability:
            return []
        services = [
            service
            for service in (capability.get("services") or [])
            if not surface or service.get("surface") == surface
        ]
        return sorted(
            services,
            key=lambda service: service.get("sort_order", 0),
        )

    def get_service(self, service_key: str) -> Optional[Dict[str, Any]]:
        for capability in self.get_capabilities():
            for service in capability.get("services") or []:
                if service.get("key") == service_key:
                    return service
        return None

    def get_models(self, service_key: str) -> List[Dict[str, Any]]:
        service = self.get_service(service_key)
        if not service:
            return []
        return service.get("models") or []

    def get_model(
        self, service_key: str, slug: str,
    ) -> Optional[Dict[str, Any]]:
        for model in self.get_models(service_key):
            if model.get("slug") == slug:
                return model
        return None

    def get_default_model_slug(self, service_key: str) -> Optional[str]:
        models = self.get_models(service_key)
        for model in models:
            if model.get("is_default"):
                return model.get("slug")
        if models:
            return models[0].get("slug")
        return None

    def get_styles(self, generation_type: str) -> List[Dict[str, Any]]:
        catalog = self._snapshot() or {}
        styles = (catalog.get("styles") or {}).get(generation_type)
        return styles or []

    def get_credit_cost(self, feature_key: str) -> Optional[int]:
        catalog = self._snapshot() or {}
        costs = catalog.get("credit_costs") or {}
        return costs.get(feature_key)

    def resolve_generate_cost(
        self,
        service_key: str = "",
        model_slug: str = "",
        feature_key: str = "",
    ) -> Optional[int]:
        """Billed credit cost for the Generate button, or None if unknown.

        Prefers the selected model's catalog ``credit_cost``, then the
        service row, then the ``credit_costs`` map keyed by feature_key.
        Catalog values are the billed amount (markup already applied).
        """
        if service_key:
            if model_slug:
                model = self.get_model(service_key, model_slug)
                cost = _positive_int((model or {}).get("credit_cost"))
                if cost is not None:
                    return cost
            service = self.get_service(service_key)
            if service:
                cost = _positive_int(service.get("credit_cost"))
                if cost is not None:
                    return cost
                feature_key = feature_key or (service.get("feature_key") or "")
        if feature_key:
            return _positive_int(self.get_credit_cost(feature_key))
        return None


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
