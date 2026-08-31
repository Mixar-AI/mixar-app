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

from ..constants import ANNOUNCED_VERSION_FILENAME, INSTALL_ID_FILENAME, PLATFORM_MAP
from .state import UpdateInfo

logger = get_logger(__name__)

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


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


def get_runtime_version() -> Optional[str]:
    """Version of the running binary, for reporting to the backend.

    Prefers the compiled-in Mixar version (``bpy.app.version_string``, built
    from ``MIXAR_VERSION`` in ``BKE_blender_version.h``) over the ``mixar.json``
    value, which is served from a process-lifetime config cache and can go
    stale. When ``version_string`` merely echoes Blender's own version tuple
    (i.e. not a Mixar build — e.g. scripts running under stock Blender), falls
    back to :func:`get_current_version`. Returns ``None`` when no real version
    is known — callers must then omit the version rather than send a
    placeholder.
    """
    version = ""
    try:
        import bpy

        match = re.search(r"\d+\.\d+\.\d+", bpy.app.version_string or "")
        if match:
            candidate = match.group(0)
            blender_version = ".".join(str(c) for c in bpy.app.version)
            if candidate != blender_version:
                version = candidate
    except Exception:
        pass
    if not version or version == "0.0.0":
        version = get_current_version()
    if not version or version == "0.0.0":
        return None
    return version


# ============================================================================
# Parse API response
# ============================================================================


def parse_update_response(raw: dict) -> Optional[UpdateInfo]:
    """Convert the raw API ``/check`` response dict into an ``UpdateInfo``.

    Handles the server envelope: ``{"status": "success", "data": {...}}``.
    The nested ``download`` object carries the installer artifact for this
    platform; a release published without one (or with a type this
    platform can't apply) still yields an ``UpdateInfo`` — the update is
    real, it just routes to the browser instead of the in-app installer.

    Returns ``None`` when the response indicates *no update available*.
    """
    # Unwrap server envelope — the payload may already be unwrapped
    data = raw.get("data", raw) if isinstance(raw, dict) else raw

    if not isinstance(data, dict) or not data.get("update_available", False):
        return None

    latest_version = data.get("latest_version", "") or ""
    if not _SEMVER_RE.match(latest_version):
        logger.error("Rejecting update: malformed latest_version %r", latest_version)
        return None

    download = data.get("download")
    if not isinstance(download, dict):
        download = {}

    # Only https installer URLs are ever fetched: this file is about to be
    # run, elevated, on the user's machine.
    download_url = str(download.get("url") or "")
    if download_url and not download_url.startswith("https://"):
        logger.error("Ignoring non-https installer URL for %s", latest_version)
        download_url = ""

    try:
        download_size = int(download.get("size_bytes") or 0)
    except (TypeError, ValueError):
        download_size = 0

    return UpdateInfo(
        latest_version=latest_version,
        current_version=data.get("current_version", ""),
        severity=data.get("severity", "normal"),
        force_update=data.get("force_update", False),
        unsupported=data.get("unsupported", False),
        changelog_summary=data.get("changelog_summary", ""),
        changelog_url=data.get("changelog_url", ""),
        browser_download_url=data.get("browser_download_url", ""),
        download_url=download_url,
        download_sha256=str(download.get("sha256") or "").strip().lower(),
        download_size=download_size,
        installer_type=str(download.get("installer_type") or "").strip().lower(),
    )


# ============================================================================
# Severity
# ============================================================================


def is_forced(info) -> bool:
    """A forced or unsupported update must be installed — no skipping."""
    return bool(info.force_update or info.unsupported)


# ============================================================================
# Announcement persistence
# ============================================================================
#
# The topbar badge shows update status permanently, so the toast only has
# to announce the news — repeating it on every launch would be nagging,
# not information.  What is persisted is therefore "we already told them
# about X", not "the user refused X": the update is never withheld, only
# demoted from an interrupt to the badge, which re-opens the toast on
# click.  Two stages earn an interruption per version — the update
# becoming available, and the installer becoming ready to apply.

ANNOUNCE_AVAILABLE = "available"
ANNOUNCE_READY = "ready"


def _announced_version_path() -> str:
    import bpy

    config_dir = os.path.join(bpy.utils.resource_path("USER"), "config")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, ANNOUNCED_VERSION_FILENAME)


def get_announced_stage(version: str) -> str:
    """Return the last stage announced for *version*, or ``""``.

    A different version reads back as never announced, so a new release
    always gets its toast without anything needing to be cleared.
    """
    if not version:
        return ""
    try:
        path = _announced_version_path()
        if not os.path.isfile(path):
            return ""
        with open(path, "r") as f:
            recorded, _, stage = f.read().strip().partition("=")
    except OSError:
        return ""
    return stage if recorded == version else ""


def set_announced_stage(version: str, stage: str) -> None:
    """Record that *stage* has been announced for *version*."""
    if not version:
        return
    try:
        with open(_announced_version_path(), "w") as f:
            f.write(f"{version}={stage}")
    except OSError:
        pass
