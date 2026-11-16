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

# Written by the app right after it spawns the helper, deleted by the helper
# just before it relaunches Mixar (or gives up). While it names a live
# helper, a Mixar the user opens by hand says "finishing an update" and
# quits instead of running half-replaced files, and the staging purge
# leaves the helper and its installer alone (``core/install_marker.py``).
HELPER_MARKER_NAME = "update-in-progress.json"

# A Mixar turned away by that marker appends its PID here. The helper then
# waits for those PIDs to exit before it swaps or reopens anything, and an
# install on quit (which otherwise leaves Mixar closed) reopens Mixar for
# them when it is done.
HELPER_REOPEN_NAME = "update-reopen-requests.txt"

# Written by the download worker once an installer is staged and verified:
# what was checked (size, mtime, signature) and how silent installs of it
# went. A launch after a crash or force quit installs from it without a
# re-download or re-hash (``core/staged_record.py``).
STAGED_RECORD_NAME = "staged-update.json"

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

# Staging failure reasons (``core/failure.py``) a fresh download can fix;
# only these get a Retry button. A checksum or signature mismatch, a full
# disk or a read-only one fails the same way again.
RETRYABLE_FAILURE_REASONS = frozenset({
    "http_error", "network_error", "timeout", "truncated_download",
    "permission_denied", "filesystem_error", "unexpected_error",
})

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

# A marker older than this is stale whatever its PID says: the helper's
# own waits (HELPER_WAIT_FOR_EXIT_S + HELPER_WAIT_FOR_LOCKS_S = 6 min) plus
# HELPER_INSTALL_MARGIN_S for the UAC prompt, the MSI (or the macOS copy
# and swap) and the relaunch — 15 min in all. A helper still running past
# it is stuck (say, an unanswered UAC prompt), and must not keep the user
# out of Mixar.
HELPER_INSTALL_MARGIN_S = 540
HELPER_MARKER_MAX_AGE_S = (
    HELPER_WAIT_FOR_EXIT_S + HELPER_WAIT_FOR_LOCKS_S + HELPER_INSTALL_MARGIN_S
)
# The macOS helper never swaps the bundle once the marker it was started
# with could have gone stale: past this (a minute inside the age cap,
# counted from the helper's own start, which precedes the marker's
# written_at) a Mixar opened meanwhile is no longer turned away and may be
# running from the bundle, so the helper gives up (stage=expired) instead.
HELPER_SWAP_DEADLINE_S = HELPER_MARKER_MAX_AGE_S - 60
# How long a Mixar opened mid-install shows "finishing an update" before
# it quits — well inside HELPER_WAIT_FOR_LOCKS_S, so on Windows the files it
# holds are released before the helper gives up on them.
MID_INSTALL_QUIT_DELAY_S = 5.0

# Written into update-result.txt so the next launch knows which fields the
# helper that ran could have recorded. 1 = version/stage/exit only. 2 adds
# attempt_id, from_version, wait_s, the registry's installed_version /
# install_location, msi_error, locks and relaunch/relaunch_kind. 3 records
# the same fields and hardens the run: delayed expansion off, every tool
# from System32 by absolute path, the staged MSI's signer pinned to the
# certificate thumbprint verified in-app, and the previous MSI log kept.
# 4 ends Mixar connectors (an AI app's MCP server python running from the
# install directory) before the lock wait instead of waiting for them.
# 5 runs the MSI with /passive instead of /qb!, so Restart Manager's
# files-in-use prompt can never block an unattended update.
# 6 records the trigger and can leave Mixar closed (install on quit), then
# reopens it only for a launch turned away meanwhile (relaunch_kind=skipped).
# 7 runs msiexec without elevation for a per-user install (one prompted
# retry on 1625 after a click), passes ALLUSERS=1 for a machine install,
# reads the installed version and location from Windows Installer for this
# account, and records ``elevation`` and the MSI's ``msi_refusal`` (#2079).
# 8 takes every path, the version and the attempt id from its environment,
# so the script text is ASCII and a non-ASCII profile name survives.
# The macOS helper writes helper_version too (from 6; the number is shared,
# so it reports 8 with the Windows one); installing on quit or at launch it
# waits up to HELPER_WAIT_FOR_LOCKS_S for every Mixar process still running
# from the bundle (stage=locked, locks=) and gives up past
# HELPER_SWAP_DEADLINE_S (stage=expired).
HELPER_VERSION = 8

