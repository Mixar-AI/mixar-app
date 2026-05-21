# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Auth failure backoff manager for JSON-RPC WebSocket connections.

Extracted from jsonrpc_client.py to keep that file under 500 lines.
Handles exponential backoff, stale token detection, and max failure limits.
"""

import time
from typing import Callable, Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class AuthBackoffManager:
    """Manages authentication failure backoff and retry logic.

    Tracks consecutive auth failures, enforces backoff delays, and
    stops reconnection when the token is stale or max failures reached.
    """

    def __init__(
        self,
        max_failures: int = 3,
        backoff_delays: Optional[list[float]] = None,
    ):
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

    def reset(self) -> None:
        """Reset backoff state on successful connection."""
        self._failure_count = 0
        self._last_failed_token = None

    def record_failure(self, token: Optional[str]) -> None:
        """Record an auth failure with the token that failed."""
        self._failure_count += 1
        self._last_failed_token = token

    def should_stop(
        self,
        token_getter: Optional[Callable[[], Optional[str]]],
    ) -> bool:
        """Check if reconnection should stop after backoff.

        Waits for the backoff delay, then checks if the token changed.
        Returns True if reconnection should stop (max failures or stale token).
        """
        if self.max_failures_reached:
            logger.error(
                "Max auth failures reached - stopping reconnection. "
                "Reconnect manually after re-authenticating."
            )
            return True

        delay = self._backoff_delays[
            min(self._failure_count - 1, len(self._backoff_delays) - 1)
        ]
        logger.info(f"Auth backoff: waiting {delay:.0f}s for token refresh...")
        time.sleep(delay)

        # Check if token has changed; if same stale token, stop retrying
        new_token = token_getter() if token_getter else None
        if new_token == self._last_failed_token:
            logger.error(
                "Token unchanged after backoff - stopping reconnection. "
                "Reconnect manually after re-authenticating."
            )
            return True

        return False
