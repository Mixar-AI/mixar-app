# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update State Manager

Thread-safe singleton that tracks the update lifecycle: *detection*
(:class:`~..constants.UpdateState`) and, independently, *installation*
(:class:`~..constants.InstallState`).  Read from the main thread (UI /
toast renderer) and written from API callbacks and the download thread.

The two states are separate because they answer different questions and
change at different times — a known update stays AVAILABLE while its
installer goes DOWNLOADING → READY → INSTALLING, and a download that
fails must not make the update itself disappear.
"""

import threading
from dataclasses import dataclass
from typing import Optional

from ..constants import InstallState, UpdateState


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
    # Installer artifact — present when the release was published with one
    # for this platform.  Absent means browser-only for this update.
    download_url: str = ""
    download_sha256: str = ""
    download_size: int = 0
    installer_type: str = ""


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
        self._reset_install_locked()

    def _reset_install_locked(self) -> None:
        self._install_state: InstallState = InstallState.IDLE
        self._installer_path: str = ""
        self._install_error: str = ""
        self._blocked_reason: str = ""
        self._downloaded_bytes: int = 0
        self._total_bytes: int = 0
        self._signature_verified: bool = False
        self._install_requested: bool = False

    # ------------------------------------------------------------------
    # Detection (thread-safe reads)
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
            self._reset_install_locked()

    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------

    @property
    def install_state(self) -> InstallState:
        with self._lock:
            return self._install_state

    @property
    def installer_path(self) -> str:
        with self._lock:
            return self._installer_path

    @property
    def install_error(self) -> str:
        with self._lock:
            return self._install_error

    @property
    def blocked_reason(self) -> str:
        """Why this install can't self-update (empty when it can)."""
        with self._lock:
            return self._blocked_reason

    @property
    def signature_verified(self) -> bool:
        with self._lock:
            return self._signature_verified

    @property
    def install_requested(self) -> bool:
        """The user asked to restart before the download had finished."""
        with self._lock:
            return self._install_requested

    @property
    def download_progress(self) -> float:
        """Fraction downloaded in ``0.0..1.0``; ``0.0`` when size is unknown."""
        with self._lock:
            if self._total_bytes <= 0:
                return 0.0
            return min(1.0, self._downloaded_bytes / self._total_bytes)

    @property
    def download_bytes(self) -> tuple:
        with self._lock:
            return self._downloaded_bytes, self._total_bytes

    def set_downloading(self) -> None:
        with self._lock:
            self._install_state = InstallState.DOWNLOADING
            self._install_error = ""
            self._installer_path = ""
            self._downloaded_bytes = 0
            self._total_bytes = 0
            # A restart request belongs to the download it was made during.
            # Carrying one into a fresh download would open the restart
            # prompt without a new click (plan_restart re-sets it after
            # starting a download the user just asked for).
            self._install_requested = False

    def set_download_progress(self, transferred: int, total: int) -> None:
        with self._lock:
            self._downloaded_bytes = transferred
            self._total_bytes = total

    def set_ready(self, installer_path: str, signature_verified: bool) -> None:
        with self._lock:
            self._install_state = InstallState.READY
            self._installer_path = installer_path
            self._signature_verified = signature_verified
            self._install_error = ""

    def set_installing(self) -> None:
        with self._lock:
            self._install_state = InstallState.INSTALLING

    def set_install_failed(self, message: str) -> None:
        with self._lock:
            self._install_state = InstallState.FAILED
            self._install_error = message
            self._installer_path = ""

    def set_install_unsupported(self, reason: str) -> None:
        with self._lock:
            self._install_state = InstallState.UNSUPPORTED
            self._blocked_reason = reason
            self._installer_path = ""

    def set_install_idle(self) -> None:
        with self._lock:
            self._reset_install_locked()

    def set_install_requested(self, requested: bool) -> None:
        with self._lock:
            self._install_requested = requested


def get_update_state() -> UpdateStateManager:
    """Module-level accessor for the update state singleton."""
    return UpdateStateManager()
