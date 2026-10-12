# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scrub secrets from log text.

Applied twice: by the client log file's formatter (``logging_config``), so the
file on disk never holds a raw secret, and to every text file a support bundle
ships (``space_mixie_chat/core/support_bundle.py``), which also covers logs
written before this filter existed. Log lines are free text: a ``requests``
exception names the full URL (S3 presigned signatures included), a FastAPI 422
``detail`` list echoes the request body (Pydantic ``'input'``: a password, a
BYOK key, a refresh token), and an open-URL failure names a handoff ticket.
The patterns are deliberately broad: a redacted false positive costs a support
engineer one value, a leaked token costs the user their account.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_QUERY_KEYS = (
    "x-amz-signature|x-amz-credential|x-amz-security-token|x-goog-signature"
    "|x-goog-credential|signature|policy|key-pair-id|awsaccesskeyid"
    "|access_token|refresh_token|id_token|token|ticket|api_key|apikey|key"
    "|code|code_verifier|state|password"
)
_SECRET_KEYS = (
    "access_token|refresh_token|id_token|api_key|apikey|password|passwd"
    "|secret|client_secret|authorization|token|ticket|auth_json|codex_bundle"
)

_PATTERNS = (
    # Authorization headers and bare bearer tokens.
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + REDACTED),
    # JSON Web Tokens (access / refresh / id tokens).
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), REDACTED),
    # Provider API keys: OpenAI / Anthropic / OpenRouter (sk-), Google (AIza),
    # Groq (gsk_), xAI (xai-).
    (re.compile(r"\b(?:sk-|gsk_|xai-)[A-Za-z0-9_-]{12,}|\bAIza[A-Za-z0-9_-]{20,}"), REDACTED),
    # Credentials and signatures in URL query strings (presigned URLs, tickets).
    (re.compile(r"(?i)([?&](?:" + _QUERY_KEYS + r")=)[^&\s\"'<>]+"), r"\1" + REDACTED),
    # Pydantic validation errors echo the rejected input verbatim.
    (re.compile(r"""(?i)(['"]input['"]\s*:\s*)('[^']*'|"[^"]*"|\{[^}]*\}|[^,}\]]+)"""),
     r"\1" + "'" + REDACTED + "'"),
    # Secret-looking keys in JSON / Python reprs / key=value pairs.
    (re.compile(r"(?i)([\"']?\b(?:" + _SECRET_KEYS + r")[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}&]{4,}"),
     r"\1" + REDACTED),
)


def redact_text(text: str) -> str:
    """``text`` with every secret-shaped value replaced by ``[REDACTED]``."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
