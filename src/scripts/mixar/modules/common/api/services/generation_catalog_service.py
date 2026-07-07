# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Service for fetching the unified generation catalog.

Wraps ``GET /api/v1/generation-catalog`` — the DB-driven catalog of
generation capabilities, services, models, parameter schemas, styles and
credit costs that powers the dynamic moodboard panels.

Supports conditional requests: pass the previously received ``ETag`` value
via ``etag=`` and the backend answers ``304 Not Modified`` with an empty
body when the catalog is unchanged.
"""

from typing import Optional

from ..constants import APIModule
from ..response import APIResponse
from .base_service import BaseService


class GenerationCatalogService(BaseService):
    """Fetch the unified generation catalog."""

    @property
    def module(self) -> APIModule:
        return APIModule.GENERATION_CATALOG

    def get_catalog(self, etag: Optional[str] = None) -> APIResponse:
        """GET ``/generation-catalog`` with optional ``If-None-Match``.

        Returns the standard :class:`APIResponse`. On ``304`` the response
        has ``success=True``, ``status_code=304`` and an empty body —
        callers should keep their cached payload.
        """
        headers = {"If-None-Match": etag} if etag else None
        return self.get("", headers=headers)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[GenerationCatalogService] = None


def get_generation_catalog_service() -> GenerationCatalogService:
    """Return the cached singleton service instance."""
    global _instance
    if _instance is None:
        _instance = GenerationCatalogService()
    return _instance
