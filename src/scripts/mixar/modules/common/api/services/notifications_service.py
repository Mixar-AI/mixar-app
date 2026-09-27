# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Service for fetching the notification-sound catalog.

Wraps ``GET /api/v1/notifications/sounds`` — the backend-owned list of
task-completion sound options, each carrying an S3 URL to the clip. Keeping
the catalog on the backend lets new sounds ship without a client release.

Supports conditional requests: pass the previously received ``ETag`` via
``etag=`` and the backend answers ``304 Not Modified`` with an empty body
when the catalog is unchanged.
"""

from typing import Optional

from ..constants import APIModule
from ..response import APIResponse
from .base_service import BaseService


class NotificationsService(BaseService):
    """Fetch the notification-sound catalog."""

    @property
    def module(self) -> APIModule:
        return APIModule.NOTIFICATIONS

    def get_sounds(self, etag: Optional[str] = None) -> APIResponse:
        """GET ``/notifications/sounds`` with optional ``If-None-Match``.

        The response body is the house envelope
        ``{"status", "message", "data": {"sounds": [{"id", "label", "url"}, ...]}}``
        where ``url`` is a public/CDN S3 link to the audio clip. On ``304`` the
        response has ``success=True``, ``status_code=304`` and an empty body —
        callers keep their cached payload.
        """
        headers = {"If-None-Match": etag} if etag else None
        return self.get("/sounds", headers=headers)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[NotificationsService] = None


def get_notifications_service() -> NotificationsService:
    """Return the cached singleton service instance."""
    global _instance
    if _instance is None:
        _instance = NotificationsService()
    return _instance
