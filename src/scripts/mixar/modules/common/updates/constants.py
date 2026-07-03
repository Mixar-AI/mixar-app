# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Auto-Update System Constants

Configuration values, enums, and file paths for the update checker,
downloader, and installer subsystems.
"""

from enum import Enum


# ============================================================================
# TIMING
# ============================================================================

DEFAULT_CHECK_DELAY_SECONDS = 5
DEFAULT_DOWNLOAD_CHUNK_SIZE = 65536  # 64 KB
DEFAULT_MAX_DOWNLOAD_RETRIES = 3
# Socket timeout for the installer download (connect + each blocking read).
# Without it a stalled CDN connection blocks the download thread forever and
# the DOWNLOADING state permanently suppresses all future update checks.
DOWNLOAD_SOCKET_TIMEOUT_SECONDS = 60

# ============================================================================
# PLATFORM MAPPING
# ============================================================================

PLATFORM_MAP = {
    "darwin": "mac",
    "win32": "windows",
    "win": "windows",
    "linux": "linux",
}

# ============================================================================
# FILE / DIRECTORY NAMES
# ============================================================================

UPDATES_CACHE_DIR = "mixar_updates"
INSTALL_ID_FILENAME = ".mixar_install_id"
SKIPPED_VERSION_FILENAME = ".mixar_skipped_version"

# ============================================================================
# NOTIFICATION
# ============================================================================

UPDATE_NOTIFICATION_ID = "mixar-update"

# ============================================================================
# STATE MACHINE
# ============================================================================


class UpdateState(Enum):
    """Lifecycle states for the auto-update process."""

    IDLE = "idle"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    READY = "ready"
    INSTALLING = "installing"
    ERROR = "error"
