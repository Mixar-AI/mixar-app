# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update State Manager

Thread-safe singleton that tracks the current update lifecycle state
and cached update info.  Read from the main thread (UI / toast renderer)
and written from API callbacks.
"""

import threading
from dataclasses import dataclass
from typing import Optional

from ..constants import UpdateState


@dataclass
class UpdateInfo:
    """Parsed payload from the update-check API response."""

    latest_version: str = ""
    current_version: str = ""
    severity: str = "normal"
    force_update: bool = False
    unsupported: bool = False
    changelog_summary: str = ""
    changelog_url: str = ""
    browser_download_url: str = ""


class UpdateStateManager:
    """Thread-safe singleton that owns all mutable update state."""

    _instance: Optional["UpdateStateManager"] = None
    _lock_cls = threading.Lock()

    def __new__(cls) -> "UpdateStateManager":
        with cls._lock_cls:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self) -> None:
        self._lock = threading.Lock()
        self._state: UpdateState = UpdateState.IDLE
        self._update_info: Optional[UpdateInfo] = None
        self._error_message: str = ""

    # ------------------------------------------------------------------
    # Properties (thread-safe reads)
    # ------------------------------------------------------------------

    @property
    def state(self) -> UpdateState:
        with self._lock:
            return self._state

    @property
    def update_info(self) -> Optional[UpdateInfo]:
        with self._lock:
            return self._update_info

    @property
    def error_message(self) -> str:
        with self._lock:
            return self._error_message

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def set_checking(self) -> None:
        with self._lock:
            self._state = UpdateState.CHECKING
            self._error_message = ""

    def set_available(self, info: UpdateInfo) -> None:
        with self._lock:
            self._state = UpdateState.AVAILABLE
            self._update_info = info
            self._error_message = ""

    def set_error(self, message: str) -> None:
        with self._lock:
            self._state = UpdateState.ERROR
            self._error_message = message

    def set_idle(self) -> None:
        with self._lock:
            self._state = UpdateState.IDLE
            self._update_info = None
            self._error_message = ""


def get_update_state() -> UpdateStateManager:
    """Module-level accessor for the update state singleton."""
    return UpdateStateManager()
