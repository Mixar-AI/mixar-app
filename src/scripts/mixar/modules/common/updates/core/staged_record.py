# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Staged-Update Record

``staged-update.json`` sits next to the staged installer. The download
worker writes it once the checksum and signature checks passed: the
version, the installer's size and modification time, the verdict and
the signer the helper pins. It is how a launch after a session that
never quit normally (a crash, a force quit, a kill) finds an
update that is ready, without downloading or hashing 400 MB again: the
installer counts as the one verified only while its size and mtime
still match (:func:`intact`).

It names the copy of Mixar the download is for (``target``, the install
location the worker checked): the staging directory is per user, not per
copy, so a second copy (a build beside the installed app, a test copy)
must never install another copy's download at its own launch.

It also remembers how installs nobody asked for went, so they stop
instead of repeating: ``launch_attempts`` (a launch that installs) and
``failures`` (attempts the helper reported as failed). Both survive a
re-verification of the same version and reset with a new one.

Filesystem only — imports no ``bpy``; never raises.
"""

import json
import os
import time

from mixar.config.logging_config import get_logger

from ..constants import STAGED_RECORD_NAME

logger = get_logger(__name__)

# Counters carried over when the same version is verified again.
_COUNTERS = ("launch_attempts", "failures")


def record_path(directory: str) -> str:
    return os.path.join(directory, STAGED_RECORD_NAME)


def read(directory: str):
    """The record in *directory* as a dict, or None (missing, unreadable)."""
    try:
        with open(record_path(directory), "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _write(directory: str, record: dict) -> bool:
    path = record_path(directory)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as e:
        logger.warning("Could not write the staged-update record: %s", e)
        try:
            os.remove(temporary)
        except OSError:
            pass
        return False
    return True


def write_ready(directory: str, *, version, installer_path, installer_type,
                download_url, sha256, verified, signer, target="") -> bool:
    """Record the installer the worker just verified (download thread)."""
    try:
        status = os.stat(installer_path)
    except OSError as e:
        logger.warning("Staged installer vanished before it was recorded: %s", e)
        return False
    previous = read(directory) or {}
    same = previous.get("version") == version and previous.get("installer") == installer_path
    record = {
        "version": version,
        "installer": installer_path,
        "installer_type": installer_type or "",
        "download_url": download_url or "",
        "sha256": (sha256 or "").lower(),
        "size": status.st_size,
        "mtime_ns": status.st_mtime_ns,
        "verified": bool(verified),
        "signer": signer if verified else "",
        "target": target or "",
        "written_at": time.time(),
    }
    for counter in _COUNTERS:
        record[counter] = _as_count(previous.get(counter)) if same else 0
    return _write(directory, record)


def _as_count(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def bump(directory: str, counter: str, version: str = "") -> int:
    """Add one to *counter*; returns the new value, 0 when nothing was
    recorded (no record, another version, or the write failed).

    With *version*, only a record for that version is counted against.
    """
    record = read(directory)
    if record is None or (version and record.get("version") != version):
        return 0
    record[counter] = _as_count(record.get(counter)) + 1
    if not _write(directory, record):
        return 0
    return record[counter]


def remove(directory: str) -> None:
    try:
        os.remove(record_path(directory))
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.debug("Could not remove the staged-update record: %s", e)


def discard(directory: str, record) -> None:
    """Delete *record* and the installer it names — only one inside *directory*."""
    installer = str((record or {}).get("installer") or "")
    if installer and os.path.dirname(os.path.abspath(installer)) == os.path.abspath(directory):
        try:
            os.remove(installer)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.debug("Could not remove a staged installer: %s", e)
    remove(directory)


def age_s(record, now=None):
    """Seconds since *record* was written; None when it does not say."""
    try:
        written = float(record["written_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return (time.time() if now is None else now) - written


def intact(record) -> bool:
    """Is the installer still the file that was verified (size and mtime)?"""
    try:
        status = os.stat(record["installer"])
        return (status.st_size == int(record["size"])
                and status.st_mtime_ns == int(record["mtime_ns"]))
    except (KeyError, OSError, TypeError, ValueError):
        return False
