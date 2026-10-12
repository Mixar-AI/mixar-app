# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bug-report diagnostics — ``/api/v1/contact``.

``POST bug-report/bundle`` stages the support bundle (a zip) for the signed-in
user and returns ``{"report_id", "size_bytes"}``. The report itself is
submitted from the website's ``/bug-report`` form, which carries the
``report_id``; the backend attaches the zip to the team's bug-report email and
deletes it afterwards (or after 24 hours if no report claims it).

Async only; the shared request queue delivers callbacks on the main thread.
"""

from typing import Callable, Optional

from ..constants import APIModule
from ..response import APIResponse
from .base_service import BaseService


class ContactService(BaseService):
    """Client for the bug-report diagnostics upload."""

    @property
    def module(self) -> APIModule:
        return APIModule.CONTACT

    def upload_bug_report_bundle_async(
        self,
        *,
        content_length: int,
        body_factory: Callable[[], object],
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        timeout: float = 120.0,
    ) -> str:
        """Stream one support-bundle zip. ``body_factory`` runs on the worker
        thread and is called again after an auth refresh."""
        return self.post_async(
            "bug-report/bundle",
            data_factory=body_factory,
            headers={
                "Content-Type": "application/zip",
                "Content-Length": str(max(0, int(content_length))),
            },
            timeout=timeout,
            on_success=on_success,
            on_error=on_error,
        )


_instance: Optional[ContactService] = None


def get_contact_service() -> ContactService:
    """Cached singleton."""
    global _instance
    if _instance is None:
        _instance = ContactService()
    return _instance