# What started an install (``update.install_started`` / ``install_result``
# ``trigger``, echoed by the helper): the Restart & Update click, a normal
# quit, or the launch after a session that never quit normally.
TRIGGER_CLICK = "click"
TRIGGER_QUIT = "quit"
TRIGGER_LAUNCH = "launch"
TRIGGERS = (TRIGGER_CLICK, TRIGGER_QUIT, TRIGGER_LAUNCH)

# The helper's bounds on the PIDs in HELPER_REOPEN_NAME: how long it waits
# for them to exit (they quit MID_INSTALL_QUIT_DELAY_S after their toast),
# and, installing on quit, how long it gives a launch that read the marker
# just before it went to leave its request.
HELPER_REOPEN_WAIT_S = 30
HELPER_REOPEN_GRACE_S = 2

# ============================================================================
# WINDOWS INSTALL SCOPE (#2079)
# ============================================================================

# The MSI's UpgradeCode: uuid5 of "Mixar" in packaging.cmake's namespace
# (pinned by tests/test_windows_install_scope.py). Windows Installer lists
# the Mixar installs this account can see under it.
MSI_UPGRADE_CODE = "{62855CF0-CD33-57A1-B073-9F3C25B723C6}"
# The installer refuses an install it cannot do from its scope before any
# change (WIX.template, "SCOPE REFUSALS"); the helper copies the value of
# this property from the MSI log into update-result.txt as msi_refusal.
MSI_REFUSAL_PROPERTY = "MIXAR_SCOPE_REFUSAL"
MSI_REFUSALS = ("machine", "needs_admin", "system")
# Where the installer put Mixar and why (installer_ca/mixar_msi_scope.c:
# MIXAR_SCOPE_ACTION / MIXAR_SCOPE_REASON), copied from the MSI log by the
# helper as scope_action / scope_reason.
MSI_SCOPE_ACTIONS = ("fresh", "keep", "move", "in_place", "in_place_program_files",
                     "beside", "relaunch", "refuse")
MSI_SCOPE_REASONS = ("machine_scope", "system_account", "machine_product", "other_account",
                     "not_elevated", "command_line", "location_unknown", "own_folder",
                     "other_session_user", "path_policy", "installer_policy", "shared",
                     "files_in_use", "own_program_files")
# HKCU values the installer writes: the folder an install moved Mixar out of
# (MixarMovedFrom), and that the file type is still to be registered by the
# app because the install ran elevated (MixarRegisterPending).
MIXAR_REGISTRY_KEY = "Software\\Mixar\\Mixar"
MOVED_FROM_VALUE = "moved_from"
REGISTER_PENDING_VALUE = "register_pending"
# Per-user memory (``add_config``) of what an earlier attempt learned:
# the version an installer refused (it is offered as a download from then
# on) and that Windows policy refuses installs without an administrator.
INSTALLER_REFUSED_CONFIG_KEY = "update_installer_refused"
USER_INSTALLS_BLOCKED_CONFIG_KEY = "update_user_installs_blocked"
# The attempt ids this user's own helpers ran (newest last): a result found
# in another account's staging folder is read only when it names one.
UPDATE_ATTEMPTS_CONFIG_KEY = "update_attempt_ids"
UPDATE_ATTEMPTS_KEPT = 8
# The install folder whose first start after the move read the result the
# old app's helper left in the shared staging folder.
MOVE_RESULT_READ_CONFIG_KEY = "update_move_result_read"
# The install whose shortcuts and taskbar pins were repointed after the move.
SHORTCUTS_REPAIRED_CONFIG_KEY = "update_shortcuts_repaired"

# Per-user setting (``add_config``; Edit > Preferences > System > Updates):
# install a staged update when Mixar quits, or at the next launch when it
# never quit normally. On unless the user turns it off.
INSTALL_ON_QUIT_CONFIG_KEY = "install_updates_on_quit"

# A staged version stops installing by itself (quit or launch) once this
# many attempts failed; Restart & Update still offers it.
SILENT_INSTALL_MAX_FAILURES = 2
# A launch installs a staged version at most this often: a launch install
# that did not take must never turn every launch into a quit.
LAUNCH_INSTALL_MAX_ATTEMPTS = 1
# How long the launch that installs shows "Mixar is finishing an update"
# before it quits. Opening a file or editing anything in that time cancels.
LAUNCH_INSTALL_QUIT_DELAY_S = 3.0
# A launch installs only a download verified this recently (the record's
# ``written_at``; every update check that offers the version re-verifies and
# rewrites it). An older one waits for the update check, which re-verifies
# it or, when the backend no longer offers it, deletes it.
STAGED_RECORD_MAX_AGE_S = 24 * 3600

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
