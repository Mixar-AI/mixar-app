# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
API Client Exceptions

Custom exception hierarchy for REST API error handling.
"""

from typing import Any, Optional


class HTTPClientError(Exception):
    """Base exception for all HTTP client errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Any] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_data = response_data


class ConnectionError(HTTPClientError):
    """Failed to connect to the server."""

    pass


class TimeoutError(HTTPClientError):
    """Request timed out."""

    pass


class AuthenticationError(HTTPClientError):
    """Authentication failed (401)."""

    pass


class AuthorizationError(HTTPClientError):
    """Authorization failed (403)."""

    pass


class NotFoundError(HTTPClientError):
    """Resource not found (404)."""

    pass


class ValidationError(HTTPClientError):
    """Request validation failed (400/422)."""

    pass


class ServerError(HTTPClientError):
    """Server error (5xx)."""

    pass


class RateLimitError(HTTPClientError):
    """Rate limit exceeded (429)."""

    def __init__(
        self,
        message: str,
        retry_after: Optional[float] = None,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
