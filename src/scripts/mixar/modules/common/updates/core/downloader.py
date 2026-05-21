# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Background Installer Downloader

Streams the installer binary to a temp directory using ``urllib.request``
(suitable for 500 MB+ files).  Writes progress to the shared
``UpdateStateManager`` so the main thread can display it.

All public functions are designed to be called from a **daemon thread**.
"""

import hashlib
import hmac
import os
import re
import tempfile
import time
import urllib.request
from typing import Optional

_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")

from mixar.config.logging_config import get_logger

from ..constants import (
    DEFAULT_DOWNLOAD_CHUNK_SIZE,
    DEFAULT_MAX_DOWNLOAD_RETRIES,
    UPDATES_CACHE_DIR,
)
from .state import UpdateInfo, get_update_state

logger = get_logger(__name__)


def _cache_dir() -> str:
    """Return (and ensure) the update-cache directory under the system temp."""
    path = os.path.join(tempfile.gettempdir(), UPDATES_CACHE_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _expected_filename(info: UpdateInfo) -> str:
    """Derive a deterministic filename from version + installer type."""
    ext = info.installer_type or "bin"
    if not ext.startswith("."):
        ext = f".{ext}"
    return f"mixar-{info.latest_version}{ext}"


def _verify_sha256(filepath: str, expected: str) -> bool:
    """Return True iff *filepath* matches *expected* SHA-256 hex digest.

    A missing, placeholder, or malformed *expected* is treated as a
    verification failure — never a free pass. Old releases that predate
    the SHA pipeline (server returns ``"unavailable"``) are filtered out
    upstream in ``parse_update_response``; if one slips through, we
    refuse here.
    """
    if not expected or not _SHA256_HEX_RE.match(expected):
        logger.error(
            "Refusing to verify installer: server SHA-256 missing or malformed (%r)",
            expected,
        )
        return False
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return hmac.compare_digest(h.hexdigest().lower(), expected.lower())


# ============================================================================
# Public API
# ============================================================================


def get_cached_installer(info: UpdateInfo) -> Optional[str]:
    """Check for a previously downloaded (and SHA-verified) installer.

    Returns the file path if valid, otherwise ``None``.
    """
    path = os.path.join(_cache_dir(), _expected_filename(info))
    if not os.path.isfile(path):
        return None
    if not _verify_sha256(path, info.sha256):
        logger.warning("Cached installer failed SHA verification, removing")
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    return path


def download_update(
    info: UpdateInfo,
    chunk_size: int = DEFAULT_DOWNLOAD_CHUNK_SIZE,
    max_retries: int = DEFAULT_MAX_DOWNLOAD_RETRIES,
) -> Optional[str]:
    """Download the installer, writing progress to shared state.

    Uses a ``.part`` intermediate file so incomplete downloads are never
    mistaken for finished ones.  Respects ``state.cancel_requested``.

    Returns:
        Absolute path to the verified installer, or ``None`` on failure.
    """
    state = get_update_state()
    url = info.download_url
    if not url:
        logger.error("No download URL in update info")
        state.set_error("No download URL provided")
        return None

    dest = os.path.join(_cache_dir(), _expected_filename(info))
    part = dest + ".part"

    for attempt in range(1, max_retries + 1):
        if state.cancel_requested:
            logger.info("Download cancelled by user")
            _cleanup(part)
            return None

        try:
            logger.info(
                "Download attempt %d/%d: %s", attempt, max_retries, url
            )
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                state.update_progress(0)
                downloaded = 0
                start_time = time.monotonic()

                with open(part, "wb") as f:
                    while True:
                        if state.cancel_requested:
                            logger.info("Download cancelled mid-stream")
                            _cleanup(part)
                            return None

                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed = time.monotonic() - start_time
                        speed = downloaded / elapsed if elapsed > 0 else 0.0
                        state.update_progress(downloaded, speed)

            # Verify
            if not _verify_sha256(part, info.sha256):
                logger.warning("SHA mismatch on attempt %d", attempt)
                _cleanup(part)
                continue

            # Rename .part → final
            if os.path.isfile(dest):
                os.remove(dest)
            os.rename(part, dest)
            _purge_old_installers(keep=os.path.basename(dest))
            logger.info("Download complete: %s (%d bytes)", dest, downloaded)
            return dest

        except Exception as e:
            logger.warning("Download attempt %d failed: %s", attempt, e)
            _cleanup(part)
            if attempt == max_retries:
                state.set_error(f"Download failed after {max_retries} attempts: {e}")
                return None

    return None


def _purge_old_installers(keep: str) -> None:
    """Remove any old ``mixar-*`` installers in the cache dir except *keep*."""
    cache = _cache_dir()
    for name in os.listdir(cache):
        if name.startswith("mixar-") and name != keep and not name.endswith(".part"):
            try:
                os.remove(os.path.join(cache, name))
                logger.info("Removed old cached installer: %s", name)
            except OSError:
                pass


def _cleanup(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
