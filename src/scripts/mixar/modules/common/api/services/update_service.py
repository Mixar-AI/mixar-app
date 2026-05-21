# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Updates API Service.

Handles /api/v1/updates endpoints for version checking.
"""

from typing import Callable, Optional

from ..constants import APIModule
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService


class UpdateService(BaseService):
    """
    Update service for version checking.

    Endpoints:
    - GET /check - Check for available updates
    """

    @property
    def module(self) -> APIModule:
        return APIModule.UPDATES

    # ========================================================================
    # SYNC METHODS
    # ========================================================================

    def check(
        self,
        platform: str,
        current_version: str,
        channel: str = "stable",
        install_id: str = "",
    ) -> APIResponse:
        """
        Check for available updates.

        Args:
            platform: Platform key (mac, windows, linux)
            current_version: Current app version (X.Y.Z)
            channel: Update channel (stable, beta, etc.)
            install_id: Unique installation identifier

        Returns:
            APIResponse with update info
        """
        params = {
            "platform": platform,
            "current_version": current_version,
            "channel": channel,
        }
        if install_id:
            params["install_id"] = install_id

        return self.get("check", params=params)

    # ========================================================================
    # ASYNC METHODS
    # ========================================================================

    def check_async(
        self,
        platform: str,
        current_version: str,
        channel: str = "stable",
        install_id: str = "",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Check for available updates asynchronously.

        Args:
            platform: Platform key (mac, windows, linux)
            current_version: Current app version (X.Y.Z)
            channel: Update channel (stable, beta, etc.)
            install_id: Unique installation identifier
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        params = {
            "platform": platform,
            "current_version": current_version,
            "channel": channel,
        }
        if install_id:
            params["install_id"] = install_id

        return self.get_async(
            "check",
            params=params,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


# Singleton instance
_update_service: Optional[UpdateService] = None


def get_update_service() -> UpdateService:
    """Get the global UpdateService instance."""
    global _update_service
    if _update_service is None:
        _update_service = UpdateService()
    return _update_service
