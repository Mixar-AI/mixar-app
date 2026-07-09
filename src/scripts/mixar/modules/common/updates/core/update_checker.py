# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update Checker Utilities

Pure functions for version comparison, install-ID management,
API-response parsing, and skip-version persistence.  No Blender
operator code — safe to call from any thread.
"""

import os
import re
import sys
import uuid
from typing import Optional, Tuple

from mixar.config.logging_config import get_logger

from ..constants import INSTALL_ID_FILENAME, PLATFORM_MAP, SKIPPED_VERSION_FILENAME
from .state import UpdateInfo

logger = get_logger(__name__)

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_ALLOWED_INSTALLER_TYPES = frozenset({"dmg", "exe", "msi", "AppImage"})
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


# ============================================================================
# Version helpers
# ============================================================================


def parse_semver(version_str: str) -> Tuple[int, ...]:
    """Parse a ``X.Y.Z`` version string into a comparable int tuple.

    Ignores any pre-release suffix (e.g. ``1.4.0-beta`` → ``(1, 4, 0)``).
    Returns ``(0,)`` for unparseable input so callers never crash.
    """
    try:
        base = version_str.split("-")[0].strip()
        return tuple(int(p) for p in base.split("."))
    except (ValueError, AttributeError):
        return (0,)


def is_newer(remote: str, local: str) -> bool:
    """Return True when *remote* is strictly newer than *local*."""
    return parse_semver(remote) > parse_semver(local)


# ============================================================================
# Install ID
# ============================================================================


def _install_id_path() -> str:
    """Return the full path to the install-ID file in Blender's USER config dir."""
    import bpy

    config_dir = os.path.join(bpy.utils.resource_path("USER"), "config")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, INSTALL_ID_FILENAME)


def get_or_create_install_id() -> str:
    """Read or generate a persistent UUID4 install identifier."""
    path = _install_id_path()
    try:
        if os.path.isfile(path):
            with open(path, "r") as f:
                existing = f.read().strip()
                if existing:
                    return existing
    except OSError:
        pass

    new_id = uuid.uuid4().hex
    try:
        with open(path, "w") as f:
            f.write(new_id)
    except OSError:
        pass
    return new_id


# ============================================================================
# Platform
# ============================================================================


def get_platform_key() -> str:
    """Map ``sys.platform`` to the API platform parameter."""
    for prefix, key in PLATFORM_MAP.items():
        if sys.platform.startswith(prefix):
            return key
    return sys.platform


# ============================================================================
# Current version
# ============================================================================


def get_current_version() -> str:
    """Read the app version from ``mixar.json``."""
    from mixar.config.config import get_config

    return get_config().get("app_info", {}).get("version", "0.0.0")


# ============================================================================
# Parse API response
# ============================================================================


def parse_update_response(raw: dict) -> Optional[UpdateInfo]:
    """Convert the raw API ``/check`` response dict into an ``UpdateInfo``.

    Handles the server envelope: ``{"status": "success", "data": {...}}``.
    The inner ``data`` dict contains update fields with a nested
    ``download`` object for binary info.

    Returns ``None`` when the response indicates *no update available*.
    """
    # Unwrap server envelope — the payload may already be unwrapped
    data = raw.get("data", raw) if isinstance(raw, dict) else raw

    if not isinstance(data, dict) or not data.get("update_available", False):
        return None

    download = data.get("download") or {}

    latest_version = data.get("latest_version", "") or ""
    if not _SEMVER_RE.match(latest_version):
        logger.error("Rejecting update: malformed latest_version %r", latest_version)
        return None

    raw_installer_type = download.get("installer_type")
    if raw_installer_type is None or raw_installer_type == "":
        installer_type = ""
    else:
        installer_type = str(raw_installer_type).lstrip(".")
        if installer_type not in _ALLOWED_INSTALLER_TYPES:
            logger.error("Rejecting update: unknown installer_type %r", raw_installer_type)
            return None

    sha256 = (download.get("sha256") or "").strip()
    if not _SHA256_HEX_RE.match(sha256):
        logger.info(
            "Skipping update %s: server SHA-256 missing or invalid (%r)",
            latest_version, sha256,
        )
        return None

    return UpdateInfo(
        latest_version=latest_version,
        current_version=data.get("current_version", ""),
        severity=data.get("severity", "normal"),
        force_update=data.get("force_update", False),
        unsupported=data.get("unsupported", False),
        changelog_summary=data.get("changelog_summary", ""),
        changelog_url=data.get("changelog_url", ""),
        download_url=download.get("url", ""),
        download_size_bytes=download.get("size_bytes", 0),
        sha256=sha256,
        installer_type=installer_type,
    )


# ============================================================================
# Skip-version persistence
# ============================================================================


def _skipped_version_path() -> str:
    import bpy

    config_dir = os.path.join(bpy.utils.resource_path("USER"), "config")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, SKIPPED_VERSION_FILENAME)


def get_skipped_version() -> str:
    """Return the version the user chose to skip, or ``""``."""
    path = _skipped_version_path()
    try:
        if os.path.isfile(path):
            with open(path, "r") as f:
                return f.read().strip()
    except OSError:
        pass
    return ""


def set_skipped_version(version: str) -> None:
    """Persist *version* so future checks skip it."""
    try:
        with open(_skipped_version_path(), "w") as f:
            f.write(version)
    except OSError:
        pass


def clear_skipped_version() -> None:
    """Remove the skip file so all versions are eligible again."""
    try:
        path = _skipped_version_path()
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
