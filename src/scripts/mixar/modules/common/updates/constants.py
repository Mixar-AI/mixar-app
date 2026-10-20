# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Auto-Update System Constants

Configuration values, enums, and file paths for the update checker and
the in-app installer.

Updating is **self-installing**: the client downloads the release
installer in the background, verifies it, and — on one click — quits,
applies the update and relaunches.  The browser downloads page stays as
the fallback for platforms/installations that cannot self-install.
"""

from enum import Enum

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

INSTALL_ID_FILENAME = ".mixar_install_id"
# Records that a version has already been announced in a toast, so the
# announcement happens once rather than on every launch. Not a user
# decision — the topbar badge keeps carrying the update either way.
ANNOUNCED_VERSION_FILENAME = ".mixar_announced_version"

# Staging directory (installer + helper script + logs) created under the
# platform root resolved by ``core/staging.py``.
STAGING_DIR_NAME = "Updates"
STAGING_VENDOR_DIR = "Mixar"

# Name of the log the update helper writes next to the installer.  The
# helper runs after Blender is gone, so this file is the only record of
# what happened — never route it to the app log.
HELPER_LOG_NAME = "update.log"

# Written by the helper once it is done.  The relaunched app reads it to
# report an update that did not finish — otherwise a failed install is
# completely silent.
HELPER_RESULT_NAME = "update-result.txt"

# Verbose Windows Installer log (``/l*v``), next to the helper log. The
# helper moves the previous attempt's to MSI_PREV_LOG_NAME right before it
# runs the installer again.
MSI_LOG_NAME = "msi-install.log"
MSI_PREV_LOG_NAME = "msi-install.prev.log"

# The logs are evidence of a failed attempt and are never purged.
# update.log is appended to by every attempt, so once it grows past the
# first size it is cut back to its last HELPER_LOG_KEEP_BYTES.
HELPER_LOG_MAX_BYTES = 1024 * 1024
HELPER_LOG_KEEP_BYTES = 256 * 1024

# ============================================================================
# NOTIFICATION
# ============================================================================

UPDATE_NOTIFICATION_ID = "mixar-update"

# ============================================================================
# OPERATORS
# ============================================================================

OP_CHECK_FOR_UPDATES = "mixar.check_for_updates"
OP_RESTART_TO_UPDATE = "mixar.restart_to_update"
OP_CANCEL_UPDATE_DOWNLOAD = "mixar.cancel_update_download"
OP_CANCEL_UPDATE_WAIT = "mixar.cancel_update_wait"

# ============================================================================
# URLS
# ============================================================================

# Public downloads page — where the update toast's [Download] button goes
# when the backend doesn't supply a per-release browser URL.
# Overridable at runtime via mixar.json ("updates" -> "downloads_url").
DOWNLOADS_PAGE_URL = "https://www.mixar.app/downloads"

# ============================================================================
# DOWNLOAD POLICY
# ============================================================================

# Installers are 400 MB-plus, so the budget is generous — but bounded, or a
# trickling transfer holds a thread and a half-written file forever.
DOWNLOAD_TOTAL_DEADLINE_S = 3600.0
DOWNLOAD_SOCKET_TIMEOUT_S = 60.0
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DOWNLOAD_MAX_ATTEMPTS = 3
DOWNLOAD_RETRY_BACKOFF_S = 3.0
DOWNLOAD_RETRY_BACKOFF_FACTOR = 3.0
# How often the download thread reports progress to the state singleton.
DOWNLOAD_PROGRESS_INTERVAL_S = 0.5

# Suffix for the partially-written file.  The final name only ever appears
# after the checksum matched, so a staged installer is always installable.
PARTIAL_SUFFIX = ".part"

# Extension per backend ``installer_type``.  An unknown type is refused
# rather than saved as ``.bin`` — Windows will not run an installer whose
# extension it does not recognise.
INSTALLER_EXTENSIONS = {
    "msi": ".msi",
    "dmg": ".dmg",
    "zip": ".zip",
}

# installer_type accepted per platform for a self-install.  Anything else
# (a Linux .deb, a mislabelled artifact) falls back to the browser.
SELF_INSTALL_TYPES = {
    "windows": ("msi",),
    "mac": ("dmg", "zip"),
}

# ============================================================================
# HELPER PROCESS
# ============================================================================

# How long the detached helper waits for Mixar to exit before giving up.
# A user who cancels the quit must not leave a helper that installs over a
# running app hours later.
HELPER_WAIT_FOR_EXIT_S = 300

# After Mixar exits, how long the Windows helper waits for every OTHER
# process running from the install directory (other Mixar windows, the
# asset-preview worker, MCP servers) before refusing to install. A file in
# use is replaced only at the next reboot, so installing anyway relaunches
# the old build. The app asks the user to close them first and waits for
# its own background work, so this is the safety net.
HELPER_WAIT_FOR_LOCKS_S = 60

# Before quitting, Restart & Update waits for Mixar's own background work
# running from the install directory (preview backfill, indexing renders):
# re-checked every BACKGROUND_POLL_S on the UI thread, given up after
# BACKGROUND_WAIT_MAX_S — the helper's own wait then covers what is left.
BACKGROUND_POLL_S = 2.0
BACKGROUND_WAIT_MAX_S = 600

# Written into update-result.txt so the next launch knows which fields the
# helper that ran could have recorded. 1 = version/stage/exit only. 2 adds
# attempt_id, from_version, wait_s, the registry's installed_version /
# install_location, msi_error, locks and relaunch/relaunch_kind. 3 records
# the same fields and hardens the run: delayed expansion off, every tool
# from System32 by absolute path, the staged MSI's signer pinned to the
# certificate thumbprint verified in-app, and the previous MSI log kept.
HELPER_VERSION = 3

# ============================================================================
# STATE MACHINE
# ============================================================================


class UpdateState(Enum):
    """Lifecycle states for the update checker."""

    IDLE = "idle"
    CHECKING = "checking"
    AVAILABLE = "available"
    ERROR = "error"


class InstallState(Enum):
    """Lifecycle states for the in-app installer.

    Orthogonal to :class:`UpdateState`, which only tracks *detection*.
    """

    IDLE = "idle"
    DOWNLOADING = "downloading"
    READY = "ready"          # installer staged + checksum verified
    INSTALLING = "installing"  # helper spawned, quit in progress
    FAILED = "failed"
    UNSUPPORTED = "unsupported"  # this install can't self-update
