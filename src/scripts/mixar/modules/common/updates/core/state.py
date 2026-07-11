# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update State Manager

Thread-safe singleton that tracks the current update lifecycle state,
cached download info, and download progress.  Read from the main thread
(UI / toast renderer) and written from background threads (downloader).
"""

import threading
from dataclasses import dataclass, field
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
    download_url: str = ""
    browser_download_url: str = ""
    download_size_bytes: int = 0
    sha256: str = ""
    installer_type: str = ""


@dataclass
class DownloadProgress:
    """Tracks bytes transferred for the in-flight download."""

    total_bytes: int = 0
    downloaded_bytes: int = 0
    speed_bps: float = 0.0

    @property
    def fraction(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(self.downloaded_bytes / self.total_bytes, 1.0)

    @property
    def percent(self) -> float:
        return self.fraction * 100.0


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
        self._progress: DownloadProgress = DownloadProgress()
        self._downloaded_path: Optional[str] = None
        self._error_message: str = ""
        self._cancel_requested: bool = False
        self._download_thread: Optional[threading.Thread] = None

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
    def progress(self) -> DownloadProgress:
        with self._lock:
            return self._progress

    @property
    def downloaded_path(self) -> Optional[str]:
        with self._lock:
            return self._downloaded_path

    @property
    def error_message(self) -> str:
        with self._lock:
            return self._error_message

    @property
    def cancel_requested(self) -> bool:
        with self._lock:
            return self._cancel_requested

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def set_checking(self) -> None:
        with self._lock:
            self._state = UpdateState.CHECKING
            self._error_message = ""
            self._cancel_requested = False

    def set_downloading(self, info: UpdateInfo) -> None:
        with self._lock:
            self._state = UpdateState.DOWNLOADING
            self._update_info = info
            self._progress = DownloadProgress(total_bytes=info.download_size_bytes)
            self._downloaded_path = None
            self._error_message = ""
            self._cancel_requested = False

    def set_ready(self, path: str) -> None:
        with self._lock:
            self._state = UpdateState.READY
            self._downloaded_path = path

    def set_installing(self) -> None:
        with self._lock:
            self._state = UpdateState.INSTALLING

    def set_error(self, message: str) -> None:
        with self._lock:
            self._state = UpdateState.ERROR
            self._error_message = message

    def set_idle(self) -> None:
        with self._lock:
            self._state = UpdateState.IDLE
            self._update_info = None
            self._progress = DownloadProgress()
            self._downloaded_path = None
            self._error_message = ""
            self._cancel_requested = False

    # ------------------------------------------------------------------
    # Download helpers (called from background thread)
    # ------------------------------------------------------------------

    def update_progress(self, downloaded: int, speed: float = 0.0) -> None:
        with self._lock:
            self._progress.downloaded_bytes = downloaded
            self._progress.speed_bps = speed

    def request_cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True

    def set_download_thread(self, thread: Optional[threading.Thread]) -> None:
        with self._lock:
            self._download_thread = thread

    def join_download_thread(self, timeout: float = 2.0) -> None:
        """Wait for the download thread to finish (if running)."""
        with self._lock:
            thread = self._download_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)


def get_update_state() -> UpdateStateManager:
    """Module-level accessor for the update state singleton."""
    return UpdateStateManager()
