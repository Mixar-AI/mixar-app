# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lightweight service for fetching generation metadata (models, styles).

Replaces the per-feature services (ImageGenService, Model3DGenService, etc.)
for the sole purpose of ``GET /models`` and ``GET /styles`` calls used by
bootstrap caches. Actual generation work is handled by the unified
``GenerationQueueService``.
"""

from typing import Optional

from ..constants import APIModule
from ..response import APIResponse
from .base_service import BaseService


class GenerationMetadataService(BaseService):
    """Fetch models / styles metadata for any generation API module."""

    def __init__(self, api_module: APIModule):
        super().__init__()
        self._module = api_module

    @property
    def module(self) -> APIModule:
        return self._module

    def get_models(self) -> APIResponse:
        """GET ``/{module}/models``."""
        return self.get("models")

    def get_styles(self) -> APIResponse:
        """GET ``/{module}/styles``."""
        return self.get("styles")


# ---------------------------------------------------------------------------
# Per-module singletons
# ---------------------------------------------------------------------------

_instances: dict[APIModule, GenerationMetadataService] = {}


def get_generation_metadata_service(
    api_module: APIModule,
) -> GenerationMetadataService:
    """Return a cached singleton for the given API module."""
    svc = _instances.get(api_module)
    if svc is None:
        svc = GenerationMetadataService(api_module)
        _instances[api_module] = svc
    return svc
