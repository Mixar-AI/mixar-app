# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Error classification and sanitization for the job queue."""

from mixar.modules.common.api.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConnectionError,
    HTTPClientError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TimeoutError,
    ValidationError,
)

# Substrings in raw error messages that indicate sensitive/internal details.
# Checked case-insensitively.  Order does not matter.
_SENSITIVE_PATTERNS = (
    "api_key",
    "api key",
    "secret",
    "credentials",
    "password",
    "token",
    ".env",
    "traceback",
    "file \"/",       # Python traceback paths
    "file \"c:\\",    # Windows traceback paths
)


def classify_error(error) -> str:
    """Return a user-friendly message for a typed exception, or ``""``."""
    if isinstance(error, AuthenticationError):
        return "Authentication required — please sign in"
    if isinstance(error, AuthorizationError):
        return "You don't have permission for this action"
    if isinstance(error, RateLimitError):
        return "Too many requests — please try again shortly"
    if isinstance(error, ServerError):
        return "Server error — please try again"
    if isinstance(error, ValidationError):
        return "Invalid request — check your inputs"
    if isinstance(error, NotFoundError):
        return "Resource not found"
    if isinstance(error, ConnectionError):
        return "Could not connect to server — check your internet"
    if isinstance(error, TimeoutError):
        return "Request timed out — please try again"
    if isinstance(error, HTTPClientError):
        return "Service error — please try again"
    return ""


def sanitize_message(raw: str, fallback: str = "Something went wrong") -> str:
    """Scrub sensitive content from a raw error string for UI display.

    Returns *fallback* when *raw* is empty or contains sensitive patterns.
    Otherwise returns the original (truncated to 80 chars for UI rows).
    """
    if not raw:
        return fallback
    lower = raw.lower()
    for pattern in _SENSITIVE_PATTERNS:
        if pattern in lower:
            return fallback
    return raw if len(raw) <= 80 else raw[:77] + "…"
