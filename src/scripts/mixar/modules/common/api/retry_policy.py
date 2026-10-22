# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How `HTTPClient` retries, and how it reads a server's requested wait.

**A server header never sets a sleep.** urllib3's `Retry` honours
``Retry-After`` by default: a 413/429/503 carrying it is retried even when
the status is not in ``status_forcelist``, after sleeping the header's FULL
value (``backoff_max`` does not cap it). A BYOK save answered 429 +
``Retry-After: 13996`` (a ChatGPT plan's usage window) slept ~3.9 h on the
dialog's request, which stayed on "Validating with your provider…". So:

- ``respect_retry_after_header=False`` on every `Retry` built here.
- A 429 is not in ``status_forcelist``, so it comes back at once — the
  caller gets `RateLimitError` with the server's message and its wait as
  ``retry_after`` (for display or a caller-owned timer, never slept on here).
- A 503 stays in ``status_forcelist``: a load balancer mid-deploy or a
  restarting service answers 503 for a few seconds, which the exponential
  backoff (0 s, 2 s, 4 s at the defaults; never more than ``backoff_max``)
  rides out. Its ``Retry-After`` is ignored, so a long maintenance wait costs
  the caller those few seconds, not the header's value.
"""

import re
from typing import Any, Mapping, Optional

from urllib3.util.retry import Retry

RETRY_STATUS_CODES = (500, 502, 503, 504)
RETRY_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

_DELTA_SECONDS = re.compile(r"^\s*\d+(\.\d+)?\s*$")


def build_retry(retry_count: int, retry_delay: float) -> Retry:
    """The session's `Retry`: 5xx only, exponential backoff, no ``Retry-After``.

    POST is included so transient 5xx responses on enqueue and other POST
    endpoints are retried. The job-queue enqueue is safe to retry because it
    carries an idempotency key; other POST callers should ensure their
    endpoints are idempotent or guard against duplicate work themselves.

    ``retry_count=0`` means "hand me the 5xx, don't retry it" — for endpoints
    that are expensive, metered or non-idempotent. It must clear
    ``status_forcelist`` rather than just zeroing ``total``: urllib3 counts a
    forced-status response as a retry attempt, so ``Retry(total=0,
    status_forcelist=[500])`` still raises MaxRetryError("too many 500 error
    responses") instead of returning the response, and the server's actual
    error never reaches the caller.
    """
    if retry_count <= 0:
        return Retry(total=0, status_forcelist=[], raise_on_status=False,
                     respect_retry_after_header=False)
    return Retry(
        total=retry_count,
        backoff_factor=retry_delay,
        status_forcelist=list(RETRY_STATUS_CODES),
        allowed_methods=list(RETRY_METHODS),
        respect_retry_after_header=False,
    )


def _seconds(value: Any) -> Optional[float]:
    """A non-negative wait in seconds, or None (absent, an HTTP-date, junk)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    if isinstance(value, str) and _DELTA_SECONDS.match(value):
        return float(value)
    return None


def envelope(data: Any) -> dict:
    """The ``{status, message, data}`` envelope of an error body: under
    ``detail`` when raised as an HTTPException, else the body itself."""
    if not isinstance(data, dict):
        return {}
    detail = data.get("detail")
    return detail if isinstance(detail, dict) else data


def retry_after_seconds(headers: Mapping[str, str], body: Any) -> Optional[float]:
    """A 429's requested wait: the ``Retry-After`` header (delta-seconds),
    else the error envelope's ``retry_after`` or ``data.retry_after_s``;
    None if none.

    An HTTP-date header reads as None rather than raising: a raise inside the
    error mapping turned the 429 into a status-less error that callers
    classify as a network failure.
    """
    wait = _seconds((headers or {}).get("Retry-After"))
    if wait is not None:
        return wait
    body = envelope(body)
    wait = _seconds(body.get("retry_after"))
    data = body.get("data")
    if wait is None and isinstance(data, dict):
        wait = _seconds(data.get("retry_after_s"))
    return wait


def rate_limit_message(data: Any, fallback: str) -> str:
    """A 429's user-facing text: the envelope's ``message``. The backend's
    limiter sends it beside a string ``detail`` (the limit itself, e.g.
    "10 per 1 minute") that the generic mapping would otherwise show."""
    message = envelope(data).get("message")
    return message if isinstance(message, str) and message.strip() else fallback
