# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Auth failure backoff manager for JSON-RPC WebSocket connections.

Extracted from jsonrpc_client.py to keep that file under 500 lines.
Tracks CONFIRMED authentication rejections (the server closed with 4001 or
answered the handshake with NOT_AUTHENTICATED) and decides how fast to
retry and when to give up.

Giving up is reserved for the one case a retry can never fix: the refresh
token itself was rejected (or is gone), so only a fresh login can produce
a token the server will accept. Everything else keeps the loop alive at a
slower cadence — a backend that is mid-restart can answer 4001 while its
database is still unreachable, and a client that stopped reconnecting after
three of those stayed dead once the backend recovered.
"""

from typing import Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class AuthBackoffManager:
    """Manages authentication failure backoff and retry logic."""

    def __init__(
        self,
        max_failures: int = 3,
        backoff_delays: Optional[list[float]] = None,
    ):
        # ``max_failures`` marks where the retry cadence reaches its slowest
        # step; it is NOT a stop condition (see module docstring).
        self._max_failures = max_failures
        self._backoff_delays = backoff_delays or [30.0, 60.0, 60.0]
        self._failure_count = 0
        self._last_failed_token: Optional[str] = None

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def max_failures_reached(self) -> bool:
        return self._failure_count >= self._max_failures

    @property
    def last_failed_token(self) -> Optional[str]:
        return self._last_failed_token

    def reset(self) -> None:
        """Reset backoff state on successful connection."""
        self._failure_count = 0
        self._last_failed_token = None

    def record_failure(self, token: Optional[str]) -> None:
        """Record a CONFIRMED auth rejection with the token that failed."""
        self._failure_count += 1
        self._last_failed_token = token

    def retry_delay(self, default: float) -> float:
        """Delay before the next connect attempt after an auth rejection.

        The first rejection retries on the caller's normal cadence: the
        usual cause is an access token that expired during an outage, and
        the very next attempt refreshes it. Repeated rejections mean the
        refresh did not help, so slow down to the backoff table.
        """
        if self._failure_count <= 1:
            return default
        index = min(self._failure_count - 2, len(self._backoff_delays) - 1)
        return max(default, self._backoff_delays[index])

    def should_stop(self, refresh_retryable: bool) -> bool:
        """Stop reconnecting only when a retry cannot possibly help.

        ``refresh_retryable`` is what the token refresh reported: False
        means the refresh token was rejected or is missing — the user has
        to log in again and the loop must stop and say so. True (transport
        failure, 5xx, a refresh that succeeded but the server still
        rejects) keeps retrying; the backend may simply not be ready yet.
        """
        if self._failure_count == 0:
            return False
        if not refresh_retryable:
            logger.error(
                "Token refresh is not retryable after an auth rejection - "
                "stopping reconnection. Reconnect manually after re-authenticating."
            )
            return True
        if self.max_failures_reached:
            logger.warning(
                f"{self._failure_count} consecutive auth rejections; the "
                f"refresh path is still retryable, so reconnection continues "
                f"at a slower cadence"
            )
        return False
