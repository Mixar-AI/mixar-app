# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Error classification and sanitization for the job queue."""

import re

from mixar.modules.common.api.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConnectionError,
    HTTPClientError,
    InsufficientCreditsError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TimeoutError,
    ValidationError,
)
from mixar.modules.common.i18n import n_

# Substrings in raw error messages that indicate sensitive/internal details.
# Checked case-insensitively.  Order does not matter.  Only words that are
# sensitive on their own belong here — a bare keyword like "token" would also
# swallow benign messages such as "token limit exceeded" (that is why bare
# "token" lives in the credential-shaped regexes below instead).
_SENSITIVE_PATTERNS = (
    "api_key",
    "api key",
    "secret",
    "credentials",
    "password",
    ".env",
    "traceback",
    "file \"/",       # Python traceback paths
    "file \"c:\\",    # Windows traceback paths
)

# Credential-shaped content: the secret itself (provider keys, JWTs, auth
# headers, key=value pairs), not keywords *about* secrets.  A message that
# merely mentions "token" (rate limits, context limits) stays user-visible.
_CREDENTIAL_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),                      # provider API keys
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}"),                       # JWT (base64 {" header)
    re.compile(r"api[_-]?key\s*[=:]\s*\S+", re.IGNORECASE),     # apikey=… / api-key: …
    re.compile(r"bearer\s+[A-Za-z0-9._-]{8,}", re.IGNORECASE),  # Authorization headers
)


# The out-of-credits banner is that failure's notification, so the queue's
# failure toast recognises this exact message and stands down.
OUT_OF_CREDITS_MESSAGE = n_("You're out of credits — upgrade your plan to continue")


def classify_error(error) -> str:
    """Return a user-friendly message for a typed exception, or ``""``."""
    # Check InsufficientCreditsError before its HTTPClientError base.
    if isinstance(error, InsufficientCreditsError):
        return OUT_OF_CREDITS_MESSAGE
    if isinstance(error, AuthenticationError):
        return n_("Authentication required — please sign in")
    if isinstance(error, AuthorizationError):
        return n_("You don't have permission for this action")
    if isinstance(error, RateLimitError):
        return n_("Too many requests — please try again shortly")
    if isinstance(error, ServerError):
        return n_("Server error — please try again")
    if isinstance(error, ValidationError):
        return n_("Invalid request — check your inputs")
    if isinstance(error, NotFoundError):
        return n_("Resource not found")
    if isinstance(error, ConnectionError):
        return n_("Could not connect to server — check your internet")
    if isinstance(error, TimeoutError):
        return n_("Request timed out — please try again")
    if isinstance(error, HTTPClientError):
        return n_("Service error — please try again")
    return ""


def sanitize_message(raw: str, fallback: str = n_("Something went wrong")) -> str:
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
    for pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(raw):
            return fallback
    return raw if len(raw) <= 80 else raw[:77] + "…"
