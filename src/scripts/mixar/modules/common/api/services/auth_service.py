# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Authentication API Service.

Handles /api/v1/auth endpoints.
"""

from typing import Callable, Optional

from ..constants import APIModule
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService


class AuthService(BaseService):
    """
    Authentication service for user management.

    Endpoints:
    - GET /me - Get current user info
    - POST /login - Login with credentials
    - POST /logout - Logout current session
    - POST /refresh - Refresh access token
    """

    @property
    def module(self) -> APIModule:
        return APIModule.AUTHENTICATION

    # ========================================================================
    # SYNC METHODS
    # ========================================================================

    def get_current_user(self) -> APIResponse:
        """
        Get current authenticated user info.

        Returns:
            APIResponse with user data including email, credits, etc.
        """
        return self.get("me")

    def login(self, email: str, password: str) -> APIResponse:
        """
        Login with email and password.

        Args:
            email: User email
            password: User password

        Returns:
            APIResponse with access token
        """
        return self.post("login", json={"email": email, "password": password})

    def logout(self) -> APIResponse:
        """Logout current session."""
        return self.post("logout")

    def refresh_token(self, refresh_token: str) -> APIResponse:
        """
        Refresh access token.

        Args:
            refresh_token: Refresh token

        Returns:
            APIResponse with new access token
        """
        return self.post("refresh", json={"refresh_token": refresh_token})

    # ========================================================================
    # ASYNC METHODS
    # ========================================================================

    def get_current_user_async(
        self,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Get current authenticated user info asynchronously.

        Args:
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        return self.get_async(
            "me",
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def login_async(
        self,
        email: str,
        password: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Login with email and password asynchronously.

        Args:
            email: User email
            password: User password
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        return self.post_async(
            "login",
            json={"email": email, "password": password},
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


# Singleton instance
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get the global AuthService instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
