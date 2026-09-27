# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One explanation for every failed generation, whatever failed.

A failed job carries four client-side facts, filled from whichever layer
failed:

- ``user_message`` — one readable sentence (the backend's class sentence, or
  the backend's HTTP ``detail`` for a rejected submit).
- ``error_reason`` — the provider's / backend's OWN words (the job queue's
  redacted ``error_reason``, a rejected submit's ``detail``, a local exception).
- ``error_class`` — the backend ``ProviderErrorClass`` value, or a client
  class (``credits``, ``auth``, ``network``, ``download``, ``import``,
  ``timeout``, ``client``); drives the "what to do" hint.
- ``vendor_code`` — the provider's error code, for support.

``error`` keeps the raw local string for logs and the copy-details action.
Every display surface (toasts, queue rows, the Agent island Queue tab, graph
nodes, the agent callback) reads these through :func:`failure_headline`,
:func:`failure_hint` and :func:`failure_details` so they can never disagree.
"""

from __future__ import annotations

import re

from .error_helpers import _CREDENTIAL_PATTERNS

REASON_MAX_CHARS = 500

#: error_class -> (short status word, what the user can do about it).
_CLASS_TEXT = {
    "invalid_input": ("Input rejected", "Check the input image/model and settings, then try again."),
    "content_policy": ("Blocked by content policy", "Change the prompt or reference image and try again."),
    "rate_limited": ("Service busy", "The provider is at capacity. Try again in a minute."),
    "vendor_transient": ("Provider error", "A temporary provider error. Try again."),
    "vendor_down": ("Provider unavailable", "The provider is unavailable right now. Try again later."),
    "platform_config": ("Service misconfigured", "This is on our side and the team has been notified."),
    "unknown": ("Failed", "Try again. If it keeps failing, copy the details and send them to support."),
    "credits": ("Out of credits", "Add credits or upgrade your plan, then try again."),
    "auth": ("Sign-in required", "Sign in again, then retry."),
    "permission": ("Not allowed", "Your plan or account cannot use this generation."),
    "network": ("Connection problem", "Check your internet connection and try again."),
    "timeout": ("Timed out", "The generation took too long. Try again."),
    "download": ("Download failed", "The generation finished but its result could not be downloaded. Retry."),
    "import": ("Import failed", "The result downloaded but could not be imported into the scene."),
    "client": ("Failed", "Check the inputs and try again."),
    "cancelled": ("Cancelled", ""),
}

#: Classes only the backend assigns: its terminal FAIL always refunds
#: (job_queue failure routing). Client-side classes are excluded on purpose —
#: a client poll timeout cancels a dispatched job, which is NOT refunded.
_REFUNDED_CLASSES = frozenset(
    {"invalid_input", "content_policy", "rate_limited", "vendor_transient",
     "vendor_down", "platform_config", "unknown"}
)

_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:home|Users|root|tmp|var|private|opt)/)[^\s\"',)]+")
_URL = re.compile(r"(https?://[^/\s\"'<>]+)[^\s\"'<>]*")


def clean_reason(raw) -> str:
    """Display-safe copy of a failure reason (never truncated below 500 chars).

    The backend already redacts ``error_reason``; this is the client's second
    line of defence for text that never went through it — submit ``detail``
    strings from older backends and local exception text.
    """
    if raw is None:
        return ""
    if isinstance(raw, dict):
        raw = raw.get("message") or raw.get("detail") or raw.get("error") or ""
    text = str(raw).strip()
    if not text:
        return ""
    cut = text.find("Traceback (most recent call last)")
    if cut >= 0:
        text = text[:cut]
    for pattern in _CREDENTIAL_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = _URL.sub(r"\1/…", text)
    text = _PATH.sub("[path]", text)
    text = " ".join(text.split())
    if len(text) > REASON_MAX_CHARS:
        text = text[: REASON_MAX_CHARS - 1].rstrip() + "…"
    return text


def apply_backend_failure(job, data: dict) -> None:
    """Record the job queue's failure fields from a client view / WS push.

    Missing keys are ignored (older backends send only ``error``).
    """
    if not isinstance(data, dict):
        return
    if data.get("error_class"):
        job.error_class = str(data["error_class"])
    reason = clean_reason(data.get("error_reason"))
    if reason:
        job.error_reason = reason
    if data.get("vendor_code"):
        job.vendor_code = str(data["vendor_code"])[:64]


def backend_failure_message(data: dict, default: str) -> str:
    """The sentence to show for a backend FAILED snapshot.

    ``user_message`` if the backend sent one, else its ``error`` (the
    job queue's per-class, client-safe sentence), else *default*.
    """
    for key in ("user_message", "error"):
        text = clean_reason(data.get(key))
        if text:
            return text
    return default


def _exception_class(error) -> str:
    from mixar.modules.common.api.exceptions import (
        AuthenticationError,
        AuthorizationError,
        ConnectionError as APIConnectionError,
        InsufficientCreditsError,
        RateLimitError,
        ServerError,
        TimeoutError as APITimeoutError,
        ValidationError,
    )

    if isinstance(error, InsufficientCreditsError):
        return "credits"
    if isinstance(error, AuthenticationError):
        return "auth"
    if isinstance(error, AuthorizationError):
        detail = str(getattr(error, "message", "") or "").lower()
        return "content_policy" if "content_policy" in detail or "policy" in detail else "permission"
    if isinstance(error, RateLimitError):
        return "rate_limited"
    if isinstance(error, ValidationError):
        return "invalid_input"
    if isinstance(error, ServerError):
        return "vendor_transient"
    if isinstance(error, (APIConnectionError, APITimeoutError)):
        return "network"
    return "client"


def apply_client_failure(job, error, *, stage: str = "submit", message: str = "") -> None:
    """Record a failure raised on this machine (submit/poll/download/import).

    The HTTP layer keeps the backend's ``detail`` in ``error.message``: that
    text IS the backend's reason ("Prompt was rejected: …", "Model X does not
    accept 5 reference images"), so it becomes both the sentence and the
    reason instead of a fixed per-status string.
    """
    from .error_helpers import classify_error

    job.error = str(error)
    if stage in ("download", "import", "timeout"):
        job.error_class = stage
    else:
        job.error_class = _exception_class(error)
    detail = clean_reason(getattr(error, "message", None) or str(error))
    job.error_reason = detail
    generic = classify_error(error)
    if message:
        job.user_message = message
    elif job.error_class in ("credits", "auth"):
        job.user_message = generic
    elif detail:
        job.user_message = detail
    else:
        job.user_message = generic or "Generation failed"


def failure_headline(job) -> str:
    """Short status word for a failed row ("Blocked by content policy")."""
    cls = getattr(job, "error_class", "") or ""
    if cls in _CLASS_TEXT:
        return _CLASS_TEXT[cls][0]
    return "Failed"


def failure_hint(job) -> str:
    """What the user can do next (and whether the credits came back)."""
    cls = getattr(job, "error_class", "") or ""
    hint = _CLASS_TEXT.get(cls or "unknown", _CLASS_TEXT["unknown"])[1]
    # Only a class the backend stamped proves the backend failed it.
    if cls in _REFUNDED_CLASSES and hint:
        hint += " Credits for this generation were refunded."
    return hint


def failure_message(job) -> str:
    """The one line every surface shows first."""
    return (
        clean_reason(getattr(job, "user_message", ""))
        or clean_reason(getattr(job, "error_reason", ""))
        or clean_reason(getattr(job, "error", ""))
        or "Generation failed"
    )


def failure_reason(job) -> str:
    """The provider/backend's own words, when they add to the message."""
    reason = clean_reason(getattr(job, "error_reason", ""))
    if not reason:
        return ""
    message = failure_message(job)
    if reason == message or reason in message:
        return ""
    return reason


def failure_details(job, *, include_ids: bool = True) -> str:
    """Multi-line explanation for tooltips, toasts and the copy action."""
    lines = [failure_message(job)]
    reason = failure_reason(job)
    if reason:
        lines.append(f"Reason: {reason}")
    hint = failure_hint(job)
    if hint:
        lines.append(hint)
    if include_ids:
        ids = []
        cls = getattr(job, "error_class", "")
        if cls:
            ids.append(f"type {cls}")
        code = getattr(job, "vendor_code", "")
        if code:
            ids.append(f"provider code {code}")
        backend_id = getattr(job, "backend_job_id", "")
        if backend_id:
            ids.append(f"job {backend_id}")
        if ids:
            lines.append("Support: " + " · ".join(ids))
    return "\n".join(lines)
